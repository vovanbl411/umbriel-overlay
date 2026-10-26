#!/usr/bin/env python3
"""Собрать, проверить и применить ограниченный artifact для Draft PR."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from overlay_policy import (  # noqa: E402
    PolicyError, ebuild_path, pair_payload, read_state, validate_state_ebuilds,
    version_block,
)

SCHEMA = 1
SHA = re.compile(r"^[0-9a-f]{40}$")
MAX_SIZE = 5 * 1024 * 1024
MANIFESTS = ("gui-wm/umbriel/Manifest", "gui-libs/xdg-desktop-portal-umbriel/Manifest")
PACKAGING_PATHS = frozenset(
    f"{repository}/{path}"
    for repository in ("noctalia-dev/umbriel", "noctalia-dev/xdg-desktop-portal-umbriel")
    for path in ("VERSION", "flake.lock", "PACKAGING.md", "meson.build", "meson_options.txt")
)


class HandoffError(PolicyError):
    """Artifact не соответствует allowlist или ожидаемому base commit."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise HandoffError(f"handoff содержит повторяющееся поле {key!r}.")
        result[key] = value
    return result


def _allowed_overlay_files(state_root: Path) -> set[str]:
    state = read_state(state_root)
    paths = {"README.md", "automation/accepted-pairs.json", *MANIFESTS}
    for pair in (state.current, state.previous):
        if pair:
            paths.update((ebuild_path("umbriel", pair.umbriel.version), ebuild_path("portal", pair.portal.version)))
    return paths


def _validate_tree(root: Path) -> set[str]:
    if not root.is_dir() or root.is_symlink():
        raise HandoffError("Artifact overlay должен быть обычным каталогом.")
    actual: set[str] = set()
    for path in root.rglob("*"):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode) or path.is_symlink() or path.stat().st_size > MAX_SIZE:
            raise HandoffError(f"Artifact содержит небезопасный файл: {path.relative_to(root)}.")
        actual.add(path.relative_to(root).as_posix())
    return actual


def create(repository_root: Path, destination: Path, *, base_commit: str,
           packaging_changes: dict[str, dict[str, str]], removed_pair: object = None) -> None:
    validate_state_ebuilds(repository_root)
    if not SHA.fullmatch(base_commit):
        raise HandoffError("base commit должен быть полным Git SHA.")
    allowed = _allowed_overlay_files(repository_root)
    if destination.exists():
        shutil.rmtree(destination)
    overlay = destination / "overlay"
    for relative in sorted(allowed):
        source = repository_root / relative
        if not source.is_file():
            raise HandoffError(f"Подготовка не создала обязательный файл {relative}.")
        target = overlay / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    metadata = {"schema_version": SCHEMA, "base_commit": base_commit,
                "packaging_changes": packaging_changes, "removed_pair": removed_pair}
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "handoff.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    validate(destination)


def validate(artifact: Path) -> tuple[Path, dict[str, object]]:
    if artifact.is_symlink() or not artifact.is_dir():
        raise HandoffError("Корень artifact должен быть обычным каталогом.")
    if {item.name for item in artifact.iterdir()} != {"handoff.json", "overlay"}:
        raise HandoffError("Artifact содержит неожиданные корневые файлы.")
    metadata_path = artifact / "handoff.json"
    if metadata_path.is_symlink() or not metadata_path.is_file() or metadata_path.stat().st_size > MAX_SIZE:
        raise HandoffError("В artifact отсутствует корректный handoff.json.")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise HandoffError("Не удалось прочитать handoff.json.") from error
    if not isinstance(metadata, dict) or set(metadata) != {"schema_version", "base_commit", "packaging_changes", "removed_pair"}:
        raise HandoffError("handoff.json содержит неожиданные поля.")
    if type(metadata["schema_version"]) is not int or metadata["schema_version"] != SCHEMA:
        raise HandoffError("Неподдерживаемая схема handoff artifact.")
    if not isinstance(metadata["base_commit"], str) or not SHA.fullmatch(metadata["base_commit"]):
        raise HandoffError("base_commit в artifact некорректен.")
    changes = metadata["packaging_changes"]
    if not isinstance(changes, dict) or set(changes) != PACKAGING_PATHS or any(
        not isinstance(values, dict) or set(values) != {"old", "new"}
        or any(not isinstance(value, str) or value not in {"absent"} and not SHA.fullmatch(value) for value in values.values())
        for path, values in changes.items()
    ):
        raise HandoffError("Список изменений upstream packaging files некорректен.")
    removed_pair = metadata["removed_pair"]
    if removed_pair is not None:
        if not isinstance(removed_pair, dict) or set(removed_pair) != {"umbriel", "portal"}:
            raise HandoffError("Удаляемая fallback-пара в handoff некорректна.")
        for package, pattern in (("umbriel", r"^\d+\.\d+\.\d+_pre\d{14}$"),
                                 ("portal", r"^\d+\.\d+\.\d+_p\d{14}$")):
            item = removed_pair[package]
            if (not isinstance(item, dict) or set(item) != {"version", "sha"}
                    or not isinstance(item["version"], str) or not re.fullmatch(pattern, item["version"])
                    or not isinstance(item["sha"], str) or not SHA.fullmatch(item["sha"])):
                raise HandoffError("Удаляемая fallback-пара содержит неверную версию или SHA.")
    overlay = artifact / "overlay"
    actual = _validate_tree(overlay)
    expected = _allowed_overlay_files(overlay)
    if actual != expected:
        raise HandoffError("Состав artifact не совпадает с allowlist принятой пары.")
    validate_state_ebuilds(overlay)
    return overlay, metadata


def expected_diff(repository_root: Path, overlay_root: Path) -> set[str]:
    expected = _allowed_overlay_files(overlay_root)
    # В diff входят также удаления старых или исторических ebuilds. Любые
    # прочие файлы пакетов и репозитория остаются вне допустимой зоны записи.
    package_dirs = ("gui-wm/umbriel", "gui-libs/xdg-desktop-portal-umbriel")
    for directory in package_dirs:
        current = repository_root / directory
        keep = {Path(path).name for path in expected if path.startswith(directory + "/") and path.endswith(".ebuild")}
        if current.exists():
            for path in current.glob("*.ebuild"):
                if path.name not in keep:
                    expected.add(path.relative_to(repository_root).as_posix())
    return expected


def apply(artifact: Path, repository_root: Path, *, expected_base: str,
          actual_base: str) -> set[str]:
    overlay, metadata = validate(artifact)
    if not SHA.fullmatch(expected_base) or not SHA.fullmatch(actual_base) or expected_base != actual_base:
        raise HandoffError("Base commit изменился; publication остановлена, нужен новый prepare run.")
    if metadata["base_commit"] != expected_base:
        raise HandoffError("Artifact подготовлен от другого base commit.")
    source_state = read_state(repository_root)
    target_state = read_state(overlay)
    if target_state.previous != source_state.current:
        raise HandoffError("Пара artifact не является ротацией текущего состояния base commit.")
    expected_removed = None if source_state.previous is None else pair_payload(source_state.previous)
    if metadata["removed_pair"] != expected_removed:
        raise HandoffError("Удаляемая fallback-пара не совпадает с состоянием base commit.")
    for package in ("umbriel", "portal"):
        previous_path = ebuild_path(package, getattr(target_state.previous, package).version)
        if (overlay / previous_path).read_bytes() != (repository_root / previous_path).read_bytes():
            raise HandoffError(f"Fallback ebuild изменён в artifact: {Path(previous_path).name}.")
    # Publish не доверяет изменённым контейнером ebuild: новый вариант обязан
    # совпадать с принятой заготовкой, где заменён ровно один закреплённый SHA.
    for package in ("umbriel", "portal"):
        old = getattr(source_state.current, package)
        new = getattr(target_state.current, package)
        source_path = repository_root / ebuild_path(package, old.version)
        target_path = overlay / ebuild_path(package, new.version)
        source_text = source_path.read_text(encoding="utf-8")
        replacement, count = re.subn(r'MY_COMMIT="[0-9a-f]{40}"',
                                     f'MY_COMMIT="{new.sha}"', source_text)
        if count != 1 or replacement != target_path.read_text(encoding="utf-8"):
            raise HandoffError(f"Кандидатный ebuild {target_path.name} отличается от разрешённой SHA-замены.")
    original_readme = (repository_root / "README.md").read_text(encoding="utf-8")
    # README разрешено менять только в выделенном блоке принятых пар.
    marker = re.compile(r"<!-- accepted-pairs:start -->.*?<!-- accepted-pairs:end -->", re.S)
    expected_readme, count = marker.subn(version_block(target_state), original_readme)
    if count != 1 or expected_readme != (overlay / "README.md").read_text(encoding="utf-8"):
        raise HandoffError("README artifact содержит изменения вне таблицы принятых пар.")
    allow = expected_diff(repository_root, overlay)
    for directory in (repository_root / "gui-wm/umbriel", repository_root / "gui-libs/xdg-desktop-portal-umbriel"):
        for path in directory.glob("*.ebuild"):
            if path.relative_to(repository_root).as_posix() in allow and path.name not in {
                Path(item).name for item in _allowed_overlay_files(overlay) if item.startswith(path.parent.relative_to(repository_root).as_posix() + "/")
            }:
                path.unlink()
    for relative in sorted(_allowed_overlay_files(overlay)):
        source, target = overlay / relative, repository_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    validate_state_ebuilds(repository_root)
    return allow


def verify_diff(artifact: Path, repository_root: Path) -> None:
    overlay, _ = validate(artifact)
    allowed = expected_diff(repository_root, overlay)
    import subprocess
    tracked = subprocess.run(["git", "diff", "--name-only"], cwd=repository_root,
                             check=True, capture_output=True, text=True).stdout.splitlines()
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"],
                               cwd=repository_root, check=True, capture_output=True, text=True).stdout.splitlines()
    actual = set(tracked) | set(untracked)
    unexpected = actual - allowed
    if unexpected:
        raise HandoffError("Diff содержит файлы вне allowlist: " + ", ".join(sorted(unexpected)))
    target_state = read_state(overlay)
    required = {"README.md", "automation/accepted-pairs.json"}
    if target_state.previous is not None:
        if target_state.current.umbriel.sha != target_state.previous.umbriel.sha:
            required.update((MANIFESTS[0], ebuild_path("umbriel", target_state.current.umbriel.version)))
        if target_state.current.portal.sha != target_state.previous.portal.sha:
            required.update((MANIFESTS[1], ebuild_path("portal", target_state.current.portal.version)))
    if not required.issubset(actual):
        raise HandoffError("В diff отсутствуют обязательные README, state или Manifest.")


def write_pr_request(artifact: Path, request_path: Path, branch: str) -> None:
    overlay, metadata = validate(artifact)
    state = read_state(overlay)
    current, previous = state.current, state.previous
    if previous is None:
        raise HandoffError("Draft PR требует предыдущую пару в состоянии ротации.")
    expected_branch = f"automation/umbriel-{current.umbriel.sha[:12]}-{current.portal.sha[:12]}"
    if branch != expected_branch:
        raise HandoffError("Branch PR не соответствует SHA подготовленного кандидата.")
    lines = [
        "## Обновление пары snapshot",
        "",
        "| Пакет | Прежняя принятая версия / SHA | Кандидат / SHA | Upstream compare |",
        "| --- | --- | --- | --- |",
        f"| Umbriel | `{previous.umbriel.version}` / `{previous.umbriel.sha}` | `{current.umbriel.version}` / `{current.umbriel.sha}` | [compare](https://github.com/noctalia-dev/umbriel/compare/{previous.umbriel.sha}...{current.umbriel.sha}) |",
        f"| Portal | `{previous.portal.version}` / `{previous.portal.sha}` | `{current.portal.version}` / `{current.portal.sha}` | [compare](https://github.com/noctalia-dev/xdg-desktop-portal-umbriel/compare/{previous.portal.sha}...{current.portal.sha}) |",
        "",
        "Открытый PR фиксирует кандидата. Автоматизация не меняет его при продвижении ветки `cachix`; принятой пара станет после merge.",
        "",
        "## Изменения packaging-файлов upstream",
        "",
        "SHA в колонках — blob SHA из старого и закреплённого нового commit; `absent` означает отсутствие файла.",
        "",
        "| Файл | Было | Стало |",
        "| --- | --- | --- |",
    ]
    changes = metadata["packaging_changes"]
    assert isinstance(changes, dict)
    for path, value in sorted(changes.items()):
        lines.append(f"| `{path}` | `{value['old']}` | `{value['new']}` |")
    removed = metadata["removed_pair"]
    if isinstance(removed, dict):
        lines.extend((
            "", "При ротации удаляется прежняя fallback-пара:", "",
            f"- Umbriel: `{removed['umbriel']['version']}` / `{removed['umbriel']['sha']}`",
            f"- Portal: `{removed['portal']['version']}` / `{removed['portal']['sha']}`",
        ))
    lines.extend((
        "", "## Автоматические проверки", "",
        "- Офлайн-тесты автоматизации прошли.",
        "- Portal SHA взят из Umbriel `flake.lock`; полные SHA проверены.",
        "- Portage подтвердил увеличение snapshot-версий.",
        "- Manifest сформирован по загруженным distfile архивам.",
        "- `pkgcheck scan --exit` прошёл для обоих пакетов.",
        "- `emerge -pv` разрешил точные версии кандидатов.",
        "- Artifact и allowlist diff проверены; base commit совпал.",
        "", "`pkgcheck` и `emerge -pv` не являются сборкой или проверкой работающей сессии.",
        "На целевой системе пакеты не устанавливались. Сборка Umbriel/portal и ручные функциональные проверки сессии не выполнялись.",
    ))
    payload = {"base": "main", "body": "\n".join(lines), "draft": True,
               "head": branch, "title": f"[snapshot-update] Umbriel {current.umbriel.version}"}
    request_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    create_parser = sub.add_parser("create")
    create_parser.add_argument("--repository-root", type=Path, required=True)
    create_parser.add_argument("--destination", type=Path, required=True)
    create_parser.add_argument("--base-commit", required=True)
    create_parser.add_argument("--prepare-result", type=Path, required=True)
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--artifact", type=Path, required=True)
    apply_parser.add_argument("--repository-root", type=Path, required=True)
    apply_parser.add_argument("--expected-base", required=True)
    apply_parser.add_argument("--actual-base", required=True)
    verify_parser = sub.add_parser("verify-diff")
    verify_parser.add_argument("--artifact", type=Path, required=True)
    verify_parser.add_argument("--repository-root", type=Path, required=True)
    pr_parser = sub.add_parser("write-pr")
    pr_parser.add_argument("--artifact", type=Path, required=True)
    pr_parser.add_argument("--request", type=Path, required=True)
    pr_parser.add_argument("--branch", required=True)
    args = parser.parse_args()
    try:
        if args.command == "create":
            result = json.loads(args.prepare_result.read_text(encoding="utf-8"))
            changes = result.get("packaging_changes") if isinstance(result, dict) else None
            if not isinstance(result, dict) or result.get("outcome") != "prepared" or not isinstance(changes, dict):
                raise HandoffError("Нет успешно подготовленного кандидата для artifact.")
            create(args.repository_root, args.destination, base_commit=args.base_commit,
                   packaging_changes=changes, removed_pair=result.get("removed"))
        elif args.command == "apply":
            allow = apply(args.artifact, args.repository_root, expected_base=args.expected_base, actual_base=args.actual_base)
            print("\n".join(sorted(allow)))
        elif args.command == "verify-diff":
            verify_diff(args.artifact, args.repository_root)
        else:
            write_pr_request(args.artifact, args.request, args.branch)
        return 0
    except (HandoffError, PolicyError, OSError, json.JSONDecodeError) as error:
        print(f"Umbriel handoff error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
