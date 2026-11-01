# Архитектура Atlas

Цель — чтобы любую функцию можно было **добавить, изменить, отключить или удалить**, не трогая остальные.

## Слои

```
atlas/
  app.py                      # точка входа: конфиг → ядро → загрузка функций → главное окно
  selfcheck.py                # --selfcheck: вход и вкладки без человека, отчёт и снимки (CI, выезд)
  dbcheck.py                  # --dbcheck: SQLite на сетевом диске, обрыв сети, два ПК
  core/                       # ядро: ничего не знает о конкретных функциях
    app_context.py            # AppContext: config, db, bus, services, user, paths
    feature.py                # FeatureSpec, Feature (базовый класс)
    registry.py               # FeatureRegistry: читает config/features.json, импортирует, сортирует по зависимостям
    bus.py                    # EventBus: publish/subscribe (через Qt-сигналы, потокобезопасно)
    services.py               # ServiceRegistry: register/get/get_optional
    db.py                     # подключение SQLite, ретраи, MigrationRunner (миграции ядра + каждой функции)
    config.py                 # config/*.json + локальные настройки машины (config/local.json, не в git)
    domain/                   # таблицы ядра (users, projects, devices, parts, folders, photos) и сервисы к ним
    logging_setup.py          # журнал в logs/, сбор ошибок
    qt_runtime.py             # подготовка Qt до QApplication
    theme/                    # atlas.qss, tokens.json (цвета), иконки SVG
    shell/                    # главное окно: верхняя полоса, вкладки, строка контекста, слоты панелей
  shared/                     # переиспользуемое, без бизнес-логики
    viewer/                   # PhotoView, SyncGroup, ImageCache, Filmstrip
    annotate/                 # инструменты: выделение, эллипс, подпись, UndoStack
    widgets/                  # NameTag, ContextBar, SearchBox, StampAnimation, Toast
    outlook/                  # base.py, outlook_win.py, outlook_fake.py
    fs/                       # сетевые пути, безопасное копирование, блокировки файлов
  features/
    <id>/
      __init__.py             # FEATURE = FeatureSpec(...)
      logic.py                # чистая логика — без Qt, тестируется отдельно
      repo.py                 # доступ к своим таблицам
      ui.py                   # виджеты/вкладка
      migrations/001_init.sql
      tests/
config/
  features.json               # какие функции включены и в каком порядке
  app.json                    # сетевые пути, режим fake/real, лимиты памяти
data/                         # справочники: defect_kinds.json, placement_rules.json, hotkeys.json …
templates/                    # mail_reply.html, excel_columns.json
packaging/                    # atlas.spec, bundle_contents.py, version_info.txt, bat/ (проверки на выезде)
scripts/                      # check_pe_imports.py, assemble_dist.py
```

Новая функция попадает в сборку сама: `packaging/bundle_contents.py` обходит `atlas/`, берёт все модули и все файлы, кроме кода
(без `tests` и `_template`). Рядом с exe лежат `config/`, `data/`, `templates/`, их можно менять без пересборки.

## Контракт функции

```python
# atlas/features/rules/__init__.py
from atlas.core.feature import FeatureSpec
FEATURE = FeatureSpec(
    id="rules",
    title="Правила",
    version=1,
    requires=[],                     # жёсткие зависимости (другие функции) — по возможности пусто
    optional=["compare"],            # если есть — используем, если нет — работаем без них
    tab_order=40,                    # место вкладки; None — функция без вкладки
    factory="atlas.features.rules.ui:RulesFeature",
)
```

```python
class Feature:
    def __init__(self, ctx): ...          # AppContext
    def on_start(self): ...               # подписки на события, регистрация сервисов
    def create_tab(self): ...             # QWidget или None
    def badge(self): ...                  # счётчик/подсветка на вкладке или None
    def settings_page(self): ...          # страница в «Настройках» или None
    def on_stop(self): ...
```

Ядро загружает только функции из `config/features.json`. Отключённая функция **не импортируется**.

```json
{"features": [{"id": "rules", "enabled": true, "tab_order": 40}]}
```

`tab_order` в `features.json` необязателен и важнее значения в `FeatureSpec`. Запись без `tab_order` берёт значение из `FeatureSpec`.

Ошибка функции (импорт, зависимости, миграции, запуск) не роняет приложение: она пишется в журнал, в `registry.failures` и в событие `feature.failed`.

## БД из кода функции

```python
rows = ctx.db.read(lambda conn: conn.execute("SELECT ...").fetchall())
ctx.db.write(lambda conn: conn.execute("INSERT ...", (...)))
```

На каждый вызов — своё подключение, поэтому вызывать можно из любого потока (но не из GUI). При блокировке транзакция откатывается и функция вызывается заново, поэтому внутри неё — только работа с базой и никаких вложенных `read`/`write`. Если база занята дольше всех повторов — `DatabaseBusyError`.
Миграции применяются при старте: сначала ядра (`core/domain/migrations`, ошибка останавливает запуск), потом функций. Менять уже применённый файл нельзя (проверяется контрольная сумма).

## Правила связей
1. `features/X` импортирует только `atlas.core.*` и `atlas.shared.*`. Проверяет `tests/test_boundaries.py` (ast-разбор импортов).
2. Сообщить другим — `ctx.bus.publish("finding.added", {...})`. Что-то получить — `ctx.services.get_optional("type_db")`;
   если `None` — блок интерфейса скрывается, а не падает.
3. Функция встраивается в чужой экран только через **слоты** оболочки: `ctx.shell.add_panel("compare.right", widget)`.
   Например, сводка по детали — функция `findings` кладёт свою панель в слот `compare.right`.
4. Свои таблицы — только свои. Чужие данные — через сервис владельца. Таблицы ядра — через сервисы `users`, `parts`, `folders`; они есть всегда.
5. Всё, что меняется без программиста (списки, шаблоны, горячие клавиши), — в `data/` и `templates/`.

## Функции (план)

| id | Что делает | Вкладка | Слоты, куда встраивается |
|---|---|---|---|
| `hello` | тестовая: проверка вкладки, сервиса, миграции | Привет | — |
| `login` | вход по фамилии, теги | — (диалог при старте) | `shell.user` |
| `presence` | кто сейчас работает и над какой папкой | — | `shell.online` |
| `compare` | просмотр 1…N фото, синхронный зум, листание, отметки | Сравнение | создаёт слоты `compare.left/right/toolbar` |
| `folders` | панель истории копирования (данные — сервис ядра `folders`) | — | `compare.left` |
| `annotate_tools` | ножницы, обводка, подпись | — | `compare.toolbar` |
| `type_db` | база типов, поиск, архив | База типов | `compare.toolbar` (+ В базу) |
| `findings` | дефекты/замечания, сводка по детали, «проблемная деталь» | — | `compare.right` |
| `import_mail` | письмо → план копирования → копирование | Импорт | — |
| `rules` | правила проверки, непрочитанные | Правила | `compare.right` (правила к детали) |
| `comments` | временные сообщения с фото | Комментарии | — |
| `draft` | черновик, автосписок найденного | Черновик | — |
| `report` | Excel + письмо-ответ в Outlook | — | `draft.actions` |
| `dashboard` | статистика | Дашборд | — |
| `history_import` | выгрузка старых писем (в конце, необязательно) | — | страница настроек |

## Слоты оболочки (поддерживать актуальным)

API окна, `ctx.shell`: `add_panel(слот, widget, key=None, order=0)` (тот же `key` заменяет панель), `remove_panel`, `register_slot(имя, layout)`,
`set_context(kind, project, device, part, path)`, `show_message(текст)`, `refresh_badges()`. Панель можно добавить раньше слота — дождётся его.
Нет слота (владелец отключён) — панель молча не показывается.

| Слот | Владелец | Что кладут |
|---|---|---|
| `shell.user` | оболочка | тег пользователя (`login`) |
| `shell.online` | оболочка | «кто онлайн» (`presence`) |
| `login.summary` | login | «С вашего последнего входа» (правила, комментарии, папки) — только на время диалога |
| `login.aside` | login | «Сейчас в работе», последние папки — только на время диалога |

Слоты `compare.*`, `draft.actions` появятся вместе с их владельцами.

## События (поддерживать актуальным)

| Событие | Кто публикует | Данные |
|---|---|---|
| `feature.failed` | ядро (registry) | `{id, stage, error}` |
| `user.logged_in` | login | `{user}` — `atlas.core.app_context.User(id, name, color)` |
| `presence.changed` | presence | `{online}` — список `OnlineUser(user_id, name, color, folder_id, folder_text)` |
| `folder.copied` | import_mail | `{folder_id, part_id}` |
| `folder.opened` | compare | `{folder_id, part_id}` |
| `folder.done` | report | `{folder_id}` |
| `photo.changed` | compare | `{folder_id, photo_id, index}` |
| `photo.marked` | compare | `{photo_id, mark, sn}` |
| `finding.added` | findings | `{finding_id, part_id, kind, sn}` |
| `type.added` / `type.archived` / `type.restored` | type_db | `{type_id, part_id}` |
| `rule.published` | rules | `{rule_id, part_id?}` |
| `comment.posted` | comments | `{comment_id, to_user?}` |

## Сервисы (поддерживать актуальным)

| Имя | Владелец | Методы |
|---|---|---|
| `hello` | hello (тестовая) | `greet(name)` |
| `login` | login | `run(parent)` → User или None, `current()`, `users()`, `sign_in(user)` |
| `presence` | presence | `online()`, `working_on(folder_id)` — из памяти, можно в GUI-потоке |
| `image_cache` | shared/viewer (ядро) | `get(path, level, priority=CURRENT)` → `CachedImage(image, level)` или None, `prefetch(paths)`, `cancel_pending()`, `forget(path)`; сигналы `ready(path, level, QImage)`, `failed(path, level, текст)`. Можно из GUI-потока: смотрит только в память |
| `outlook` | shared/outlook (ядро) | `selected_mail()`, `reply(mail, html)` |
| `type_db` | type_db | `types_for_part(part_id, include_archived)`, `search(q)` |
| `findings` | findings | `summary(part_id, days)`, `add(...)` |
| `users` | ядро | `all()` → [(User, last_login_at)], `add(name, color_for)`, `touch(id)` |
| `parts` | ядро | `ensure(kind, project, device, part, article)` → Part, `get(id)`, `find(name)`, `all()` |
| `folders` | ядро | `add(part_id, path, folder_date, created_by)`, `get(id)`, `recent(limit, status)`, `set_status(id, status, user_id)`, `add_photos(folder_id, rel_paths)`, `photos(folder_id)`, `mark_photo(photo_id, mark, sn, user_id)`, `counts(folder_ids)` |

## Картинки 3456×5184, 5–15 МБ

Одно фото в памяти целиком ≈ 72 МБ (RGBA). Поэтому — уровни:

| Уровень | Размер | Как получаем | Где храним |
|---|---|---|---|
| L0 миниатюра | ~160 px | из L1, без второго чтения исходника | диск: локальный кэш + память |
| L1 превью | 1/4 (864×1296, ~4,5 МБ) | JPEG DCT-масштабирование (быстро) | диск + память |
| L2 половина | 1/2 (~18 МБ) | там же | память, текущее ±1 |
| L3 полное | ~72 МБ | полное декодирование | память, только текущее (±1 при сильном зуме) |

- Листание: сразу L1, через 100–300 мс после остановки — L2/L3 для видимой области.
- После копирования папки — фоновый «прогрев» L0/L1 на локальный диск (`%LOCALAPPDATA%\Atlas\cache`, ключ: путь+размер+mtime).
- `get` отдаёт лучшее из памяти сразу (точный уровень, иначе выше, иначе ниже) и при необходимости ставит запрос в очередь: текущее > соседи > прогрев; внутри приоритета новые первыми; прогрев не занимает последний поток.
- Лимит памяти (`image_cache` в `config/app.json`), по объёму RAM целевой машины (из `docs/TARGET_MACHINE.md`). Нужен 64-битный Python.
- `setAutoTransform(True)` — учитывать EXIF-поворот.
- Синхронизация — в **нормализованных** координатах (доли ширины/высоты), чтобы фото разного размера смотрели в одно место.

## Как добавить / изменить / удалить функцию
- **Добавить:** `/new-feature id: описание` — шаблон папки, `FEATURE`, миграция, тест, строка в `features.json`, строки в таблицах выше.
- **Изменить:** `/change-feature id: что` — правится только папка функции (+ `data/`, `templates/`). Если меняется
  событие или сервис — сохранить старое поле/метод или обновить всех подписчиков и таблицу.
- **Удалить:** `/remove-feature id` — убрать из `features.json`, прогнать тесты независимости, удалить папку и строки в таблицах.
  Таблицы в БД остаются (безопасно), удаляются отдельной миграцией ядра только по просьбе.
