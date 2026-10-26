from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import umbriel_handoff as handoff
import watch_umbriel as watcher
from overlay_policy import Package, Pair, PolicyError, read_state, validate_state_ebuilds
from prepare_umbriel import PrepareError, rotate

OLD_UM = "366739955d3905d7600638eb637941b2782c0c68"
OLD_PORTAL = "e69d6f72122a99aa3668e182a4df8755ada81c17"
NEW_UM = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
NEW_PORTAL = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
BASE = "cccccccccccccccccccccccccccccccccccccccc"


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
        state = json.loads((ROOT / "automation/accepted-pairs.json").read_text())
        (self.root / "automation").mkdir()
        (self.root / "automation/accepted-pairs.json").write_text(json.dumps(state, indent=2) + "\n")
        dirs = ("gui-wm/umbriel", "gui-libs/xdg-desktop-portal-umbriel")
        for directory in dirs:
            (self.root / directory).mkdir(parents=True)
            (self.root / directory / "Manifest").write_text("DIST old.tar.gz 1 BLAKE2B a SHA512 b\n")
        for relative in (
            "gui-wm/umbriel/umbriel-0.1.0_pre20261026184522.ebuild",
            "gui-libs/xdg-desktop-portal-umbriel/xdg-desktop-portal-umbriel-0.1.0_p20261024195939.ebuild",
        ):
            shutil.copyfile(ROOT / relative, self.root / relative)
        (self.root / "gui-wm/umbriel/umbriel-0.0.0_pre20261008.ebuild").write_text(f'MY_COMMIT="{"1" * 40}"\n')
        (self.root / "gui-libs/xdg-desktop-portal-umbriel/xdg-desktop-portal-umbriel-0.1.0_p20260926.ebuild").write_text(f'MY_COMMIT="{"2" * 40}"\n')
        self._write_readme()

    def _write_readme(self) -> None:
        state = read_state(self.root)
        (self.root / "README.md").write_text("# Test\n\n" + watcher_readme_block(state) + "\n", encoding="utf-8")

    def _candidate(self, portal_sha: str = OLD_PORTAL) -> Pair:
        portal_version = "0.1.0_p20261024195939" if portal_sha == OLD_PORTAL else "0.1.0_p20261027110000"
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
            "README.md\nautomation/accepted-pairs.json\ngui-wm/umbriel/Manifest\n"
            "gui-wm/umbriel/umbriel-0.1.0_pre20261027120000.ebuild\n",
            "",
        ))
        with patch("subprocess.run", side_effect=lambda *args, **kwargs: SimpleNamespace(stdout=next(outputs))):
            handoff.verify_diff(artifact, self.root)
        outputs = iter(("README.md\nautomation/accepted-pairs.json\ngui-wm/umbriel/Manifest\n",
                        "unrelated.txt\n"))
        with patch("subprocess.run", side_effect=lambda *args, **kwargs: SimpleNamespace(stdout=next(outputs))):
            with self.assertRaises(handoff.HandoffError):
                handoff.verify_diff(artifact, self.root)


def watcher_readme_block(state) -> str:
    from overlay_policy import version_block
    return version_block(state)


def tree_snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


if __name__ == "__main__":
    unittest.main()
