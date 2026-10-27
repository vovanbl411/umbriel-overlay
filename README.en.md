# Umbriel overlay

[Русский](README.md)

This Gentoo overlay provides two packages from [Umbriel](https://github.com/noctalia-dev/umbriel): the Wayland compositor and its [XDG Desktop Portal backend](https://github.com/noctalia-dev/xdg-desktop-portal-umbriel). Syncing the overlay fetches ebuilds and Manifests.

## For users

### Connect and install

1. Create `/etc/portage/repos.conf/umbriel-overlay.conf`:

   ```ini
   [umbriel-overlay]
   location = /var/db/repos/umbriel-overlay
   sync-type = git
   sync-uri = https://github.com/vovanbl411/umbriel-overlay.git
   auto-sync = yes
   ```

2. Sync the overlay:

   ```sh
   emerge --sync umbriel-overlay
   ```

   This command fetches overlay files.

3. Both packages have `KEYWORDS="~amd64"`. Add the exact atoms from the accepted pair table to `/etc/portage/package.accept_keywords/umbriel-overlay`, replacing the version placeholders with the values from `current`:

   ```text
   =gui-wm/umbriel-<Umbriel-version> ~amd64
   =gui-libs/xdg-desktop-portal-umbriel-<portal-version> ~amd64
   ```

4. Preview dependency resolution, then install the pair as a separate command:

   ```sh
   emerge -pv '=gui-wm/umbriel-<Umbriel-version>' '=gui-libs/xdg-desktop-portal-umbriel-<portal-version>'
   emerge '=gui-wm/umbriel-<Umbriel-version>' '=gui-libs/xdg-desktop-portal-umbriel-<portal-version>'
   ```

   Use versions from the same table row. Do not mix versions from different pairs. Umbriel provides the `jemalloc` and `screencast` USE flags; the portal provides `picker` (enabled by default). Configure them separately in `/etc/portage/package.use/`.

### Accepted pair and rollback

[`automation/accepted-pairs.json`](automation/accepted-pairs.json) is the source of truth for the version-to-full-upstream-SHA mapping. `current` identifies the pair accepted on the default branch. In a Draft PR, the table shows a candidate; it becomes accepted only after the PR is merged.

Each version includes the upstream base version and the commit's UTC timestamp: Umbriel uses the `_pre` suffix and the portal uses `_p`. Each ebuild pins a full commit SHA, so its source does not change when an upstream branch advances.

<!-- accepted-pairs:start -->
| Status | Umbriel / portal versions | Umbriel / portal SHAs |
| --- | --- | --- |
| Current accepted pair | `0.1.0_pre20261026184522` / `0.1.0_p20261024195939` | `366739955d3905d7600638eb637941b2782c0c68` / `e69d6f72122a99aa3668e182a4df8755ada81c17` |
<!-- accepted-pairs:end -->

After a rotation, `previous` holds the previously accepted pair and can be used for rollback. `previous` is currently `null`; the first rotation will move the current pair into `previous`. Historical ebuilds on the default branch before that rotation do not define an accepted pair. If both pairs use the same portal SHA, they share one ebuild.

To roll back, sync the overlay, select both versions from the `previous` row, allow the corresponding `~amd64` atoms, and install the pair using those exact Portage atoms.

## Maintaining the overlay

### How updates are prepared

The [Prepare Umbriel snapshot pair](.github/workflows/prepare-umbriel-snapshot.yml) workflow checks the upstream `cachix` branch daily at `06:23 UTC` and can also be started manually. It follows this sequence:

1. Check for an open automation PR. If one exists, stop before contacting upstream.
2. Resolve `cachix` to one full Umbriel SHA and read `VERSION`, `flake.lock`, and packaging files only at that SHA.
3. Read the portal SHA only from `nodes.xdg-desktop-portal-umbriel.locked.rev` in that `flake.lock`, then read portal files at the pinned SHA.
4. Compare both SHAs with `current`. If the pair has not changed, stop without preparing an update.
5. Prepare ebuilds and archives for changed projects. Move the previous `current` into `previous` and keep only the ebuilds for those two pairs. If the portal SHA is unchanged, reuse its ebuild.
6. In the pinned Gentoo images, generate Manifests from downloaded archives, check version ordering with Portage, run `pkgcheck scan --exit`, and run `emerge -pv` for the exact versions.
7. Pass a restricted artifact to a separate publish job. That job checks its contents, the allowed diff, and the base commit, then opens a Draft PR using `GITHUB_TOKEN`.

The PR lists the old and new versions and SHAs for both projects, upstream compare links, packaging-file changes, and the results of the container checks, artifact checks, and base-commit check.

The prepare job has no repository write permission, and the Gentoo container receives no GitHub credentials. The automation does not install Umbriel, build the packages, test a session, merge a PR, or enable auto-merge. `pkgcheck` checks ebuild metadata, and `emerge -pv` checks dependency resolution.

A manual run accepts the `dry_run` input. In this mode, the workflow runs discovery and shows the plan, but skips container validation and creates no artifact, branch, or PR. A successful `dry_run` does not confirm a local container prepare.

### GitHub settings

These are repository setup instructions.

- Enable GitHub Actions. If the repository allows only selected Actions, allow `actions/checkout`, `actions/upload-artifact`, and `actions/download-artifact` at the SHAs used in the workflow's `uses:` entries. GitHub matches pinned SHAs against the allowlist; see [GitHub's allowed-actions settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository).
- Under **Settings → Actions → General → Workflow permissions**, keep the minimum default `GITHUB_TOKEN` permissions and enable **Allow GitHub Actions to create and approve pull requests**; otherwise, the publish job cannot create a Draft PR. The workflow gives prepare `contents: read` and `pull-requests: read`, and publish `contents: write` and `pull-requests: write`.
- For the default branch, require the **Python unit tests** check from the [Python unit tests](.github/workflows/ci.yml) workflow, with GitHub Actions as its source. Require the PR branch to be up to date before merging.
- Before merging, install the pair and check it in an Umbriel session: startup, input, display output, Noctalia if used, screen sharing, and the portal picker.

A PR created with `GITHUB_TOKEN` may leave its `pull_request` workflow run awaiting approval. After reviewing the changes, a user with write access must select **Approve workflows to run**. See [GitHub's documentation on triggering workflows from workflows](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow). PATs, GitHub Apps, and `pull_request_target` are not used to bypass this approval.

### Repeat the container checks

Prepare a separate clean overlay copy whose `accepted-pairs.json`, ebuilds, and Manifests already contain the candidate and fallback pairs. From the repository root, run:

```sh
set -eu
GENTOO_PORTAGE_IMAGE='gentoo/portage@sha256:ce69e5b771bfe9404731e846b835346c34f2c82817ac3626f13af198689a1961'
GENTOO_STAGE3_IMAGE='gentoo/stage3@sha256:d8536e52677e3efe4caf048ca588bc685bc2d24d7fdfc882de1cdc6d38c81d96'
OVERLAY_DIR="$(mktemp -d)"
CONTAINER_NAME='umbriel-portage-check'
trap 'docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true; rm -rf "$OVERLAY_DIR"' EXIT

tar --exclude=.git -C "$(git rev-parse --show-toplevel)" -cf - . | tar -C "$OVERLAY_DIR" -xf -
docker create --name "$CONTAINER_NAME" "$GENTOO_PORTAGE_IMAGE" /bin/true
docker run --rm --volumes-from "$CONTAINER_NAME" \
  --mount "type=bind,src=$OVERLAY_DIR,dst=/overlay" \
  --env OVERLAY_UID="$(id -u)" --env OVERLAY_GID="$(id -g)" \
  "$GENTOO_STAGE3_IMAGE" /bin/bash -e -c '
    mkdir -p /etc/portage/repos.conf
    printf "[umbriel-overlay]\nlocation = /overlay\nmasters = gentoo\nauto-sync = no\n" > /etc/portage/repos.conf/umbriel-overlay.conf
    printf "[gentoo]\nlocation = /var/db/repos/gentoo\nauto-sync = no\n" > /etc/portage/repos.conf/gentoo.conf
    emerge --oneshot dev-util/pkgcheck
    PYTHONPATH=/overlay/scripts python3 /overlay/scripts/gentoo_validate.py
    chown -R "$OVERLAY_UID:$OVERLAY_GID" /overlay
  '
```

The image digests are set in `.github/workflows/prepare-umbriel-snapshot.yml`. Change them only as a compatible pair, then repeat the full check. Temporary resolver keyword and USE overrides are in `scripts/gentoo_validate.py`; change them only in response to new `emerge -pv` output, then repeat container validation. Do not run `--autounmask`.

### Manual checks and limits

Before merging, install and check the pair in an Umbriel session. CI checks the Python update logic; the container checks ebuild metadata and dependencies. Neither builds Umbriel or the portal.

Track these outcomes separately: a local prepare with container and artifact verification; and a successful GitHub `dry_run`, which checks discovery and shows the plan. Noctalia updates are handled separately and are not part of Umbriel automation.
