#!/usr/bin/env python3
"""Атомарно подготовить ротацию принятой snapshot-пары без GitHub доступа."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from overlay_policy import (  # noqa: E402
    Pair, Package, PolicyError, ROOT, State, ebuild_path, pair_payload,
    read_state, state_payload, update_readmes, validate_state_ebuilds,
)


class PrepareError(PolicyError):
    """Кандидат нельзя безопасно включить в overlay."""


SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
UMBRIEL_PATTERN = re.compile(r"^\d+\.\d+\.\d+_pre\d{14}$")
PORTAL_PATTERN = re.compile(r"^\d+\.\d+\.\d+_p\d{14}$")


def candidate_pair(payload: object) -> Pair:
    if not isinstance(payload, dict) or not isinstance(payload.get("pair"), dict):
        raise PrepareError("Discovery не передал пару кандидата.")
    try:
        um, portal = payload["pair"]["umbriel"], payload["pair"]["portal"]
        pair = Pair(Package(um["version"], um["sha"]), Package(portal["version"], portal["sha"]))
    except (KeyError, TypeError) as error:
        raise PrepareError("Некорректная пара кандидата.") from error
    for name, package, pattern in (("Umbriel", pair.umbriel, UMBRIEL_PATTERN),
                                   ("portal", pair.portal, PORTAL_PATTERN)):
        if not isinstance(package.version, str) or not pattern.fullmatch(package.version):
            raise PrepareError(f"Некорректная версия кандидата {name}: {package.version!r}.")
        if not isinstance(package.sha, str) or not SHA_PATTERN.fullmatch(package.sha):
            raise PrepareError(f"Некорректный полный SHA кандидата {name}.")
    return pair


def rotate(root: Path, candidate: Pair, *, dry_run: bool = False) -> dict[str, object]:
    """Собрать новую пару, сохранить прошлую current и удалить legacy ebuilds."""
    old = read_state(root)
    if candidate == old.current:
        return {"outcome": "up-to-date", "current": pair_payload(old.current), "previous": None, "removed": None}
    if candidate.umbriel.sha == old.current.umbriel.sha and candidate.portal.sha == old.current.portal.sha:
        raise PrepareError("Новая пара не содержит обновлений.")
    for package, new in (("umbriel", candidate.umbriel), ("portal", candidate.portal)):
        old_package = getattr(old.current, package)
        source_path = root / ebuild_path(package, old_package.version)
        if not source_path.is_file():
            raise PrepareError(f"Не найден исходный ebuild {source_path.name}.")
        if new.version == old_package.version and new.sha != old_package.sha:
            raise PrepareError(f"Новая версия {package} совпала по имени, но указывает на другой SHA.")
        target = root / ebuild_path(package, new.version)
        if new.version != old_package.version and target.exists():
            raise PrepareError(f"Ebuild кандидата уже существует: {target.name}.")
    if dry_run:
        return {"outcome": "dry-run", "current": pair_payload(candidate),
                "previous": pair_payload(old.current),
                "removed": None if old.previous is None else pair_payload(old.previous),
                "portal_reused": candidate.portal.sha == old.current.portal.sha}

    keep = State(candidate, old.current)
    # Подготовка идёт в отдельной копии workspace; состояние и каталог файлов
    # попадают в handoff только целиком после проверки всех ebuild и ссылок.
    sources = {
        "umbriel": root / ebuild_path("umbriel", old.current.umbriel.version),
        "portal": root / ebuild_path("portal", old.current.portal.version),
    }
    targets = {
        "umbriel": root / ebuild_path("umbriel", candidate.umbriel.version),
        "portal": root / ebuild_path("portal", candidate.portal.version),
    }
    for package in ("umbriel", "portal"):
        if targets[package] == sources[package]:
            continue
        text = sources[package].read_text(encoding="utf-8")
        replaced, count = re.subn(r'MY_COMMIT="[0-9a-f]{40}"', f'MY_COMMIT="{getattr(candidate, package).sha}"', text)
        if count != 1:
            raise PrepareError(f"В {sources[package].name} ожидалось одно поле MY_COMMIT.")
        targets[package].write_text(replaced, encoding="utf-8")
    for package, directory in (("umbriel", root / "gui-wm/umbriel"),
                               ("portal", root / "gui-libs/xdg-desktop-portal-umbriel")):
        keep_versions = {getattr(pair, package).version for pair in (keep.current, keep.previous) if pair}
        for path in directory.glob("*.ebuild"):
            if not any(path.name == Path(ebuild_path(package, version)).name for version in keep_versions):
                path.unlink()
    state_path = root / "automation/accepted-pairs.json"
    state_path.write_text(json.dumps(state_payload(keep), indent=2) + "\n", encoding="utf-8")
    update_readmes(root, keep)
    validate_state_ebuilds(root)
    return {"outcome": "prepared", "current": pair_payload(candidate),
            "previous": pair_payload(old.current),
            "removed": None if old.previous is None else pair_payload(old.previous),
            "portal_reused": candidate.portal.sha == old.current.portal.sha}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--watch-result", type=Path, required=True)
    parser.add_argument("--result-json", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    try:
        watched = json.loads(args.watch_result.read_text(encoding="utf-8"))
        outcome = watched.get("outcome") if isinstance(watched, dict) else None
        if outcome != "candidate":
            raise PrepareError(f"Нет кандидата для подготовки (outcome={outcome!r}).")
        result = rotate(args.repository_root, candidate_pair(watched), dry_run=args.dry_run)
        result.update({"base_commit": watched.get("base_commit"), "packaging_changes": watched.get("packaging_changes")})
        args.result_json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        if args.summary:
            args.summary.write_text(f"## Umbriel snapshot preparation\n\n- Результат: `{result['outcome']}`\n- Portal ebuild повторно используется: `{result.get('portal_reused', False)}`\n", encoding="utf-8")
        return 0
    except (OSError, json.JSONDecodeError, PolicyError) as error:
        print(f"Umbriel preparation error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
