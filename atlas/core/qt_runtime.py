"""Подготовка Qt (из curator). Пути — только от пакета PyQt5, никаких QLibraryInfo:
из папки с кириллицей Qt сам не находит плагины."""
from __future__ import annotations

from pathlib import Path


def plugins_dir():
    """Папка плагинов Qt внутри пакета PyQt5 или None."""
    import PyQt5

    path = Path(PyQt5.__file__).resolve().parent / "Qt5" / "plugins"
    return path if (path / "platforms").is_dir() else None


def prepare():
    """Вызывать до создания QApplication."""
    from PyQt5.QtCore import QCoreApplication, Qt

    plugins = plugins_dir()
    if plugins is not None:
        QCoreApplication.addLibraryPath(str(plugins))
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
