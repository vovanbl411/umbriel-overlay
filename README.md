# Umbriel overlay

[English](README.en.md)

Gentoo overlay с двумя пакетами [Umbriel](https://github.com/noctalia-dev/umbriel): Wayland-композитором и его [backend для XDG Desktop Portal](https://github.com/noctalia-dev/xdg-desktop-portal-umbriel). Синхронизация оверлея получает ebuild и Manifest.

## Для пользователя

### Подключение и установка

1. Создайте `/etc/portage/repos.conf/umbriel-overlay.conf`:

   ```ini
   [umbriel-overlay]
   location = /var/db/repos/umbriel-overlay
   sync-type = git
   sync-uri = https://github.com/vovanbl411/umbriel-overlay.git
   auto-sync = yes
   ```

2. Синхронизируйте оверлей:

   ```sh
   emerge --sync umbriel-overlay
   ```

   Эта команда получает файлы оверлея.

3. Обе версии имеют `KEYWORDS="~amd64"`. Добавьте точные атомы из таблицы принятой пары в `/etc/portage/package.accept_keywords/umbriel-overlay`, заменив обозначения версий значениями из `current`:

   ```text
   =gui-wm/umbriel-<Umbriel-version> ~amd64
   =gui-libs/xdg-desktop-portal-umbriel-<portal-version> ~amd64
   ```

4. Проверьте разрешение выбранной пары, затем установите её отдельной командой:

   ```sh
   emerge -pv '=gui-wm/umbriel-<Umbriel-version>' '=gui-libs/xdg-desktop-portal-umbriel-<portal-version>'
   emerge '=gui-wm/umbriel-<Umbriel-version>' '=gui-libs/xdg-desktop-portal-umbriel-<portal-version>'
   ```

   Подставляйте версии из одной строки таблицы. Не смешивайте версии из разных пар. У Umbriel доступны USE-флаги `jemalloc` и `screencast`; у portal — `picker` (включён по умолчанию). Их настраивают отдельно в `/etc/portage/package.use/`.

### Принятая пара и откат

[Файл `automation/accepted-pairs.json`](automation/accepted-pairs.json) — источник соответствия версий и полных upstream SHA. `current` задаёт пару, принятую в основной ветке. В Draft PR таблица показывает кандидата; он станет принятой парой только после merge.

Версия включает upstream base version и UTC-время соответствующего commit: Umbriel использует суффикс `_pre`, portal — `_p`. Ebuild закрепляет полный commit SHA, поэтому его исходник не меняется при продвижении upstream-ветки.

<!-- accepted-pairs:start -->
| Статус | Версии Umbriel / portal | SHA Umbriel / portal |
| --- | --- | --- |
| Принятая текущая пара | `0.1.0_pre20261026184522` / `0.1.0_p20261024195939` | `366739955d3905d7600638eb637941b2782c0c68` / `e69d6f72122a99aa3668e182a4df8755ada81c17` |
<!-- accepted-pairs:end -->

`previous` хранит предыдущую принятую пару после ротации и позволяет выбрать её для отката. Сейчас `previous` равен `null`: первая ротация перенесёт текущую пару в `previous`. Исторические ebuild в основной ветке до этой ротации не задают принятую пару. Если SHA portal в двух парах совпадает, для него используется один ebuild.

Для отката синхронизируйте оверлей, выберите обе версии из строки `previous`, разрешите соответствующие `~amd64` атомы и установите пару теми же точными атомами Portage.

## Сопровождение оверлея

### Как готовится обновление

Workflow [Prepare Umbriel snapshot pair](.github/workflows/prepare-umbriel-snapshot.yml) ежедневно проверяет upstream-ветку `cachix` в `06:23 UTC`; его также можно запустить вручную. Он действует в таком порядке:

1. Проверяет, нет ли открытого автоматического PR. Если PR открыт, завершает запуск до обращения к upstream.
2. Разрешает `cachix` в один полный Umbriel SHA и читает `VERSION`, `flake.lock` и packaging-файлы только по этому SHA.
3. Берёт portal SHA только из `nodes.xdg-desktop-portal-umbriel.locked.rev` этого `flake.lock`, затем читает файлы portal по закреплённому SHA.
4. Сравнивает оба SHA с `current`. Если пара не изменилась, подготовка останавливается без изменений.
5. Для изменившихся проектов готовит ebuild и архивы. Предыдущая `current` становится `previous`; сохраняются только ebuild двух пар. Если portal SHA не изменился, его ebuild переиспользуется.
6. В закреплённых Gentoo images создаёт Manifest из загруженных архивов, проверяет порядок версий средствами Portage, запускает `pkgcheck scan --exit` и `emerge -pv` для точных версий.
7. Передаёт в отдельную publish job ограниченный artifact. Та проверяет его состав, разрешённый diff и совпадение base commit, затем открывает Draft PR через `GITHUB_TOKEN`.

В PR перечисляются старые и новые версии/SHA обоих проектов, upstream compare-ссылки, изменения packaging-файлов и результаты контейнерных проверок, artifact и base commit.

Prepare job не получает права записи в репозиторий, Gentoo container не получает GitHub credentials. Автоматизация не устанавливает Umbriel, не собирает пакет, не тестирует сессию, не выполняет merge и не включает auto-merge. `pkgcheck` проверяет ebuild, а `emerge -pv` — разрешение зависимостей.

Ручной запуск принимает `dry_run`. В этом режиме workflow выполняет discovery и показывает план, но не запускает контейнерную проверку и не создаёт artifact, branch или PR. Успешный `dry_run` не подтверждает локальный container prepare.

### Настройки GitHub

Это инструкции по настройке репозитория.

- Включите GitHub Actions. Если разрешены только выбранные Actions, добавьте `actions/checkout`, `actions/upload-artifact` и `actions/download-artifact` с SHA из `uses:` в workflow. GitHub сравнивает закреплённый SHA с allowlist; см. [настройки разрешённых Actions](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository).
- В **Settings → Actions → General → Workflow permissions** оставьте минимальные разрешения `GITHUB_TOKEN` по умолчанию и включите **Allow GitHub Actions to create and approve pull requests**, иначе publish job не сможет создать Draft PR. В workflow prepare имеет `contents: read` и `pull-requests: read`, publish — `contents: write` и `pull-requests: write`.
- Для основной ветки задайте required check **Python unit tests** из workflow [Python unit tests](.github/workflows/ci.yml), источник — GitHub Actions. Требуйте, чтобы ветка PR была актуальна перед merge.
- Перед merge вручную установите и проверьте пару в сессии Umbriel: запуск, ввод, вывод изображения, Noctalia при необходимости, демонстрацию экрана и picker портала.

PR, созданный с помощью `GITHUB_TOKEN`, может поставить запуск `pull_request` workflow в состояние ожидания. После проверки изменений пользователь с правом записи должен вручную выбрать **Approve workflows to run**. Это описано в [документации GitHub о запуске workflow из workflow](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow). PAT, GitHub App и `pull_request_target` для обхода подтверждения не используются.

### Повтор контейнерной проверки

Подготовьте отдельную чистую копию overlay, в которой `accepted-pairs.json`, ebuild и Manifest уже содержат пару-кандидата и fallback-пару. Из корня репозитория выполните:

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

Digest образов задаются в `.github/workflows/prepare-umbriel-snapshot.yml`. Меняйте их только согласованно и повторяйте полный набор проверок. В `scripts/gentoo_validate.py` находятся временные keyword и USE overrides для resolver; меняйте их только по новому выводу `emerge -pv`, затем повторите контейнерную проверку. Не запускайте `--autounmask`.

### Ручная проверка и границы результатов

Перед merge проверьте установленную пару в сессии Umbriel. CI проверяет Python-логику обновления, а контейнер — метаданные ebuild и зависимости. Они не выполняют сборку Umbriel или portal.

Отдельно фиксируйте три результата: локально выполненный prepare с контейнером и проверкой artifact; успешный GitHub `dry_run`, который проверяет discovery и показывает план. Noctalia обновляется отдельно и в автоматизацию Umbriel не входит.
