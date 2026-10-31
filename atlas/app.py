"""Точка входа: конфиг → тема → ядро → функции → вход → главное окно."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from atlas.core.app_context import AppContext
from atlas.core.config import AppPaths, Config, ConfigError
from atlas.core.db import Database
from atlas.core.logging_setup import configure, install_excepthook
from atlas.core.qt_runtime import prepare

log = logging.getLogger("atlas.app")


def build_core(paths):
    """Конфиг, БД, шина, сервисы. Нужен уже созданный QApplication: шина — QObject."""
    from atlas.core.bus import EventBus
    from atlas.core.services import ServiceRegistry

    config = Config.load(paths)
    db_value = config.get("database.path")
    if not db_value:
        raise ConfigError('В настройках нет "database.path"')
    db_path = paths.resolve(db_value)
    # Только для локальной папки: сетевую не создаём, иначе при сбое получим вторую пустую базу
    if not Path(db_value).is_absolute():
        db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path, config.get("database.busy_timeout_ms", 5000))
    ctx = AppContext(config, paths, db, EventBus(), ServiceRegistry())
    from atlas.core.shell import ShellWindow

    ctx.shell = ShellWindow(ctx)  # до запуска функций: им нужны слоты оболочки
    return ctx


def start_features(ctx):
    from atlas.core.registry import FeatureRegistry

    registry = FeatureRegistry(ctx)
    registry.start_all()
    return registry


def build_window(registry):
    """Вкладки из реестра в уже созданное окно оболочки (ctx.shell)."""
    window = registry.ctx.shell
    window.set_tabs(registry.tabs())
    if registry.failures:
        names = ", ".join(failure.id for failure in registry.failures)
        window.show_message("Не запущены функции: {}. Подробности в журнале.".format(names))
    return window


def run_login(ctx, window):
    """True — можно работать. Нет функции login — работаем без пользователя."""
    login = ctx.services.get_optional("login")
    if login is None:
        return True
    return login.run() is not None


def _option(args, name, default=None):
    """Значение после ключа. argparse нельзя: в оконном exe sys.stderr = None, и его сообщения об ошибке падают."""
    if name in args and args.index(name) + 1 < len(args):
        return args[args.index(name) + 1]
    return default


def _run_check_command(args):
    """Код выхода проверки или None, если это обычный запуск. Импорт — только при вызове."""
    if "--selfcheck" in args:
        out = _option(args, "--selfcheck")
        if not out:
            return 2
        from atlas.selfcheck import run

        return run(Path(out))
    if "--dbcheck" in args:
        folder = _option(args, "--dbcheck")
        seconds = _option(args, "--seconds", "60")
        if not folder or not seconds.isdigit():
            return 2
        from atlas.dbcheck import run_check

        report = _option(args, "--report") or AppPaths.discover().root / "reports"
        return run_check(Path(folder), Path(report), int(seconds), _option(args, "--label"))
    return None


def main(argv=None):
    code = _run_check_command(list(argv if argv is not None else sys.argv)[1:])
    if code is not None:
        return code
    from PyQt5.QtWidgets import QApplication, QMessageBox

    paths = AppPaths.discover()
    configure(paths.logs)
    install_excepthook()
    prepare()
    app = QApplication(list(argv if argv is not None else sys.argv))
    from atlas.core.theme import apply_theme

    apply_theme(app)
    try:
        ctx = build_core(paths)
    except (ConfigError, OSError) as exc:
        log.exception("Не удалось запустить программу")
        QMessageBox.critical(None, "Atlas", str(exc))
        return 2
    registry = start_features(ctx)
    app.aboutToQuit.connect(registry.stop_all)
    window = build_window(registry)
    try:
        proceed = run_login(ctx, window)
    except Exception as exc:  # база недоступна и т. п.
        log.exception("Не удалось выполнить вход")
        QMessageBox.critical(None, "Atlas", "Не удалось выполнить вход: {}".format(exc))
        return 2
    if not proceed:
        return 0
    window.show()
    return app.exec_()
