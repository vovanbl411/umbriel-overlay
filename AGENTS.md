# Инструкции для этого репозитория

## Назначение и границы

Это Gentoo overlay для snapshot-версий Umbriel и `xdg-desktop-portal-umbriel`. Описание принятой пары и работы автоматизации находится в [README.md](README.md) и [README.en.md](README.en.md), соответствие версий и SHA хранится в [automation/accepted-pairs.json](automation/accepted-pairs.json).

Разрешённая область изменений для этой автоматизации:

- `gui-wm/umbriel/` и `gui-libs/xdg-desktop-portal-umbriel/`, включая ebuild и Manifest;
- `automation/accepted-pairs.json`;
- `scripts/`, `tests/`, `.github/`;
- `README.md`, `README.en.md` и `AGENTS.md`.

Не менять другие оверлеи, пользовательскую конфигурацию, установленную систему или upstream. Не устанавливать пакеты локально. Не выполнять push, merge или реальную публикацию тестового Draft PR. Сохранять ebuild до тех пор, пока ротация не удаляет его как версию вне двух пар в состоянии.

## Источники и snapshot-версии

- Umbriel-кандидат разрешается только из ветки upstream `cachix` в полный SHA. Один раз получить SHA, затем читать `VERSION`, `flake.lock` и остальные файлы Umbriel по нему.
- SHA `xdg-desktop-portal-umbriel` брать только из `nodes.xdg-desktop-portal-umbriel.locked.rev` файла `flake.lock` закреплённого Umbriel commit. Исследовать портал только по этому SHA.
- Проверять форму обоих полных SHA, наличие lock node и версию portal из его исходников. Некорректные данные должны прекращать discovery с причиной.
- Новая версия содержит upstream base version и UTC timestamp commit в формате `YYYYMMDDHHMMSS`. Для Umbriel сохранять `_pre`, для portal — `_p`. Проверять, что версия увеличилась, средствами Portage. Не менять содержимое ebuild под существующей версией или distfile.
- Не создавать новый portal ebuild, если SHA portal совпадает с хранимой парой. Общий SHA portal в current и previous использует один ebuild.
- Сверять зависимости ebuild с Meson dependencies и `umbrielfx`. Явно задавать Meson options для USE-управляемых и необязательных путей, чтобы сборка не зависела от случайно установленных библиотек. Не добавлять USE-флаги без необходимости.
- Сохранять EAPI 8, SLOT 0, KEYWORDS `~amd64` и назначение USE `jemalloc`, `screencast` и `picker`.
- Manifest генерировать в Gentoo container из фактически загруженных distfile архивов.

## Состояние принятых пар

- `automation/accepted-pairs.json` — единственный источник соответствия версий и SHA. Не выводить пары независимо из самых новых ebuild.
- `current` обозначает принятую пару в основной ветке. `previous` содержит предыдущую принятую пару либо `null` до первой ротации.
- В Draft PR обновлять state, ebuilds, Manifest и таблицы в обоих README атомарно. До merge состояние основной ветки остаётся прежним.
- Оба README используют маркеры `accepted-pairs:start` и `accepted-pairs:end`; автоматически менять разрешено только таблицу между ними. Заголовки таблицы локализуются, версии и SHA формируются из одного `automation/accepted-pairs.json`.
- При ротации переносить нынешнюю `current` в `previous`, удалять ebuild вне этих пар и добавлять кандидата. Если SHA portal общий, оставлять один ebuild.
- Принятой считать только пару, попавшую в `main` после merge. Не приписывать паре проверки, которых не выполняли.
- Noctalia обновляется отдельно и в автоматизацию Umbriel не входит.

## Автоматизация и безопасность публикации

- Сохранять отдельные read-only prepare и publish jobs. Prepare не получает repository write credentials. Gentoo container не получает GitHub credentials.
- Упаковывать только ограниченный artifact после подготовки и проверок. В publish повторно проверять состав файлов, allowlist diff и исходный base commit. При несовпадении base commit останавливать публикацию.
- Использовать только встроенный `GITHUB_TOKEN` с минимальными правами job. Не добавлять PAT, auto-merge, установку пакетов или действия, которые пишут в upstream.
- Закреплять GitHub Actions по полному commit SHA, container images — по digest.
- При ограничении разрешённых Actions оставлять только `actions/checkout`, `actions/upload-artifact` и `actions/download-artifact`.
- Проверять открытый automation PR до discovery upstream. Если он открыт, завершать запуск без нового кандидата и не переписывать существующий PR при продвижении `cachix`.
- При отсутствии обновления завершать запуск без подготовки. `dry_run` не создаёт branch, commit, artifact или PR.
- Не добавлять отдельное сопоставление двух main-веток и ожидание upstream bot commits.
- Discovery отражает изменения `PACKAGING.md`, `meson.build`, `meson_options.txt`, `VERSION` и `flake.lock` обоих проектов. PR описывает старые/новые версии и SHA и содержит compare-ссылки.
- Комментарии в scripts/workflow писать по-русски, когда они объясняют нетривиальную логику, влияние изменяемых параметров, связанные настройки или security/correctness constraints. Очевидные операции не комментировать.

## Проверка

Локально выполнить:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
git diff --check
```

Focused tests должны покрывать чтение пары, отсутствие обновления, открытый PR, обновление только Umbriel, обновление обоих проектов, ротацию, повторное использование portal ebuild, `dry_run`, неверный lock/SHA, конфликт base commit, artifact и allowlist diff.

В workflow, внутри закреплённого Gentoo container:

- генерировать Manifest из новых или повторно используемых архивов;
- проверять порядок версий средствами Portage;
- запускать `pkgcheck scan --exit` для обоих пакетов;
- запускать `emerge -pv` с точными кандидатными версиями.

`pkgcheck` и `emerge -pv` не подтверждают сборку или работу сессии. Перед merge нужна ручная проверка установленной пары в сессии Umbriel.
