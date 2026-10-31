# Atlas

Настольное приложение для сверки фото деталей (платы, SSD и т. п.) на однотипность и дефекты.
Разработка — macOS, целевая машина — Windows 7.

## Как начать (для человека)

1. Положите эту папку как `Atlas`, сделайте `git init`.
2. В терминале: `cd Atlas && claude`
3. Первая команда агенту:

   ```
   /step 0.1
   ```

   Агент спросит список ваших репозиториев на GitHub (owner/repo) и соберёт из них
   данные о целевой машине, что уже протестировано, стиль Digger и код, который можно переиспользовать.

4. Дальше по одному шагу: `/step 0.2`, `/step 0.3` … После каждого шага агент пишет:
   - **Чат:** можно ли очищать (`/clear`)
   - **Дальше:** следующий шаг
   - **Модель:** какую включить (`/model opus` / `/model sonnet` / `/model haiku`)

## Команды агента

| Команда | Что делает |
|---|---|
| `/step 3.2` | выполнить шаг плана |
| `/status` | где мы сейчас, что дальше |
| `/new-feature имя: описание` | добавить новую функцию (отдельным модулем) |
| `/change-feature имя: что поменять` | изменить существующую функцию |
| `/remove-feature имя` | удалить функцию целиком, ничего не сломав |

## Файлы

| Файл | Зачем |
|---|---|
| `CLAUDE.md` | правила для агента (читается автоматически) |
| `PLAN.md` | план по шагам |
| `PROGRESS.md` | журнал: что сделано, решения, проблемы — память между очистками чата |
| `docs/ARCHITECTURE.md` | как устроен код, чтобы функции легко добавлять/менять/удалять |
| `docs/UI_SPEC.md` | описание экранов по макету |
| `docs/TARGET_MACHINE.md` | целевая машина и уже проверенное (заполняется на шаге 0.1) |
| `docs/OPEN_ITEMS.md` | что ещё нужно от вас |
| `design/mockup/` | исходники макета (8 экранов) |

## Окружение разработчика (macOS)

```bash
uv venv --python 3.8 .venv                      # Rosetta не нужна: PyQt5 ставится нативно на arm64
uv pip install -p .venv -r requirements-dev.txt
.venv/bin/python -m pytest                      # QT_QPA_PLATFORM=offscreen задан в tests/conftest.py
.venv/bin/vermin --target=3.8- --no-tips --violations atlas/ tests/
.venv/bin/python -m atlas                       # окно с вкладками из config/features.json
```

Проверено на Apple Silicon (arm64): Python 3.8, PyQt5 5.15.10, PyQt5-Qt5 5.15.19 (на Windows — 5.15.2, см. `requirements.txt`).

## Сборка под Windows 7

Собирает GitHub Actions (`.github/workflows/build-windows.yml`) при push в `main` и вручную: тесты, PyInstaller, проверка импортов на Win7,
`--selfcheck` из папки с кириллицей и по UNC, две `--dbcheck` на общей базе по SMB. Результат — артефакт `atlas-win7-x64.zip`,
отчёты и снимки — `ci_reports`. На целевой машине проверять по `docs/WIN7_CHECK.md` (лежит и в zip).

Локально на Windows:

```bat
python -m pip install -r requirements-dev.txt
python -m PyInstaller packaging\atlas.spec --noconfirm --distpath dist --workpath build\pyinstaller
python scripts\check_pe_imports.py dist\atlas
python scripts\assemble_dist.py dist\atlas
```

Проверки без человека: `atlas.exe --selfcheck ПАПКА`, `atlas.exe --dbcheck ПАПКА [--report ПАПКА] [--seconds N] [--label ИМЯ]`.
Exe оконный и в консоль ничего не пишет: результат — код выхода и отчёт в файле.
