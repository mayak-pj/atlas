"""Точка входа: конфиг → ядро → функции → окно. Окно временное, оболочка — шаг 0.4."""
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
    return AppContext(config, paths, db, EventBus(), ServiceRegistry())


def start_features(ctx):
    from atlas.core.registry import FeatureRegistry

    registry = FeatureRegistry(ctx)
    registry.start_all()
    return registry


def build_window(registry):
    from PyQt5.QtWidgets import QMainWindow, QTabWidget

    window = QMainWindow()
    window.setWindowTitle("Atlas")
    window.resize(1200, 800)
    tabs = QTabWidget()
    for item in registry.tabs():
        tabs.addTab(item.tab, item.spec.title)
    window.setCentralWidget(tabs)
    if registry.failures:
        names = ", ".join(failure.id for failure in registry.failures)
        window.statusBar().showMessage("Не запущены функции: {}. Подробности в журнале.".format(names))
    return window


def main(argv=None):
    from PyQt5.QtWidgets import QApplication, QMessageBox

    paths = AppPaths.discover()
    configure(paths.logs)
    install_excepthook()
    prepare()
    app = QApplication(list(argv if argv is not None else sys.argv))
    try:
        ctx = build_core(paths)
    except (ConfigError, OSError) as exc:
        log.exception("Не удалось запустить программу")
        QMessageBox.critical(None, "Atlas", str(exc))
        return 2
    registry = start_features(ctx)
    app.aboutToQuit.connect(registry.stop_all)
    window = build_window(registry)
    window.show()
    return app.exec_()
