#!/usr/bin/env python3
"""Portage-only checks run inside the pinned Gentoo validation container."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path("/overlay")


def main() -> int:
    try:
        from portage.versions import vercmp
    except ImportError as error:
        raise SystemExit("Portage Python module is required for version ordering.") from error
    state = json.loads((ROOT / "automation/accepted-pairs.json").read_text(encoding="utf-8"))
    current, previous = state["current"], state["previous"]
    for package in ("umbriel", "portal"):
        old, new = previous[package], current[package]
        if old["sha"] == new["sha"]:
            if old["version"] != new["version"]:
                raise SystemExit(f"Shared {package} SHA must reuse the same ebuild version.")
            continue
        if vercmp(new["version"], old["version"]) <= 0:
            raise SystemExit(f"Portage version ordering failed for {package}: {old['version']} -> {new['version']}.")
    paths = set()
    for pair in (current, previous):
        paths.add(ROOT / "gui-wm/umbriel" / f"umbriel-{pair['umbriel']['version']}.ebuild")
        paths.add(ROOT / "gui-libs/xdg-desktop-portal-umbriel" /
                  f"xdg-desktop-portal-umbriel-{pair['portal']['version']}.ebuild")
    for path in sorted(paths):
        subprocess.run(["ebuild", str(path), "manifest"], check=True)
    subprocess.run(["pkgcheck", "scan", "--exit", "gui-wm/umbriel",
                    "gui-libs/xdg-desktop-portal-umbriel"], cwd=ROOT, check=True)
    subprocess.run(["emerge", "-pv", f"=gui-wm/umbriel-{current['umbriel']['version']}",
                    f"=gui-libs/xdg-desktop-portal-umbriel-{current['portal']['version']}"], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
