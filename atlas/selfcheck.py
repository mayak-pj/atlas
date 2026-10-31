"""Проверка собранной программы без человека: atlas.exe --selfcheck ПАПКА.

Настоящий путь пользователя на настоящем окне: тема → функции → диалог входа (добавить себя, войти) → все вкладки.
Работает на временной копии config/ и data/ со своей базой, рабочую базу не трогает.
В папке остаются selfcheck.txt, снимки и журнал. Код выхода: 0 — всё прошло, 1 — есть ошибки,
3 — некуда писать отчёт, 4 — зависание (например, неожиданное окно с вопросом).
"""
from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

from atlas.core.config import AppPaths
from atlas.core.logging_setup import configure, install_excepthook
from atlas.core.qt_runtime import plugins_dir, prepare
from atlas.core.report import TextReport

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NO_REPORT = 3
EXIT_HUNG = 4
HANG_TIMEOUT_S = 120
STEP_DELAY_MS = 200
TEST_USER = "Проверка"
REQUIRED_IMAGE_FORMATS = ("jpeg", "svg")

log = logging.getLogger("atlas.selfcheck")


class _Check:
    def __init__(self, report, out):
        self.report = report
        self.out = out
        self.failed = False
        self.started = time.monotonic()

    def info(self, text):
        self.report.line(text)

    def result(self, name, ok, detail=""):
        self.failed = self.failed or not ok
        elapsed = time.monotonic() - self.started
        tail = ": {}".format(detail) if detail else ""
        self.report.line("[{:6.2f} с] {} {}{}".format(elapsed, "ОК    " if ok else "ОШИБКА", name, tail))

    def shot(self, widget, name):
        path = self.out / "{}.png".format(name)
        self.result("снимок {}".format(name), widget.grab().save(str(path)))


def _make_work_root(source, work):
    """Копия настроек со своей базой. Кириллица и пробел в пути — как на целевой машине."""
    root = work / "Проверка Атласа"
    root.mkdir(parents=True)
    shutil.copytree(str(source.config), str(root / "config"), ignore=shutil.ignore_patterns("local.json"))
    if source.data.is_dir():
        shutil.copytree(str(source.data), str(root / "data"))
    local = {"database": {"path": "var/selfcheck.sqlite"}}
    (root / "config" / "local.json").write_text(json.dumps(local), encoding="utf-8")
    return AppPaths(root)


def _describe_system(check, paths):
    check.info("Программа: {}".format(sys.executable if getattr(sys, "frozen", False) else "из исходников"))
    check.info("Папка программы: {}".format(paths.root))
    check.info("ОС: {}".format(platform.platform()))
    check.info("Python {} {}. SQLite {}".format(platform.python_version(), platform.architecture()[0], sqlite3.sqlite_version))
    check.info("Плагины Qt: {}".format(plugins_dir()))


def _describe_screen(check, app):
    from PyQt5.QtCore import qVersion

    screen = app.primaryScreen()
    size = screen.size()
    check.info("Qt {}. Экран: {}×{}, DPI {:.0f}, масштаб {}".format(
        qVersion(), size.width(), size.height(), screen.logicalDotsPerInch(), screen.devicePixelRatio()
    ))


def _check_formats(check):
    from PyQt5.QtGui import QImageReader

    formats = {bytes(item).decode("ascii").lower() for item in QImageReader.supportedImageFormats()}
    for name in REQUIRED_IMAGE_FORMATS:
        check.result("формат изображений {}".format(name), name in formats)


def _drive_login(app, check):
    """Нажимает кнопки модального диалога таймерами: exec_() занят своим циклом событий."""
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QPushButton

    def guarded(step):
        def call():
            try:
                step()
            except Exception as exc:
                log.exception("Сбой при проходе диалога входа")
                check.result("диалог входа", False, str(exc))
                modal = app.activeModalWidget()
                if modal is not None:
                    modal.reject()

        return call

    def open_add():
        dialog = app.activeModalWidget()
        check.shot(dialog, "login_empty")
        QTimer.singleShot(STEP_DELAY_MS, guarded(enter_name))
        dialog.findChild(QPushButton, "login_add").click()  # вернётся, когда закроется окно ввода

    def enter_name():
        box = app.activeModalWidget()
        box.setTextValue(TEST_USER)
        QTimer.singleShot(STEP_DELAY_MS, guarded(press_go))
        box.accept()

    def press_go():
        dialog = app.activeModalWidget()
        check.shot(dialog, "login")
        dialog.findChild(QPushButton, "login_go").click()

    QTimer.singleShot(STEP_DELAY_MS, guarded(open_add))


def _walk(check, paths, work):
    from PyQt5.QtWidgets import QApplication

    prepare()
    check.info("Создание QApplication…")  # здесь падает Qt, если не найден плагин платформы
    app = QApplication.instance() or QApplication(["atlas"])
    check.result("QApplication", True)
    _describe_screen(check, app)

    from atlas.app import build_core, build_window, run_login, start_features
    from atlas.core.theme import apply_theme

    theme = apply_theme(app)
    check.result("тема", bool(app.styleSheet()))
    check.info("Шрифты: основной «{}», моноширинный «{}»".format(theme.ui_family, theme.mono_family))
    _check_formats(check)

    ctx = build_core(_make_work_root(paths, work))
    check.result("ядро и база", True, str(ctx.db.path))
    registry = start_features(ctx)
    for failure in registry.failures:
        check.result("функция {}".format(failure.id), False, "{}: {}".format(failure.stage, failure.error))
    check.result("функции запущены", not registry.failures, ", ".join(i.spec.id for i in registry.loaded))
    window = build_window(registry)

    has_login = ctx.services.get_optional("login") is not None
    if has_login:
        _drive_login(app, check)
    check.result("вход", run_login(ctx, window) and (not has_login or ctx.user is not None))

    window.resize(1280, 720)
    window.show()
    app.processEvents()
    if has_login:
        check.result("тег пользователя", bool(window.slots.panels("shell.user")))
    tabs = registry.tabs()
    check.result("вкладки есть", bool(tabs), ", ".join(window.tab_titles()))
    for item in tabs:
        window.select_tab(item.spec.id)
        app.processEvents()
        check.result("вкладка {}".format(item.spec.id), window.current_tab_id() == item.spec.id)
        check.shot(window, "tab_{}".format(item.spec.id))
    window.close()
    registry.stop_all()
    app.processEvents()


def run(out, paths=None):
    """Возвращает код выхода (см. начало файла)."""
    out = Path(out)
    try:
        out.mkdir(parents=True, exist_ok=True)
        report = TextReport(out / "selfcheck.txt")
    except OSError:
        return EXIT_NO_REPORT
    paths = paths or AppPaths.discover()
    configure(out / "logs")
    install_excepthook()
    check = _Check(report, out)

    def on_hang():
        report.line("ИТОГ: ЗАВИСАНИЕ — нет завершения за {} с".format(HANG_TIMEOUT_S))
        os._exit(EXIT_HUNG)

    watchdog = threading.Timer(HANG_TIMEOUT_S, on_hang)
    watchdog.daemon = True
    watchdog.start()
    work = None
    try:
        _describe_system(check, paths)
        work = Path(tempfile.mkdtemp(prefix="work_", dir=str(out)))
        _walk(check, paths, work)
    except Exception:
        log.exception("Проверка прервана")
        check.result("проверка прервана", False, traceback.format_exc())
    finally:
        watchdog.cancel()
        if work is not None:
            shutil.rmtree(str(work), ignore_errors=True)
    report.line("ИТОГ: {}".format("ЕСТЬ ОШИБКИ" if check.failed else "ВСЁ РАБОТАЕТ"))
    return EXIT_FAILED if check.failed else EXIT_OK
