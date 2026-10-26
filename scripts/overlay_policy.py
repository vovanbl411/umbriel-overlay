#!/usr/bin/env python3
"""Правила пар принятых snapshot-пакетов и безопасного обновления overlay."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = "automation/accepted-pairs.json"
SHA = re.compile(r"^[0-9a-f]{40}$")
UMBRIEL_VERSION = re.compile(r"^\d+\.\d+\.\d+_pre\d{14}$")
PORTAL_VERSION = re.compile(r"^\d+\.\d+\.\d+_p\d{14}$")


class PolicyError(RuntimeError):
    """Ошибка состояния или ограничений overlay."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PolicyError(f"Повторяющееся поле {key!r} в {STATE_PATH}.")
        result[key] = value
    return result


@dataclass(frozen=True)
class Package:
    version: str
    sha: str


@dataclass(frozen=True)
class Pair:
    umbriel: Package
    portal: Package


@dataclass(frozen=True)
class State:
    current: Pair
    previous: Pair | None


def _package(value: object, name: str) -> Package:
    if not isinstance(value, dict) or set(value) != {"version", "sha"}:
        raise PolicyError(f"Некорректная запись пакета {name} в {STATE_PATH}.")
    version, sha = value["version"], value["sha"]
    pattern = UMBRIEL_VERSION if name == "umbriel" else PORTAL_VERSION
    if not isinstance(version, str) or not pattern.fullmatch(version):
        raise PolicyError(f"Некорректная версия {name}: {version!r}.")
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise PolicyError(f"Некорректный полный SHA {name}: {sha!r}.")
    return Package(version, sha)


def _pair(value: object, field: str) -> Pair:
    if not isinstance(value, dict) or set(value) != {"umbriel", "portal"}:
        raise PolicyError(f"Некорректная пара {field} в {STATE_PATH}.")
    return Pair(_package(value["umbriel"], "umbriel"), _package(value["portal"], "portal"))


def read_state(root: Path = ROOT) -> State:
    """Прочитать единственный источник соответствия версий и SHA."""
    try:
        payload = json.loads((root / STATE_PATH).read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PolicyError(f"Не удалось прочитать {STATE_PATH}.") from error
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "current", "previous"}:
        raise PolicyError(f"Некорректная структура {STATE_PATH}.")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise PolicyError("Неподдерживаемая версия схемы accepted-pairs.json.")
    current = _pair(payload["current"], "current")
    previous = None if payload["previous"] is None else _pair(payload["previous"], "previous")
    if previous == current:
        raise PolicyError("Текущая и предыдущая принятые пары совпадают.")
    if previous is not None:
        for name in ("umbriel", "portal"):
            old, new = getattr(previous, name), getattr(current, name)
            if old.version == new.version and old.sha != new.sha:
                raise PolicyError(f"Одна версия {name} не может указывать на разные SHA.")
            if old.sha == new.sha and old.version != new.version:
                raise PolicyError(f"Один SHA {name} должен использовать одну версию ebuild в обеих парах.")
    return State(current, previous)


def pair_payload(pair: Pair) -> dict[str, dict[str, str]]:
    return {"umbriel": {"version": pair.umbriel.version, "sha": pair.umbriel.sha},
            "portal": {"version": pair.portal.version, "sha": pair.portal.sha}}


def state_payload(state: State) -> dict[str, object]:
    return {"schema_version": 1, "current": pair_payload(state.current),
            "previous": None if state.previous is None else pair_payload(state.previous)}


def ebuild_path(package: str, version: str) -> str:
    if package == "umbriel" and UMBRIEL_VERSION.fullmatch(version):
        return f"gui-wm/umbriel/umbriel-{version}.ebuild"
    if package == "portal" and PORTAL_VERSION.fullmatch(version):
        return f"gui-libs/xdg-desktop-portal-umbriel/xdg-desktop-portal-umbriel-{version}.ebuild"
    raise PolicyError(f"Недопустимое имя версии {package}: {version}.")


def validate_state_ebuilds(root: Path = ROOT) -> None:
    """Проверить соответствие всех учитываемых версий SHA в ebuild."""
    state = read_state(root)
    expected: dict[str, set[str]] = {"umbriel": set(), "portal": set()}
    for pair in (state.current, state.previous):
        if pair is not None:
            expected["umbriel"].add(pair.umbriel.version)
            expected["portal"].add(pair.portal.version)
    for package, versions in expected.items():
        directory = (root / ("gui-wm/umbriel" if package == "umbriel" else "gui-libs/xdg-desktop-portal-umbriel"))
        for version in versions:
            path = root / ebuild_path(package, version)
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as error:
                raise PolicyError(f"Нет ebuild для принятой версии {path.name}.") from error
            sha = state.current if version == getattr(state.current, package).version else state.previous
            assert sha is not None
            expected_sha = getattr(sha, package).sha
            if f'MY_COMMIT="{expected_sha}"' not in text:
                raise PolicyError(f"SHA в {path.name} не совпадает с {STATE_PATH}.")


# У каждого документа свой заголовок таблицы, но общие маркеры. Новый язык
# нужно добавить здесь и снабдить теми же маркерами в соответствующем README.
README_FILES = {"README.md": "ru", "README.en.md": "en"}


def version_block(state: State, language: str) -> str:
    """Сформировать таблицу пары для README на заданном языке."""
    labels = {
        "ru": (
            "Статус", "Версии Umbriel / portal", "SHA Umbriel / portal",
            "Принятая текущая пара", "Предыдущая принятая пара",
        ),
        "en": (
            "Status", "Umbriel / portal versions", "Umbriel / portal SHAs",
            "Current accepted pair", "Previous accepted pair",
        ),
    }
    try:
        status, versions, shas, current, previous = labels[language]
    except KeyError as error:
        raise PolicyError(f"Неподдерживаемый язык README: {language!r}.") from error
    rows = []
    for label, pair in ((current, state.current), (previous, state.previous)):
        if pair is None:
            continue
        rows.append(f"| {label} | `{pair.umbriel.version}` / `{pair.portal.version}` | `{pair.umbriel.sha}` / `{pair.portal.sha}` |")
    return "\n".join(("<!-- accepted-pairs:start -->", f"| {status} | {versions} | {shas} |", "| --- | --- | --- |", *rows, "<!-- accepted-pairs:end -->"))


def update_readme_text(text: str, state: State, language: str, filename: str) -> str:
    """Заменить только таблицу; остальной текст документа остаётся авторским."""
    block = re.compile(r"<!-- accepted-pairs:start -->.*?<!-- accepted-pairs:end -->", re.S)
    updated, count = block.subn(lambda _: version_block(state, language), text)
    if count != 1:
        raise PolicyError(f"{filename} должен содержать ровно один блок принятых пар.")
    return updated


def update_readmes(root: Path, state: State) -> None:
    for filename, language in README_FILES.items():
        path = root / filename
        text = path.read_text(encoding="utf-8")
        path.write_text(update_readme_text(text, state, language, filename), encoding="utf-8")
