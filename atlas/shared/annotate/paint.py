"""Рисование фигур. Одна функция и для экрана, и для будущего сохранения фото с обводкой (4.2): отличается только `mapper`.

mapper: `point(x, y)` → QPointF (доли неповёрнутого фото → пиксели) и `unit` — сколько пикселей в меньшей стороне фото на этом
рисунке. Толщина линий и размер подписи — доли `unit`, поэтому на экране при зуме и на сохранённом снимке выглядят одинаково.
"""
from __future__ import annotations

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QBrush, QFont, QFontMetricsF, QPainterPath, QPen

from atlas.shared.annotate.model import Crop, Ellipse, Label

LINE_WIDTH = 0.0045  # толщина обводки, доля меньшей стороны фото
LINE_MIN_PX = 2.0
LABEL_SIZE = 0.05  # высота букв подписи, доля меньшей стороны фото
LABEL_MIN_PX = 12.0
LABEL_OUTLINE = 0.18  # толщина тёмной обводки текста, доля размера шрифта
CROP_LINE_PX = 2.0
CROP_DASH = (5.0, 4.0)


def rect_of(shape, mapper):
    a = mapper.point(shape.x0, shape.y0)
    b = mapper.point(shape.x1, shape.y1)
    return QRectF(a, b).normalized()


def label_font(mapper):
    font = QFont()
    font.setBold(True)
    font.setPixelSize(max(1, round(max(LABEL_MIN_PX, LABEL_SIZE * mapper.unit))))
    return font


def label_path(label, mapper):
    """Контур текста подписи; левый верхний угол букв — в точке подписи."""
    font = label_font(mapper)
    point = mapper.point(label.x, label.y)
    path = QPainterPath()
    path.addText(QPointF(point.x(), point.y() + QFontMetricsF(font).ascent()), font, label.text)
    return path


def paint_shapes(painter, shapes, mapper, colors, clip=None):
    """colors: {"defect": обводка и текст, "outline": тёмная обводка текста, "crop": рамка ножниц, "dim": затемнение вне ножниц}."""
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    if clip is not None:
        painter.setClipRect(clip)
    for shape in shapes:
        if isinstance(shape, Crop):
            _paint_crop(painter, shape, mapper, colors, clip)
        elif isinstance(shape, Ellipse):
            width = max(LINE_MIN_PX, LINE_WIDTH * mapper.unit)
            painter.setPen(QPen(colors["defect"], width))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(rect_of(shape, mapper))
        elif isinstance(shape, Label) and shape.text:
            path = label_path(shape, mapper)
            outline = max(2.0, label_font(mapper).pixelSize() * LABEL_OUTLINE)
            painter.setPen(QPen(colors["outline"], outline, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(colors["defect"]))
            painter.drawPath(path)
    painter.restore()


def _paint_crop(painter, shape, mapper, colors, clip):
    rect = rect_of(shape, mapper)
    if clip is not None:
        outside = QPainterPath()
        outside.addRect(QRectF(clip))
        inside = QPainterPath()
        inside.addRect(rect)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(colors["dim"]))
        painter.drawPath(outside.subtracted(inside))
    pen = QPen(colors["crop"], CROP_LINE_PX)
    pen.setDashPattern(list(CROP_DASH))
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(rect)
