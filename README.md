# Umbriel overlay

Gentoo overlay содержит snapshot-сборки [Umbriel](https://github.com/noctalia-dev/umbriel) и его [XDG Desktop Portal backend](https://github.com/noctalia-dev/xdg-desktop-portal-umbriel). Каждая версия закреплена за полным upstream commit SHA. Workflow ежедневно проверяет ветку `cachix`, выполняет проверки кандидата и при обновлении открывает Draft PR.

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

Workflow [Prepare Umbriel snapshot pair](.github/workflows/prepare-umbriel-snapshot.yml) запускается ежедневно в `06:23 UTC`. Его также можно запустить вручную через GitHub Actions. Ручной запуск принимает `dry_run`: он показывает обнаруженный кандидат и план ротации, не создавая branch, commit, artifact или PR.

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

Перед первым запуском без `dry_run` откройте `Settings → Actions → General` и разрешите `Allow GitHub Actions to create and approve pull requests`. Если запись ветки разрешена, но эта настройка выключена, GitHub отклонит создание PR после отправки ветки-кандидата. После включения можно повторить запуск: workflow использует существующую ветку только при совпадении её tree и base commit. Убедитесь также, что политика репозитория или организации разрешает workflow права `contents: write` и `pull-requests: write`. Discovery использует только `contents: read` и `pull-requests: read`; PAT не требуется. Описание настройки находится в [документации GitHub Actions](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository#preventing-github-actions-from-creating-or-approving-pull-requests).

После review автоматизацию можно включить, запустив workflow вручную без `dry_run` или дождавшись ежедневного запуска. До этого ручного включения публикация Draft PR не проверена в настройках самого репозитория.
