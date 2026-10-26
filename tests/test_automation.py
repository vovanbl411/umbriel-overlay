from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import umbriel_handoff as handoff
import gentoo_validate as gentoo_validation
import watch_umbriel as watcher
from overlay_policy import (
    README_FILES, Package, Pair, PolicyError, read_state,
    update_readme_text, validate_state_ebuilds,
)
from prepare_umbriel import PrepareError, rotate

OLD_UM = "366739955d3905d7600638eb637941b2782c0c68"
OLD_PORTAL = "e69d6f72122a99aa3668e182a4df8755ada81c17"
FIXTURE_UM_VERSION = "0.1.0_pre20261026184522"
FIXTURE_PORTAL_VERSION = "0.1.0_p20261024195939"
NEW_UM = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
NEW_PORTAL = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
BASE = "cccccccccccccccccccccccccccccccccccccccc"

FIXTURE_STATE = {
    "schema_version": 1,
    "current": {
        "umbriel": {"version": FIXTURE_UM_VERSION, "sha": OLD_UM},
        "portal": {"version": FIXTURE_PORTAL_VERSION, "sha": OLD_PORTAL},
    },
    "previous": None,
}


class FakeClient:
    def __init__(self, *, portal_sha: str = OLD_PORTAL, open_pr: bool = False,
                 lock: str | None = None, umb_sha: str = NEW_UM) -> None:
        self.portal_sha = portal_sha
        self.open_pr = open_pr
        self.lock = lock or json.dumps({"nodes": {"xdg-desktop-portal-umbriel": {"locked": {"rev": portal_sha}}}})
        self.umb_sha = umb_sha

    def open_automation_pr(self):
        return {"number": "7", "url": "https://github.com/vovanbl411/umbriel-overlay/pull/7", "branch": "automation/umbriel-existing"} if self.open_pr else None

    def ref_sha(self, repository: str, branch: str) -> str:
        return self.umb_sha

    def content(self, repository: str, path: str, ref: str) -> str:
        if path == "VERSION":
            return "0.1.0\n"
        if path == "flake.lock":
            return self.lock
        if path == "meson.build":
            return "project('xdg-desktop-portal-umbriel', version: '0.1.0')\n"
        raise AssertionError((repository, path))

    def commit_date(self, repository: str, sha: str) -> str:
        return "20261027120000" if repository == watcher.UPSTREAM else "20261027110000"

    def file_sha(self, repository: str, path: str, ref: str) -> str | None:
        return "d" * 40 if path != "PACKAGING.md" else None


class AutomationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._fixture()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _fixture(self) -> None:
        (self.root / "automation").mkdir()
        (self.root / "automation/accepted-pairs.json").write_text(json.dumps(FIXTURE_STATE, indent=2) + "\n")
        dirs = ("gui-wm/umbriel", "gui-libs/xdg-desktop-portal-umbriel")
        for directory in dirs:
            (self.root / directory).mkdir(parents=True)
        (self.root / "gui-wm/umbriel/Manifest").write_text(
            f"DIST umbriel-{OLD_UM}.tar.gz 1 BLAKE2B a SHA512 b\n"
        )
        (self.root / "gui-libs/xdg-desktop-portal-umbriel/Manifest").write_text(
            f"DIST xdg-desktop-portal-umbriel-{FIXTURE_PORTAL_VERSION}.tar.gz 1 BLAKE2B a SHA512 b\n"
        )
        (self.root / f"gui-wm/umbriel/umbriel-{FIXTURE_UM_VERSION}.ebuild").write_text(
            f'EAPI=8\nMY_COMMIT="{OLD_UM}"\n'
            'SRC_URI="https://example.invalid/umbriel/archive/${MY_COMMIT}.tar.gz -> ${PN}-${MY_COMMIT}.tar.gz"\n',
            encoding="utf-8",
        )
        (self.root / f"gui-libs/xdg-desktop-portal-umbriel/xdg-desktop-portal-umbriel-{FIXTURE_PORTAL_VERSION}.ebuild").write_text(
            f'EAPI=8\nMY_COMMIT="{OLD_PORTAL}"\n'
            'SRC_URI="https://example.invalid/portal/archive/${MY_COMMIT}.tar.gz -> ${P}.tar.gz"\n',
            encoding="utf-8",
        )
        (self.root / "gui-wm/umbriel/umbriel-0.0.0_pre20261008.ebuild").write_text(f'MY_COMMIT="{"1" * 40}"\n')
        (self.root / "gui-libs/xdg-desktop-portal-umbriel/xdg-desktop-portal-umbriel-0.1.0_p20260926.ebuild").write_text(f'MY_COMMIT="{"2" * 40}"\n')
        self._write_readme()

    def _write_readme(self) -> None:
        state = read_state(self.root)
        (self.root / "README.md").write_text("# Test\n\n" + watcher_readme_block(state, "ru") + "\n", encoding="utf-8")
        (self.root / "README.en.md").write_text("# Test\n\n" + watcher_readme_block(state, "en") + "\n", encoding="utf-8")

    def _candidate(self, portal_sha: str = OLD_PORTAL) -> Pair:
        portal_version = FIXTURE_PORTAL_VERSION if portal_sha == OLD_PORTAL else "0.1.0_p20261027110000"
        return Pair(Package("0.1.0_pre20261027120000", NEW_UM), Package(portal_version, portal_sha))

    @staticmethod
    def _packaging_changes() -> dict[str, dict[str, str]]:
        return {f"{repository}/{path}": {"old": "a"*40, "new": "b"*40}
                for repository in ("noctalia-dev/umbriel", "noctalia-dev/xdg-desktop-portal-umbriel")
                for path in watcher.PACKAGING_FILES}

    def test_reads_explicit_accepted_pair(self) -> None:
        state = read_state(self.root)
        self.assertEqual(state.current.umbriel.sha, OLD_UM)
        self.assertEqual(state.current.portal.sha, OLD_PORTAL)
        self.assertIsNone(state.previous)

    def test_checked_in_accepted_state_matches_ebuilds(self) -> None:
        validate_state_ebuilds(ROOT)

    def test_checked_in_readme_tables_and_language_links_match_state(self) -> None:
        state = read_state(ROOT)
        for filename, language in README_FILES.items():
            text = (ROOT / filename).read_text(encoding="utf-8")
            self.assertEqual(update_readme_text(text, state, language, filename), text)
        self.assertIn("[English](README.en.md)", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("[Русский](README.md)", (ROOT / "README.en.md").read_text(encoding="utf-8"))

    def test_thin_manifest_contains_only_src_uri_distfiles(self) -> None:
        state = json.loads((self.root / "automation/accepted-pairs.json").read_text())
        gentoo_validation.verify_thin_manifests(self.root, state)
        manifest = self.root / "gui-wm/umbriel/Manifest"
        manifest.write_text("AUX unrelated.patch 1 BLAKE2B a SHA512 b\n")
        with self.assertRaisesRegex(SystemExit, "non-DIST"):
            gentoo_validation.verify_thin_manifests(self.root, state)

    def test_keyword_override_is_exact_and_only_when_stage3_needs_it(self) -> None:
        state = json.loads((self.root / "automation/accepted-pairs.json").read_text())
        override = gentoo_validation.candidate_keyword_overrides(state, "amd64", {"amd64"})
        self.assertEqual(
            override.splitlines(),
            [
                f"=gui-wm/umbriel-{FIXTURE_UM_VERSION} ~amd64",
                f"=gui-libs/xdg-desktop-portal-umbriel-{FIXTURE_PORTAL_VERSION} ~amd64",
                "=dev-cpp/sdbus-c++-2.3.1 ~amd64",
            ],
        )
        self.assertEqual(gentoo_validation.candidate_keyword_overrides(state, "amd64", {"amd64", "~amd64"}), "")
        with self.assertRaisesRegex(SystemExit, "invalid ARCH"):
            gentoo_validation.candidate_keyword_overrides(state, "amd64!", {"amd64"})
        self.assertEqual(
            gentoo_validation.RESOLVER_USE_OVERRIDES,
            (
                ">=x11-libs/cairo-1.18.4-r1 X",
                ">=media-libs/libglvnd-1.7.0 X",
                ">=media-libs/freetype-2.14.3 harfbuzz",
                ">=gui-libs/wlroots-0.20.2 X",
            ),
        )

    def test_rotation_does_not_break_suite_after_two_rotations(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            rotated_root = Path(temp) / "overlay"
            rotated_root.mkdir()
            # Копируем только исходники пакетов и автоматизации, не .git или скрытые конфиги.
            for name in ("README.md", "README.en.md", "automation", "scripts", "tests", "gui-wm", "gui-libs", "metadata", "profiles"):
                source = ROOT / name
                target = rotated_root / name
                if source.is_dir():
                    shutil.copytree(source, target)
                else:
                    shutil.copyfile(source, target)
            initial = read_state(rotated_root).current
            base = initial.umbriel.version.split("_pre", maxsplit=1)[0]
            first = Pair(Package(f"{base}_pre99991231235958", "1" * 40), initial.portal)
            second = Pair(Package(f"{base}_pre99991231235959", "2" * 40), initial.portal)
            rotate(rotated_root, first)
            self._run_offline_suite(rotated_root)
            rotate(rotated_root, second)
            self._run_offline_suite(rotated_root)

    def _run_offline_suite(self, root: Path) -> None:
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, str(root / "tests/run_after_rotation.py")],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_no_update_does_not_prepare(self) -> None:
        result = watcher.discover(FakeClient(umb_sha=OLD_UM), base_commit=BASE, repository_root=self.root)
        self.assertEqual(result.outcome, "up-to-date")

    def test_open_pr_stops_before_upstream_discovery(self) -> None:
        result = watcher.discover(FakeClient(open_pr=True), base_commit=BASE, repository_root=self.root)
        self.assertEqual(result.outcome, "open-pr")
        self.assertIsNotNone(result.open_pr)

    def test_discovery_uses_only_locked_portal_sha(self) -> None:
        result = watcher.discover(FakeClient(), base_commit=BASE, repository_root=self.root)
        self.assertEqual(result.outcome, "candidate")
        self.assertEqual(result.pair["portal"]["sha"], OLD_PORTAL)

    def test_invalid_lock_and_portal_sha_fail_closed(self) -> None:
        for lock in ("{bad", json.dumps({"nodes": {"xdg-desktop-portal-umbriel": {"locked": {"rev": "bad"}}}})):
            with self.assertRaises(watcher.DiscoveryError):
                watcher.discover(FakeClient(lock=lock), base_commit=BASE, repository_root=self.root)

    def test_umbriel_only_rotation_reuses_single_portal_ebuild(self) -> None:
        result = rotate(self.root, self._candidate())
        self.assertTrue(result["portal_reused"])
        self.assertEqual(len(list((self.root / "gui-libs/xdg-desktop-portal-umbriel").glob("*.ebuild"))), 1)
        self.assertTrue((self.root / "gui-wm/umbriel/umbriel-0.1.0_pre20261026184522.ebuild").exists())
        self.assertEqual(read_state(self.root).previous.umbriel.sha, OLD_UM)

    def test_rotation_updates_localized_tables_from_the_same_state(self) -> None:
        rotate(self.root, self._candidate())
        russian = (self.root / "README.md").read_text(encoding="utf-8")
        english = (self.root / "README.en.md").read_text(encoding="utf-8")
        for sha in (NEW_UM, OLD_PORTAL):
            self.assertIn(sha, russian)
            self.assertIn(sha, english)
        self.assertIn("| Статус | Версии Umbriel / portal | SHA Umbriel / portal |", russian)
        self.assertIn("| Status | Umbriel / portal versions | Umbriel / portal SHAs |", english)
        self.assertIn("| Принятая текущая пара |", russian)
        self.assertIn("| Current accepted pair |", english)

    def test_both_projects_rotate_together(self) -> None:
        result = rotate(self.root, self._candidate(NEW_PORTAL))
        self.assertFalse(result["portal_reused"])
        self.assertTrue((self.root / "gui-libs/xdg-desktop-portal-umbriel/xdg-desktop-portal-umbriel-0.1.0_p20261027110000.ebuild").exists())
        self.assertEqual(read_state(self.root).current.portal.sha, NEW_PORTAL)

    def test_second_rotation_keeps_two_pairs_and_removes_older_fallback(self) -> None:
        first = self._candidate()
        rotate(self.root, first)
        second = Pair(Package("0.1.0_pre20261028120000", "c"*40), first.portal)
        result = rotate(self.root, second)
        state = read_state(self.root)
        self.assertEqual(state.current.umbriel.sha, second.umbriel.sha)
        self.assertEqual(state.previous.umbriel.sha, first.umbriel.sha)
        self.assertEqual(result["removed"]["umbriel"]["sha"], OLD_UM)
        self.assertFalse((self.root / "gui-wm/umbriel/umbriel-0.1.0_pre20261026184522.ebuild").exists())
        self.assertEqual(len(list((self.root / "gui-libs/xdg-desktop-portal-umbriel").glob("*.ebuild"))), 1)

    def test_pr_request_reports_pair_shas_upstream_changes_and_removed_fallback(self) -> None:
        first = self._candidate()
        rotate(self.root, first)
        second = Pair(Package("0.1.0_pre20261028120000", "c"*40), first.portal)
        result = rotate(self.root, second)
        artifact = self.root.parent / (self.root.name + "-pr-artifact")
        handoff.create(self.root, artifact, base_commit=BASE,
                       packaging_changes=self._packaging_changes(), removed_pair=result["removed"])
        request = self.root.parent / (self.root.name + "-request.json")
        branch = f"automation/umbriel-{second.umbriel.sha[:12]}-{second.portal.sha[:12]}"
        handoff.write_pr_request(artifact, request, branch)
        body = json.loads(request.read_text())["body"]
        self.assertIn(second.umbriel.sha, body)
        self.assertIn(OLD_UM, body)
        self.assertIn("удаляется прежняя fallback-пара", body)
        self.assertIn("noctalia-dev/xdg-desktop-portal-umbriel/meson.build", body)

    def test_dry_run_has_no_repository_or_artifact_writes(self) -> None:
        before = tree_snapshot(self.root)
        result = rotate(self.root, self._candidate(), dry_run=True)
        self.assertEqual(result["outcome"], "dry-run")
        self.assertEqual(tree_snapshot(self.root), before)

    def test_invalid_state_pair_is_rejected(self) -> None:
        path = self.root / "automation/accepted-pairs.json"
        payload = json.loads(path.read_text())
        payload["current"]["portal"]["sha"] = "short"
        path.write_text(json.dumps(payload))
        with self.assertRaises(PolicyError):
            read_state(self.root)

    def test_handoff_rejects_extra_file_and_conflicting_base(self) -> None:
        rotate(self.root, self._candidate())
        for directory in ("gui-wm/umbriel", "gui-libs/xdg-desktop-portal-umbriel"):
            (self.root / directory / "Manifest").write_text("DIST generated.tar.gz 4 BLAKE2B c SHA512 d\n")
        prep_result = self.root / "preparation.json"
        prep_result.write_text(json.dumps({"outcome": "prepared", "packaging_changes": self._packaging_changes()}))
        artifact = self.root / "artifact"
        handoff.create(self.root, artifact, base_commit=BASE, packaging_changes=json.loads(prep_result.read_text())["packaging_changes"])
        extra = artifact / "overlay/README.extra"
        extra.write_text("unexpected")
        with self.assertRaises(handoff.HandoffError):
            handoff.validate(artifact)
        extra.unlink()
        with self.assertRaises(handoff.HandoffError):
            handoff.apply(artifact, self.root, expected_base=BASE, actual_base="e"*40)

    def test_allowlisted_diff_passes_and_unrelated_change_fails(self) -> None:
        base = BASE
        base_readmes = {
            filename: (self.root / filename).read_text(encoding="utf-8")
            for filename in ("README.md", "README.en.md")
        }
        prepared = self.root.parent / (self.root.name + "-prepared")
        shutil.copytree(self.root, prepared)
        rotate(prepared, self._candidate())
        for directory in ("gui-wm/umbriel", "gui-libs/xdg-desktop-portal-umbriel"):
            (prepared / directory / "Manifest").write_text("DIST generated.tar.gz 4 BLAKE2B c SHA512 d\n")
        packaging = self._packaging_changes()
        artifact = self.root.parent / (self.root.name + "-handoff")
        handoff.create(prepared, artifact, base_commit=base, packaging_changes=packaging)
        handoff.apply(artifact, self.root, expected_base=base, actual_base=base)
        outputs = iter((
            "README.md\nREADME.en.md\nautomation/accepted-pairs.json\ngui-wm/umbriel/Manifest\n"
            "gui-wm/umbriel/umbriel-0.1.0_pre20261027120000.ebuild\n",
            "",
            base_readmes["README.md"],
            base_readmes["README.en.md"],
        ))
        with patch("subprocess.run", side_effect=lambda *args, **kwargs: SimpleNamespace(stdout=next(outputs))):
            handoff.verify_diff(artifact, self.root)
        outputs = iter(("README.md\nREADME.en.md\nautomation/accepted-pairs.json\ngui-wm/umbriel/Manifest\n",
                        "unrelated.txt\n"))
        with patch("subprocess.run", side_effect=lambda *args, **kwargs: SimpleNamespace(stdout=next(outputs))):
            with self.assertRaises(handoff.HandoffError):
                handoff.verify_diff(artifact, self.root)

    def test_handoff_applies_and_verifies_on_separate_base_copy(self) -> None:
        base_copy = self.root.parent / (self.root.name + "-base-copy")
        shutil.copytree(self.root, base_copy)
        subprocess.run(["git", "init", "-q"], cwd=base_copy, check=True)
        subprocess.run(["git", "add", "."], cwd=base_copy, check=True)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "-c", "commit.gpgsign=false",
                        "commit", "-qm", "fixture base"], cwd=base_copy, check=True)
        base_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=base_copy,
                                     check=True, capture_output=True, text=True).stdout.strip()

        prepared = self.root.parent / (self.root.name + "-prepared-copy")
        shutil.copytree(base_copy, prepared)
        result = rotate(prepared, self._candidate())
        for directory in ("gui-wm/umbriel", "gui-libs/xdg-desktop-portal-umbriel"):
            (prepared / directory / "Manifest").write_text("DIST generated.tar.gz 4 BLAKE2B c SHA512 d\n")
        artifact = self.root.parent / (self.root.name + "-separate-base-artifact")
        handoff.create(prepared, artifact, base_commit=base_commit,
                       packaging_changes=self._packaging_changes(), removed_pair=result["removed"])
        artifact_readme = artifact / "overlay/README.en.md"
        original_artifact_readme = artifact_readme.read_text(encoding="utf-8")
        artifact_readme.write_text("Extra prose\n" + original_artifact_readme, encoding="utf-8")

        applied_copy = self.root.parent / (self.root.name + "-applied-copy")
        shutil.copytree(base_copy, applied_copy)
        self.assertTrue((artifact / "overlay/README.md").is_file())
        self.assertTrue(artifact_readme.is_file())
        with self.assertRaisesRegex(handoff.HandoffError, "README.en.md.*вне выделенного блока"):
            handoff.apply(artifact, applied_copy, expected_base=base_commit, actual_base=base_commit)
        artifact_readme.write_text(original_artifact_readme, encoding="utf-8")
        handoff.apply(artifact, applied_copy, expected_base=base_commit, actual_base=base_commit)
        handoff.verify_diff(artifact, applied_copy)
        applied_readme = applied_copy / "README.en.md"
        original_applied_readme = applied_readme.read_text(encoding="utf-8")
        applied_readme.write_text("Extra prose\n" + original_applied_readme, encoding="utf-8")
        with self.assertRaisesRegex(handoff.HandoffError, "README.en.md.*вне выделенного блока"):
            handoff.verify_diff(artifact, applied_copy)
        applied_readme.write_text(original_applied_readme, encoding="utf-8")
        unexpected = applied_copy / "gui-wm/umbriel/umbriel-9.9.9_pre99991231235959.ebuild"
        unexpected.write_text('EAPI=8\n', encoding="utf-8")
        with self.assertRaisesRegex(handoff.HandoffError, "вне allowlist"):
            handoff.verify_diff(artifact, applied_copy)


def watcher_readme_block(state, language: str) -> str:
    from overlay_policy import version_block
    return version_block(state, language)


def tree_snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


if __name__ == "__main__":
    unittest.main()
