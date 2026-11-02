# Целевая машина

> Заполнено на шаге 0.1 (2026-10-31) из прошлых проектов на GitHub. Каждый факт — со ссылкой на источник.
> Здесь же — что **уже проверено** на этой машине: такие вещи в Atlas не тестируем повторно, а берём готовое решение.
> Чего нет в репозиториях — в `docs/OPEN_ITEMS.md`.

Источники (клоны в `_refs/`, в git не попадают):
`curator` @1c207a3 · `matcher` @b691492 · `digger` @224e0ae · `cvision` @07179d2.
`rename` — ранняя версия `cvision` (та же история и те же файлы, остановилась на 6b5c05c), отдельно не разбирается.

## Железо и ОС
| Параметр | Значение | Источник |
|---|---|---|
| ОС, сборка, разрядность | Windows 7 SP1, build 7601, x64 | `curator/ARCHITECTURE.md` §21.3 |
| Service Pack, важные обновления | SP1. `ucrtbase.dll` есть в System32 (UCRT, KB3118401). KB2533623/KB2999226 в списке нет, но заменены более новыми: `AddDllDirectory` есть | `matcher/docs/TARGET_ENV.md` §1 |
| CPU | Intel i5-6500: 4 ядра, без HT, AVX2 | `matcher/docs/TARGET_ENV.md` §1 |
| RAM | 16 ГБ | `matcher/docs/TARGET_ENV.md` §1, `digger/CLAUDE.md` |
| Видео / OpenGL | Встроенная графика, дискретной нет. Версия OpenGL не выяснялась; OpenGL не нужен: Qt Widgets и `QGraphicsView` рисуем программно, без `QOpenGLWidget` | `digger/CLAUDE.md`, `digger/docs/ARCHITECTURE.md` (стр. 24, 454) |
| Разрешение экрана, масштаб (DPI) | 1920×1080, DPI 96, масштаб 1.0. Системный шрифт крупнее, чем на Mac: размеры считать от шрифта | `selfcheck`, выезд 02.11.2026; `cvision/docs/decisions.md` |
| Права администратора | Нет. Только portable-папка: без установщиков, реестра, служб и открытых портов | `matcher/docs/TARGET_ENV.md` §2, `digger/CLAUDE.md` |
| Антивирус / блокировка .exe | Kaspersky. Запуск exe из папки пользователя и с сетевого диска через букву работает (выезд 02.11.2026). По UNC не проверялся | `curator/ARCHITECTURE.md` §21.3, `matcher/docs/TARGET_ENV.md` §5 |
| Сеть: сетевые диски, буквы, UNC-пути | Минимум два сетевых диска, `R:` и `N:`; пути с кириллицей и пробелами. Чтение и запись через букву диска работают. UNC на этой машине не подтверждён, только в CI | `curator/ARCHITECTURE.md` §21.3, `curator/STATUS.md` |
| Интернет | **Источники расходятся:** `matcher` и `cvision` — offline; в `digger` с рабочего ПК доступны 42 из 87 сайтов. Atlas интернет не нужен, считаем, что его нет | `matcher/docs/TARGET_ENV.md` §1, `cvision/README.md`, `digger/docs/PROGRESS.md` (2026-10-03) |
| Доступ к машине | «Выезды», примерно раз в день. Проверки собираются в пачку и не останавливают разработку | `digger/CLAUDE.md` |
| Outlook: версия, Exchange или нет | Outlook 2016 MSO, 32-разрядный (программа 64-разрядная: COM идёт через отдельный процесс, это учесть на шаге 8.2). Exchange — не определено | выезд 02.11.2026 |
| Excel установлен? | Да, 2016. Открытие `.xlsx` из программы ещё не проверялось | выезд 02.11.2026 |

## Стек, который уже работает на этой машине
| Что | Версия | В каком проекте | Примечание |
|---|---|---|---|
| Python | 3.8.10 x64 | все | Последняя ветка с Win7 |
| GUI | **PyQt5 5.15.10, PyQt5-Qt5 5.15.2, PyQt5-sip 12.13.0** | `digger`, `curator` v2 | На Mac — PyQt5-Qt5 5.15.19 (маркер `sys_platform`), нативно на arm64, Rosetta не нужна |
| GUI (другой вариант) | PySide2 5.15.2.1 | `matcher` | Тоже работает, но нет wheel для macOS arm64 cp38: на Mac окно не запустить. Для Atlas **не берём** |
| Сборка | **PyInstaller 6.22.3, onedir, без UPX, `console=False`** | `curator` | CI: `windows-2022` + GitHub Actions. VC++ runtime ставить не нужно. UCRT из сборки **исключён** |
| Сборка (другой вариант) | Embeddable Python 3.8.10 + колёса `cp38 win_amd64` | `digger`, `matcher`, `cvision` | Тоже работает; можно собрать и на Mac (`matcher`) |
| SQLite | 3.35.5 (stdlib Python 3.8.10) | `matcher` | Проверен только на **локальном** диске, см. ниже |
| Прочие библиотеки | numpy 1.24.4, Pillow 10.4.0, opencv-headless 4.5.5.64 / contrib 4.10.0.84, onnxruntime 1.11.1 (1.12+ не работает на Win7) | `digger`, `matcher` | Atlas пока нужен только Pillow (если нужен) |
| Разработка на Mac | `uv venv --python 3.8`, `pytest` 8.3.5, `pytest-qt` 4.4.0, `vermin`, `QT_QPA_PLATFORM=offscreen` | `digger`, `curator` | Готовый рецепт для шага 0.2 |

**Решение для Atlas:** PyQt5 5.15.10 + PyInstaller onedir, как в `curator` v2. Этот набор уже запускался на целевой машине,
а окно можно открыть на Mac. Лицензия PyQt5 — GPL v3, Qt — LGPL v3; в поставку кладём `THIRD_PARTY_LICENSES.txt` (как `curator`).

## Уже проверено — не тестировать повторно
- [x] Запуск собранного .exe (PyInstaller onedir, из папки пользователя, без админа) — `curator` §21.3, выезды 25 и 30.10.2026
- [x] Окно PyQt5 5.15.10 на Win7: стиль Fusion + QSS, обе темы, старт ~1 с — `curator/STATUS.md`, выезды 25 и 30.10.2026; `digger`, веха 0.6
- [x] Кириллица в путях программы — при условии, что пути Qt заданы явно, см. проблемы ниже — `digger`, `matcher` D-022/D-029
- [x] Кириллица и пробелы в путях данных на сетевых дисках — `curator` §21.3
- [x] Чтение и запись файлов на сетевых дисках `R:`, `N:` — `curator` §21.3 и выезды
- [x] Остановка посреди обработки файлов, без потери данных и остатков `.part` (диск в отчёте не указан) — `curator/STATUS.md`, выезд 30.10.2026
- [x] Тема с размерами шрифта в пикселях выглядит хорошо (какой шрифт выбран фактически, в отчётах не указано) — `digger` 7.2, `curator/STATUS.md`, выезд 25.10.2026
- [x] Потоки и фоновые воркеры из оконного запуска; `spawn`-процессы — `matcher` пакет 0.1.19, долгий прогон 0.1.22
- [x] Замер памяти через `GetProcessMemoryInfo` (ctypes) — `matcher/docs/TARGET_ENV.md` §5

- [x] **SQLite на сетевом диске, режим `DELETE`** — 120 с, потеряно 0, целостность ok: один ПК (чтение 5 мс, запись 24 мс, медианы), два ПК и три запуска сразу (чтение 40–67 мс, запись 40–52 мс, «занято» 0), два обрыва сети (21 и 72 с, программа дождалась сети) — выезд 02.11.2026
- [x] Запуск `atlas.exe` с сетевого диска через букву, вход, листание — выезд 02.11.2026
- [x] `QImageReader` и qjpeg на фото 3456×5184: L1 112 мс, L2 144 мс, L3 234 мс — `selfcheck`, выезд 02.11.2026
- [x] Запись кэша в `%LOCALAPPDATA%\Atlas\cache`, значки SVG, шрифты Segoe UI и Consolas — `selfcheck`, выезд 02.11.2026
- [x] Отрисовка в `PhotoView` на встроенной графике: GUI-поток свободен, цифры в `PROGRESS.md` (02.11.2026) — выезд 02.11.2026

### Не проверено — проверить в своём шаге
- [ ] **Запуск по UNC на реальной машине.** В `curator` работает только в CI (`\\localhost`); на выездах не подтверждён.
- [ ] **Работа нескольких пользователей с общими файлами.** Одновременный запуск снят с проверки в `curator` (28.09.2026).
- [ ] **COM Outlook и pywin32.** Не использовались нигде (шаг 11 / `report`).
- [ ] **Открытие `.xlsx` в Excel.** `matcher`: проверка ещё ждёт.
- [ ] **Установка и обновление (10.1):** `.bat` и `.vbs` при Kaspersky, ярлык, переход на новую версию — `WIN7_CHECK.md`, раздел 7.

## Известные проблемы и их решения
| Проблема | Решение | Источник |
|---|---|---|
| Из папки с кириллицей Qt не находит плагины: «no Qt platform plugin», аварийный выход с кодом 1073741845 | До `QApplication`: `QCoreApplication.addLibraryPath(<пакет PyQt5>/Qt5/plugins)` | `digger` b8528bd, 8.3e; `matcher` D-022; `curator/.../platform/qt_runtime.py` |
| Из такой же папки `QLibraryInfo.TranslationsPath` даёт «?» вместо букв, кнопки становятся английскими | **Никаких путей из `QLibraryInfo`**; переводы — тоже от пакета PyQt5 | `curator/ARCHITECTURE.md` §26.3 |
| Тесты, создающие окно, падают с тем же кодом | Задавать путь к плагинам в `tests/conftest.py` до первого окна | `digger/docs/PROGRESS.md` 8.3e |
| PyInstaller копирует UCRT со сборочной машины, и на Win7 копии перекрывают системный | Исключить `ucrtbase.dll`, `api-ms-win-*.dll`; проверять в CI | `curator/BUILD.md` |
| Новые сборки DLL импортируют функции Windows 8+ (`WaitOnAddress`, `ProcessPrng`) | `scripts/check_pe_imports.py` — блокирующий шаг CI | `curator/BUILD.md` |
| Лишний вес: `opengl32sw.dll`, Quick/Qml/Network и т. п. | Убрать из сборки (96 → 81 МБ); при удалении проверять импорты: одна из DLL нужна по цепочке | `curator` §26.3, `matcher` D-020 |
| В оконном exe `sys.stderr = None`: запись туда даёт диалог PyInstaller и зависание | Не писать в `stderr` без проверки; логи — в файл | `curator/STATUS.md`, этап 12 |
| Эмодзи и знаки вроде `✓`, `🗑` на Win7 не отображаются | Только SVG-иконки или рисование | `cvision/docs/decisions.md`, `curator/ARCHITECTURE.md` |
| Размеры, заданные числом, ломаются при другом системном шрифте | Шрифт в пикселях (`setPixelSize`), ширину колонок считать от шрифта | `digger` 7.2, `cvision/docs/decisions.md` |
| После обрыва Windows может показать окно «Ошибка при восстановлении подключения R: … Имя локального устройства уже используется», а Проводник — пустую папку. Файлы на месте | Ничего делать не надо: база снова доступна, как только диск вернулся | выезд 02.11.2026 |
| Обрыв сети — рабочая ситуация | Коды временных ошибок Windows и повторы 5/15/30/60/120 с | `curator/src/curator/fs/retry.py` |
| `Z:\X` и `\\srv\share\X` — одна папка под разными именами | Нормализация через `WNetGetUniversalNameW` | `curator/src/curator/fs/locks.py` |
| Путь длиннее 259 символов | Отклонять с понятным сообщением, не обрезать | `curator/TROUBLESHOOTING.md` |
| Загруженный zip заблокирован Windows | «Разблокировать» в свойствах до распаковки | `matcher/docs/WIN7_CHECK.md` |
| CI на Windows: offscreen без шрифтов не рисует текст | `QT_QPA_FONTDIR=C:/Windows/Fonts` | `digger/.github/workflows/ci.yml` |
| Ошибка Qt показывает окно и ждёт «OK», шаг CI зависает | `timeout-minutes` у шагов, запускающих окно | `digger/.github/workflows/ci.yml` |
| Текст для Блокнота Win7 | UTF-8 с BOM и CRLF | `digger/docs/PROGRESS.md` 8.3f |
| CSV для русского Excel | UTF-8 с BOM, разделитель `;` | `cvision/docs/decisions.md` |

## Код и решения для переиспользования
Копируем файлы, а не подключаем зависимость. Имена и импорты меняем под Atlas.

| Что | Откуда | Куда в Atlas |
|---|---|---|
| Сборка под Win7: workflow, spec, проверка импортов | `curator`: `.github/workflows/build-windows.yml`, `packaging/curator.spec`, `scripts/check_pe_imports.py` | `packaging/`, `scripts/`, `.github/workflows/` (шаг 0.5; `build/` в `.gitignore`) |
| Запуск из UNC и кириллической папки в CI (`New-SmbShare`, `--snapshot`) | `curator`: тот же workflow | `.github/workflows/` (шаг 0.5) |
| Проверка без человека: `--snapshot`, отчёт до создания `QApplication` | `curator`: `packaging/qt_smoke_entry.py`, `platform/` | `atlas/selfcheck.py`, `--selfcheck` (шаг 0.5) |
| Подготовка Qt | `curator`: `src/curator/platform/qt_runtime.py` | `core/` (шаг 0.3–0.4) |
| Логирование и сбор ошибок для показа в окне | `curator`: `src/curator/logging_setup.py` | `core/` (шаг 0.3) |
| Повторы при сбоях сети | `curator`: `src/curator/fs/retry.py` | `shared/fs/` |
| Копирование с проверкой хеша, байтовый прогресс | `curator`: `src/curator/fs/safe_copy.py`, `hashing.py` | `shared/fs/` (шаг 6.x) |
| Блокировки файлов (`O_EXCL`), нормализация пути | `curator`: `src/curator/fs/locks.py`. Heartbeat там не вызывается: нужно подключить | `shared/fs/` |
| Тема: токены → QSS, палитра Fusion, иконки | `digger`: `digger/ui/theme/` (адаптация — `curator/.../platform/theme/`) | `core/theme/` (шаг 0.4) |
| Набор проверок для выезда (один запуск → один zip) | `digger`: `tools/win7_pack/` | `build/` (шаг 0.5, по необходимости) |
| Обновление из общей папки | `digger`: `digger/core/updater.py`, `tools/publish_update.py` | Позже, по необходимости |
| Снимки окна для проверки вида | `digger`: `tools/screenshots.py` | `tools/` (шаг 0.4) |
| Работа с Outlook | **нет ни в одном проекте** — писать с нуля | `shared/outlook/` |

### Стиль Digger и макет
**Итог: оставляем цвета и раскладку макета, механизм темы берём из Digger.**

| | Digger | Макет Atlas | Берём |
|---|---|---|---|
| Палитра | Светлая по умолчанию + тёмная, один акцент | Только тёмная, `#0F1115` | **Макет:** фото лучше смотреть на тёмном фоне |
| Смысловые цвета | `success`, `warning`, `danger` | `type2`, `defect`, `remark`, `ok` | **Макет:** цвета описывают предмет работы |
| Хранение | `tokens.py` + `string.Template` | `tokens.json` + `atlas.qss` | **Макет и архитектура** (JSON), подстановка из Digger: в QSS нет своих цветов |
| Размер шрифта | Пиксели: 12/13/15 | 9–10 pt | **Digger:** пиксели (при 96 DPI 9–10 pt ≈ 12–13 px), на машинах вид одинаков |
| Шрифт | Segoe UI, цепочка запасных | Segoe UI, Consolas | Макет + цепочка запасных из `fonts.py` (Consolas на машине отдельно не проверялся) |
| Отступы, скругления | 4/8/12/16/24; 6/10; контрол 30 px | Скругления 7–10 | Шкала Digger, скругления макета |
| Иконки | Lucide SVG, перекраска, `LICENSE` в поставке | — | **Digger** |
| Основа | Fusion + `QPalette` + QSS | — | **Digger:** палитра закрывает то, что не красит QSS |
| Стрелки списков | SVG-файлы в кэше, пути в QSS | — | **Digger** |
