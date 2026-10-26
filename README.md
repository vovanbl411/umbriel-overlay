# Umbriel overlay

Gentoo overlay содержит snapshot-сборки [Umbriel](https://github.com/noctalia-dev/umbriel) и его [XDG Desktop Portal backend](https://github.com/noctalia-dev/xdg-desktop-portal-umbriel). Каждая версия закреплена за полным upstream commit SHA. Отдельный PR CI запускает offline unit tests. Автоматизация snapshot ежедневно проверяет ветку `cachix`, выполняет проверки кандидата и при обновлении открывает Draft PR.

## Подключение

Создайте `/etc/portage/repos.conf/umbriel-overlay.conf`:

```ini
[umbriel-overlay]
location = /var/db/repos/umbriel-overlay
sync-type = git
sync-uri = https://github.com/vovanbl411/umbriel-overlay.git
auto-sync = yes
```

Затем выполните `emerge --sync umbriel-overlay`. Для установки текущей принятой пары укажите точные версии `current` из [automation/accepted-pairs.json](automation/accepted-pairs.json) в атомах Portage.

## Принятая пара

Пользователь подтвердил успешные сборку, установку и работу этой пары. Другие результаты проверок ей не приписываются.

<!-- accepted-pairs:start -->
| Статус | Версии Umbriel / portal | SHA Umbriel / portal |
| --- | --- | --- |
| Принятая текущая пара | `0.1.0_pre20261026184522` / `0.1.0_p20261024195939` | `366739955d3905d7600638eb637941b2782c0c68` / `e69d6f72122a99aa3668e182a4df8755ada81c17` |
<!-- accepted-pairs:end -->

Файл состояния — единственный источник связи версий и SHA. `current` задаёт пару, которая будет принята после merge соответствующего PR. `previous` хранит предыдущую принятую пару для отката. Сейчас `previous` равен `null`; первая ротация перенесёт текущую принятую пару в `previous` и удалит исторические ebuild, которые не входят в эти пары. Если SHA портала совпадает в обеих парах, для него остаётся один ebuild.

Исторические ebuild в основной ветке до первой автоматической ротации не считаются принятыми парами. Их SHA не следует использовать для вывода соответствия Umbriel и portal.

## Подготовка обновлений

Workflow [Python unit tests](.github/workflows/ci.yml) запускается на `push` и `pull_request`. Job проверки называется `Python unit tests`.

Workflow подготовки snapshot [Prepare Umbriel snapshot pair](.github/workflows/prepare-umbriel-snapshot.yml) запускается по расписанию ежедневно в `06:23 UTC` и вручную через GitHub Actions. Ручной запуск принимает `dry_run`: он показывает обнаруженный кандидат и план ротации, не создавая branch, commit, artifact или PR.

Порядок подготовки:

1. Проверить, нет ли открытого автоматического PR. При его наличии запуск завершится без обращения к `cachix` и без изменения кандидата.
2. Один раз разрешить `cachix` в полный Umbriel commit SHA. `VERSION`, `flake.lock` и packaging-файлы читать только по этому SHA.
3. Получить portal SHA только из `nodes.xdg-desktop-portal-umbriel.locked.rev` этого `flake.lock`. Файлы портала и дату его commit читать по указанному SHA.
4. Сравнить оба SHA с `current` из файла состояния. Если SHA не изменились, новую пару не готовить.
5. Для каждого изменившегося проекта создать отдельный ebuild и distfile. Версия включает upstream base version и UTC timestamp commit: Umbriel использует `_pre`, portal — `_p`. Если SHA портала не изменился, существующий ebuild повторно используется.
6. Перенести прежнюю `current` в `previous`, обновить README, удалить ebuild вне двух хранимых пар и выполнить проверки в закреплённом Gentoo container. `pkgcheck` устанавливается только во временный container; система пользователя не меняется.
7. Передать только ограниченный artifact в отдельный job публикации. Он проверит состав artifact, allowlist diff и совпадение base commit, затем создаст ветку и Draft PR через встроенный `GITHUB_TOKEN`.

Кандидат в PR не становится принятой парой до merge. Пока автоматический PR открыт, продвижение `cachix` не меняет его содержимое и не создаёт второй PR. Автоматизация не включает auto-merge и не устанавливает пакеты.

В описании PR указываются старые и новые версии/SHA обоих проектов, upstream compare-ссылки, изменения packaging-файлов, результаты Manifest, `pkgcheck`, Portage-порядка версий, `emerge -pv`, проверок artifact и base commit. Эти проверки не заменяют сборку и ручную проверку сессии.

## Проверка пары перед merge

Для кандидата, подготовленного автоматизацией, необходимо вручную проверить установленную пару в сессии Umbriel. `pkgcheck scan --exit` проверяет ebuild, а `emerge -pv` — разрешение зависимостей; ни одна из этих команд не подтверждает сборку или работоспособность сессии. Перед merge проверьте запуск сессии, базовый ввод и вывод изображения, Noctalia при необходимости, демонстрацию экрана и picker портала.

## Настройки GitHub

### Actions и токен

Включите GitHub Actions для репозитория. Если политика репозитория ограничивает Actions, разрешите закреплённые в workflow `actions/checkout` и `actions/upload-artifact`.

В **Settings → Actions → General → Workflow permissions** оставьте минимальные разрешения по умолчанию для `GITHUB_TOKEN`. Включите **Allow GitHub Actions to create and approve pull requests**: без этой настройки workflow не сможет открыть Draft PR. Workflow задаёт права отдельно для каждой job: prepare получает `contents: read` и `pull-requests: read`, publish — `contents: write` и `pull-requests: write`.

При создании или обновлении PR через `GITHUB_TOKEN` событие `pull_request` может поставить CI в состояние ожидания подтверждения. После проверки изменений в PR пользователь с правом записи должен нажать **Approve workflows to run**. Это поведение описано в [документации GitHub о запуске workflow из workflow](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow). Для обхода этого шага не используются PAT, GitHub App или `pull_request_target`.

### Проверки перед merge

Для основной ветки настройте protection rule или ruleset:

- требуемая проверка — job **Python unit tests** из workflow [Python unit tests](.github/workflows/ci.yml), источник проверки — GitHub Actions;
- включите требование актуальности ветки PR перед merge (**Require branches to be up to date before merging**);
- перед принятием пары вручную проверьте её установку и работу в сессии Umbriel. `pkgcheck` и `emerge -pv` проверяют ebuild и разрешение зависимостей, но не сборку и не работу сессии.

### Параметры запуска и повтор контейнерной проверки

Ручной запуск workflow **Prepare Umbriel snapshot pair** принимает параметр `dry_run`. При `true` workflow выполняет discovery, вызывает prepare в режиме dry run и показывает план, но не запускает контейнерную проверку и не создаёт artifact, branch или PR. При обычном запуске container validation работает с подготовленной парой.

Версии окружения задаются в `GENTOO_PORTAGE_IMAGE` и `GENTOO_STAGE3_IMAGE` в `.github/workflows/prepare-umbriel-snapshot.yml`. Используются образы по digest; меняйте digest только после проверки новой связки Portage tree и Stage3 и повторного выполнения всех команд ниже. В `scripts/gentoo_validate.py` заданы временные keyword и USE overrides для resolver. Меняйте их только по новому выводу `emerge -pv` закреплённого окружения; не запускайте `--autounmask`.

Чтобы повторить контейнерную проверку локально, сначала подготовьте чистую копию overlay с парой-кандидатом и fallback-парой в `automation/accepted-pairs.json`, включая их ebuild. Затем из корня репозитория выполните:

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

Команда использует те же digest и validation script, что и workflow. Она генерирует Manifest из загруженных архивов, проверяет thin Manifest и `SRC_URI`, порядок версий средствами Portage, запускает `pkgcheck scan --exit` и `emerge -pv` для точных версий из `current`. При обновлении resolver overrides повторите эту же команду и проверьте весь вывод.

Результаты следует различать:

- **Локально проверенный prepare** — завершились подготовка, container validation, artifact, его применение к отдельной Git-копии base commit и `verify-diff`.
- **Успешный GitHub `dry_run`** — workflow успешно выполнил offline tests и discovery и показал план; это не выполняет контейнерную подготовку.
- **Реальная публикация первого update PR** — подтверждается только фактическим запуском publish job и появлением Draft PR. Пока такой запуск не выполнен, публикация не считается проверенной.
