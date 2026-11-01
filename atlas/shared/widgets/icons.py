"""Значки кнопок: векторный набор Lucide (лицензия ISC, файл `icons/LICENSE.txt`), перекрашивается под тему.

    button.setIcon(icon("search"))                                  # цвет text_dim, выключенная — disabled
    button.setIcon(icon("triangle-alert", on="defect"))            # у нажатой («включённой») кнопки цвет defect

Цвета — только имена токенов темы. В файлах набора линии нарисованы цветом `currentColor`: при загрузке он заменяется.
"""
from __future__ import annotations

from pathlib import Path

ICON_DIR = Path(__file__).resolve().parent / "icons"
DEFAULT_SIZE = 16
SCALE = 2  # запас точек для экранов с масштабом

_cache = {}


def names():
    return sorted(path.stem for path in ICON_DIR.glob("*.svg"))


def svg_text(name, color):
    """Текст значка с подставленным цветом (#RRGGBB). Нет такого значка — KeyError."""
    path = ICON_DIR / (name + ".svg")
    if not path.is_file():
        raise KeyError("нет значка: {}".format(name))
    return path.read_text(encoding="utf-8").replace("currentColor", color)


def pixmap(name, color, size=DEFAULT_SIZE):
    from PyQt5.QtCore import QByteArray, QRectF, Qt
    from PyQt5.QtGui import QPainter, QPixmap
    from PyQt5.QtSvg import QSvgRenderer

    side = size * SCALE
    result = QPixmap(side, side)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    QSvgRenderer(QByteArray(svg_text(name, color).encode("utf-8"))).render(painter, QRectF(0, 0, side, side))
    painter.end()
    result.setDevicePixelRatio(SCALE)
    return result


def icon(name, color="text_dim", on=None, size=DEFAULT_SIZE):
    """QIcon темы. color — токен обычного вида, on — токен для включённой кнопки (по умолчанию тот же)."""
    from PyQt5.QtGui import QIcon

    from atlas.core import theme

    colors = theme.current()
    normal, disabled = colors.color(color), colors.color("disabled")
    active = colors.color(on) if on else normal
    key = (name, normal, active, disabled, size)
    if key not in _cache:
        result = QIcon()
        result.addPixmap(pixmap(name, normal, size), QIcon.Normal, QIcon.Off)
        result.addPixmap(pixmap(name, active, size), QIcon.Normal, QIcon.On)
        result.addPixmap(pixmap(name, disabled, size), QIcon.Disabled, QIcon.Off)
        result.addPixmap(pixmap(name, disabled, size), QIcon.Disabled, QIcon.On)
        _cache[key] = result
    return _cache[key]


def set_icon(button, name, color="text_dim", on=None, size=DEFAULT_SIZE):
    """Значок на кнопку; размер значка фиксирован, чтобы подпись не прыгала."""
    from PyQt5.QtCore import QSize

    button.setIcon(icon(name, color, on, size))
    button.setIconSize(QSize(size, size))
    return button
