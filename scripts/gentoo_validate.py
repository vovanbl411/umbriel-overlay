#!/usr/bin/env python3
"""Portage-only checks run inside the pinned Gentoo validation container."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path("/overlay")
PACKAGES = {
    "umbriel": ("gui-wm/umbriel", "umbriel"),
    "portal": ("gui-libs/xdg-desktop-portal-umbriel", "xdg-desktop-portal-umbriel"),
}
# Resolver закреплённого дерева показал эти четыре USE-флага как необходимые
# для точных кандидатов и sdbus-c++ 2.3.1 как единственную unstable-зависимость.
# Менять настройки можно только по новому выводу emerge -pv после смены image
# digest; затем повторить container prepare командами из README. Не запускать autounmask.
RESOLVER_KEYWORD_OVERRIDES = ("=dev-cpp/sdbus-c++-2.3.1 ~amd64",)
RESOLVER_USE_OVERRIDES = (
    ">=x11-libs/cairo-1.18.4-r1 X",
    ">=media-libs/libglvnd-1.7.0 X",
    ">=media-libs/freetype-2.14.3 harfbuzz",
    ">=gui-libs/wlroots-0.20.2 X",
)


def ebuild_distfiles(path: Path, pn: str, version: str) -> set[str]:
    """Expand the controlled SRC_URI aliases used by these two ebuild families."""
    text = path.read_text(encoding="utf-8")
    match = re.search(r'^SRC_URI="([^"\n]+)"$', text, re.MULTILINE)
    commit = re.search(r'^MY_COMMIT="([0-9a-f]{40})"$', text, re.MULTILINE)
    if match is None or commit is None:
        raise SystemExit(f"Cannot read SRC_URI or MY_COMMIT from {path.name}.")
    aliases = re.findall(r"->\s+([^\s]+)", match.group(1))
    if not aliases:
        raise SystemExit(f"SRC_URI in {path.name} has no explicit distfile alias to verify.")
    values = {"PN": pn, "P": f"{pn}-{version}", "MY_COMMIT": commit.group(1)}
    names = set()
    for alias in aliases:
        name = re.sub(r"\$\{(PN|P|MY_COMMIT)\}", lambda item: values[item.group(1)], alias)
        if "${" in name or "/" in name or name in {"", ".", ".."}:
            raise SystemExit(f"Unsupported distfile alias {alias!r} in {path.name}.")
        names.add(name)
    return names


def expected_distfiles(root: Path, state: dict[str, object], package: str) -> set[str]:
    directory, pn = PACKAGES[package]
    pairs = (state["current"], state["previous"])
    versions = {pair[package]["version"] for pair in pairs if pair is not None}
    expected: set[str] = set()
    for version in versions:
        path = root / directory / f"{pn}-{version}.ebuild"
        expected.update(ebuild_distfiles(path, pn, version))
    return expected


def verify_thin_manifests(root: Path, state: dict[str, object]) -> None:
    """Require only DIST records and exact agreement with visible SRC_URI aliases."""
    for package, (directory, _) in PACKAGES.items():
        path = root / directory / "Manifest"
        records = [line.split() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if any(not fields or fields[0] != "DIST" for fields in records):
            raise SystemExit(f"{path.relative_to(root)} contains non-DIST records despite thin-manifests=true.")
        actual = {fields[1] for fields in records if len(fields) >= 2}
        expected = expected_distfiles(root, state, package)
        if actual != expected:
            raise SystemExit(
                f"{path.relative_to(root)} distfiles differ from SRC_URI: "
                f"missing={sorted(expected - actual)}, unexpected={sorted(actual - expected)}."
            )


def candidate_keyword_overrides(state: dict[str, object], arch: str,
                                accepted_keywords: set[str]) -> str:
    """Return exact candidate-only keyword entries when stage3 accepts stable keywords only."""
    # Overlay ebuilds объявляют только ~amd64; другой stage3 не может корректно проверить эти атомы.
    if not arch or not re.fullmatch(r"[A-Za-z0-9_-]+", arch):
        raise SystemExit(f"Stage3 reported an invalid ARCH value: {arch!r}.")
    if arch != "amd64":
        raise SystemExit(f"Pinned stage3 ARCH={arch!r} does not match package KEYWORDS=~amd64.")
    unstable_keyword = f"~{arch}"
    if unstable_keyword in accepted_keywords or "**" in accepted_keywords:
        return ""
    current = state["current"]
    package_overrides = [
        f"={directory}-{current[package]['version']} {unstable_keyword}"
        for package, (directory, pn) in PACKAGES.items()
    ]
    return "\n".join((*package_overrides, *RESOLVER_KEYWORD_OVERRIDES)) + "\n"


def configure_candidate_keywords(state: dict[str, object]) -> None:
    """Inspect stage3 policy and add exact, temporary resolver overrides."""
    import portage

    settings = portage.settings
    arch = settings["ARCH"].strip()
    accepted = set(settings["ACCEPT_KEYWORDS"].split())
    print(f"Stage3 ARCH={arch}; ACCEPT_KEYWORDS={' '.join(sorted(accepted))}")
    overrides = candidate_keyword_overrides(state, arch, accepted)
    if overrides:
        path = Path("/etc/portage/package.accept_keywords/umbriel-candidates")
        if path.exists():
            raise SystemExit(f"Refusing to replace existing temporary keyword file: {path}.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(overrides, encoding="utf-8")
        print(f"Added candidate-only keyword acceptance in {path}:\n{overrides.rstrip()}")
    else:
        print("Stage3 already accepts the candidates' ~ARCH keywords; no keyword override added.")

    use_path = Path("/etc/portage/package.use/umbriel-candidates")
    if use_path.exists():
        raise SystemExit(f"Refusing to replace existing temporary USE file: {use_path}.")
    use_path.parent.mkdir(parents=True, exist_ok=True)
    use_lines = "\n".join(RESOLVER_USE_OVERRIDES) + "\n"
    use_path.write_text(use_lines, encoding="utf-8")
    print(f"Added resolver-reported USE settings in {use_path}:\n{use_lines.rstrip()}")


def main() -> int:
    try:
        from portage.versions import vercmp
    except ImportError as error:
        raise SystemExit("Portage Python module is required for version ordering.") from error
    state = json.loads((ROOT / "automation/accepted-pairs.json").read_text(encoding="utf-8"))
    current, previous = state["current"], state["previous"]
    if previous is None:
        raise SystemExit("Rotation state must include the current pair as fallback.")
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
    verify_thin_manifests(ROOT, state)
    subprocess.run(["pkgcheck", "scan", "gui-wm/umbriel",
                    "gui-libs/xdg-desktop-portal-umbriel", "--exit"], cwd=ROOT, check=True)
    configure_candidate_keywords(state)
    subprocess.run(["emerge", "-pv", f"=gui-wm/umbriel-{current['umbriel']['version']}",
                    f"=gui-libs/xdg-desktop-portal-umbriel-{current['portal']['version']}"], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
