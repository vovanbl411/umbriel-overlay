# Umbriel overlay

Этот Gentoo overlay содержит ebuild для [Umbriel](https://github.com/noctalia-dev/umbriel) и его XDG Desktop Portal backend. Каждая версия привязана к полному upstream SHA; обновления готовятся и проверяются вручную.

## Подключение

Создайте `/etc/portage/repos.conf/umbriel-overlay.conf`:

```ini
[umbriel-overlay]
location = /var/db/repos/umbriel-overlay
sync-type = git
sync-uri = https://github.com/vovanbl411/umbriel-overlay.git
auto-sync = yes
```

Затем выполните `emerge --sync umbriel-overlay`. Чтобы установить подготовленные версии, укажите точные атомы:

```sh
emerge -av =gui-wm/umbriel-0.1.0_pre20261026184522 =gui-libs/xdg-desktop-portal-umbriel-0.1.0_p20261024195939
```

## Источники и версия-кандидат

Кандидат Umbriel выбирается из ветки `cachix` репозитория `noctalia-dev/umbriel`. После разрешения ветки на полный коммит читаются `VERSION`, `flake.lock` и исходники Umbriel именно этого коммита. SHA портала берётся только из узла `xdg-desktop-portal-umbriel` этого `flake.lock`; его исходники также читаются по полному SHA.

| Пакет | Статус | upstream base version | Версия ebuild | Полный SHA исходников |
| --- | --- | --- | --- | --- |
| `gui-wm/umbriel` | подготовленный кандидат | `0.1.0` | `0.1.0_pre20261026184522` | `366739955d3905d7600638eb637941b2782c0c68` |
| `gui-libs/xdg-desktop-portal-umbriel` | подготовленный кандидат | `0.1.0` | `0.1.0_p20261024195939` | `e69d6f72122a99aa3668e182a4df8755ada81c17` |

Snapshot-версия содержит UTC-время соответствующего коммита в формате `YYYYMMDDHHMMSS`. Для Umbriel используется `_pre`. Для portal используется `_p`: при той же upstream base version суффикс `_pre` оказался бы ниже существующей версии `0.1.0_p20260926` по правилам Portage. Portal SHA закреплён в `flake.lock` выбранного коммита Umbriel. Эти версии подготовлены из согласованных источников; пользовательская проверка работающей сессии ещё не выполнена.

## Существующие версии

Старые ebuild оставлены без изменений и удаления. Они закрепляют другую комбинацию исходников и не считаются парой, согласованной с upstream `flake.lock`:

| Пакет | Версия ebuild | Закреплённый SHA |
| --- | --- | --- |
| `gui-wm/umbriel` | `0.0.0_pre20261008` | `185b559ca6bb2be7af0a28e2c75455d6f926552b` |
| `gui-libs/xdg-desktop-portal-umbriel` | `0.1.0_p20260926` | `d6bd72cabd83e3084fb2f2e24898d8ffa4a8c24f` |

Noctalia обновляется отдельно по релизам и в эту пару snapshot-версий не входит.

## Правила будущего обновления

- Использовать `cachix` как источник кандидатов Umbriel.
- Сначала закрепить ветку полным Umbriel SHA, затем читать все upstream-файлы по этому SHA.
- Получать portal SHA только из `flake.lock` закреплённого Umbriel; не выбирать портал по отдельной ветке или последнему релизу.
- Закреплять все исходники полными SHA и создавать новую версию ebuild. Не менять исходники под существующим именем версии или distfile.
- Генерировать Manifest по фактическим архивам.
- Хранить текущую и предыдущую принятую пару. Если portal SHA общий для обеих пар, оставлять один ebuild портала.
- Создавать один Draft PR одновременно, без auto-merge. Пока кандидат проверяется, автоматизация не переписывает его и не открывает следующий PR.
- Считать пару принятой только после проверки пользователем; один лишь подготовленный Draft PR этого статуса не даёт.

## Проверки кандидата

Для новых ebuild выполните из корня overlay:

```sh
git diff --check
pkgcheck scan --exit gui-wm/umbriel gui-libs/xdg-desktop-portal-umbriel
emerge -pv =gui-wm/umbriel-0.1.0_pre20261026184522
emerge -pv =gui-libs/xdg-desktop-portal-umbriel-0.1.0_p20261024195939
```

Порядок версий следует проверять парсером версий Portage, а Manifest — генерировать из загруженных архивов новых ebuild. Убедитесь, что полный SHA портала совпадает с `nodes.xdg-desktop-portal-umbriel.locked.rev` в `flake.lock` выбранного коммита Umbriel.

`pkgcheck` и `emerge -pv` проверяют метаданные и разрешение зависимостей. Они не подтверждают сборку и работу сессии. Перед merge пользователь должен установить именно подготовленную пару, войти в Umbriel и вручную проверить запуск сессии, базовый ввод и вывод изображения, Noctalia при необходимости, а также демонстрацию экрана и picker портала.
