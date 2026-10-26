#!/usr/bin/env python3
"""Найти snapshot cachix и подготовить проверяемое описание кандидата."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from overlay_policy import PolicyError, ROOT, read_state, validate_state_ebuilds  # noqa: E402

API = "https://api.github.com"
UPSTREAM = "noctalia-dev/umbriel"
OVERLAY = "vovanbl411/umbriel-overlay"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
PACKAGING_FILES = ("VERSION", "flake.lock", "PACKAGING.md", "meson.build", "meson_options.txt")


class DiscoveryError(RuntimeError):
    """Ошибка discovery или некорректные upstream данные."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DiscoveryError(f"flake.lock содержит повторяющееся поле {key!r}.")
        result[key] = value
    return result


class Client(Protocol):
    def open_automation_pr(self) -> dict[str, str] | None: ...
    def ref_sha(self, repository: str, branch: str) -> str: ...
    def content(self, repository: str, path: str, ref: str) -> str: ...
    def commit_date(self, repository: str, sha: str) -> str: ...
    def file_sha(self, repository: str, path: str, ref: str) -> str | None: ...


class GitHubClient:
    """Минимальный read-only клиент GitHub REST; токен нужен только для PR list."""

    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def _json(self, url: str) -> Any:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "umbriel-overlay-updater",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            with urlopen(Request(url, headers=headers), timeout=25) as response:  # noqa: S310
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            status = f"HTTP {error.code}" if isinstance(error, HTTPError) else str(error)
            raise DiscoveryError(f"GitHub API запрос не выполнен ({status}).") from error

    def open_automation_pr(self) -> dict[str, str] | None:
        for page in range(1, 11):
            pulls = self._json(f"{API}/repos/{OVERLAY}/pulls?state=open&per_page=100&page={page}")
            if not isinstance(pulls, list):
                raise DiscoveryError("GitHub API вернул некорректный список PR.")
            for pr in pulls:
                head = pr.get("head", {}) if isinstance(pr, dict) else {}
                ref = head.get("ref") if isinstance(head, dict) else None
                if isinstance(ref, str) and ref.startswith("automation/umbriel-"):
                    return {"number": str(pr.get("number", "")), "url": str(pr.get("html_url", "")), "branch": ref}
            if len(pulls) < 100:
                break
        else:
            raise DiscoveryError("Слишком много открытых PR; нельзя надёжно проверить единственный automation PR.")
        return None

    def ref_sha(self, repository: str, branch: str) -> str:
        data = self._json(f"{API}/repos/{repository}/commits/{quote(branch, safe='')}")
        sha = data.get("sha") if isinstance(data, dict) else None
        if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
            raise DiscoveryError(f"Ветка {repository}/{branch} не разрешилась в полный commit SHA.")
        return sha

    def content(self, repository: str, path: str, ref: str) -> str:
        data = self._json(f"{API}/repos/{repository}/contents/{quote(path, safe='/')}?ref={quote(ref)}")
        import base64
        import binascii
        if not isinstance(data, dict) or data.get("encoding") != "base64" or not isinstance(data.get("content"), str):
            raise DiscoveryError(f"Не удалось прочитать {repository}/{path} по закреплённому SHA.")
        try:
            encoded = re.sub(r"\s+", "", data["content"])
            return base64.b64decode(encoded, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as error:
            raise DiscoveryError(f"Некорректное содержимое {repository}/{path}.") from error

    def commit_date(self, repository: str, sha: str) -> str:
        data = self._json(f"{API}/repos/{repository}/commits/{sha}")
        try:
            date = data["commit"]["committer"]["date"]
            parsed = datetime.fromisoformat(date.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("commit date has no timezone")
            return parsed.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise DiscoveryError(f"GitHub API вернул некорректное время коммита {sha}.") from error

    def file_sha(self, repository: str, path: str, ref: str) -> str | None:
        try:
            data = self._json(f"{API}/repos/{repository}/contents/{quote(path, safe='/')}?ref={quote(ref)}")
        except DiscoveryError as error:
            if "HTTP 404" in str(error):
                return None
            raise
        value = data.get("sha") if isinstance(data, dict) else None
        if not isinstance(value, str) or not SHA_RE.fullmatch(value):
            raise DiscoveryError(f"GitHub API вернул некорректный blob SHA для {repository}/{path}.")
        return value


@dataclass(frozen=True)
class Candidate:
    outcome: str
    base_commit: str
    pair: dict[str, dict[str, str]] | None = None
    packaging_changes: dict[str, dict[str, str]] | None = None
    open_pr: dict[str, str] | None = None
    dry_run: bool = False


def _semver(value: str, source: str) -> str:
    value = value.strip().removeprefix("v")
    if not VERSION_RE.fullmatch(value):
        raise DiscoveryError(f"{source} должен содержать версию X.Y.Z, получено {value!r}.")
    return value


def discover(client: Client, *, base_commit: str, dry_run: bool = False,
             repository_root: Path = ROOT) -> Candidate:
    """Проверить PR до upstream и привязать lock только к commit cachix."""
    validate_state_ebuilds(repository_root)
    open_pr = client.open_automation_pr()
    if open_pr is not None:
        return Candidate("open-pr", base_commit, open_pr=open_pr, dry_run=dry_run)
    current = read_state(repository_root).current
    umbriel_sha = client.ref_sha(UPSTREAM, "cachix")
    umbriel_version = _semver(client.content(UPSTREAM, "VERSION", umbriel_sha), "Umbriel VERSION")
    lock_text = client.content(UPSTREAM, "flake.lock", umbriel_sha)
    try:
        lock = json.loads(lock_text, object_pairs_hook=_unique_object)
        portal_sha = lock["nodes"]["xdg-desktop-portal-umbriel"]["locked"]["rev"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise DiscoveryError("flake.lock не содержит nodes.xdg-desktop-portal-umbriel.locked.rev.") from error
    if not isinstance(portal_sha, str) or not SHA_RE.fullmatch(portal_sha):
        raise DiscoveryError("Portal SHA из flake.lock должен быть полным commit SHA.")
    portal_build = client.content("noctalia-dev/xdg-desktop-portal-umbriel", "meson.build", portal_sha)
    match = re.search(r"project\s*\((?:(?!\)).)*?version\s*:\s*['\"]([0-9]+\.[0-9]+\.[0-9]+)['\"]", portal_build, re.S)
    if not match:
        raise DiscoveryError("Не удалось определить версию portal из meson.build закреплённого SHA.")
    um_stamp = client.commit_date(UPSTREAM, umbriel_sha)
    portal_stamp = client.commit_date("noctalia-dev/xdg-desktop-portal-umbriel", portal_sha)
    pair = {"umbriel": {"version": f"{umbriel_version}_pre{um_stamp}", "sha": umbriel_sha},
            "portal": {"version": f"{match.group(1)}_p{portal_stamp}", "sha": portal_sha}}
    if umbriel_sha == current.umbriel.sha and portal_sha == current.portal.sha:
        return Candidate("up-to-date", base_commit)
    changes = {}
    for project, sha, old_sha in ((UPSTREAM, umbriel_sha, current.umbriel.sha),
                                  ("noctalia-dev/xdg-desktop-portal-umbriel", portal_sha, current.portal.sha)):
        for path in PACKAGING_FILES:
            changes[f"{project}/{path}"] = {"old": client.file_sha(project, path, old_sha) or "absent",
                                               "new": client.file_sha(project, path, sha) or "absent"}
    return Candidate("candidate", base_commit, pair, changes, dry_run=dry_run)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-commit")
    parser.add_argument("--result-json", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--assert-no-open-pr", action="store_true")
    args = parser.parse_args()
    try:
        client = GitHubClient(os.environ.get("GH_TOKEN"))
        if args.assert_no_open_pr:
            if client.open_automation_pr() is not None:
                raise DiscoveryError("Открыт automation PR; публикация отменена.")
            return 0
        if not args.base_commit or args.result_json is None:
            parser.error("--base-commit и --result-json необходимы для discovery.")
        result = discover(client, base_commit=args.base_commit, dry_run=args.dry_run)
        payload = asdict(result)
        args.result_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        if args.summary:
            args.summary.write_text(f"## Umbriel snapshot discovery\n\n- Результат: `{result.outcome}`\n" + ("- Режим: `dry_run`; внешние записи отключены.\n" if args.dry_run else ""), encoding="utf-8")
        if args.github_output:
            args.github_output.write_text(f"outcome={result.outcome}\nhas_candidate={'true' if result.pair else 'false'}\n", encoding="utf-8")
        return 0
    except (DiscoveryError, PolicyError) as error:
        print(f"Umbriel discovery error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
