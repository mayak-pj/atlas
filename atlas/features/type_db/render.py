"""Готовые картинки для базы типов: фото с фигурами и вырезка. Читает файл целиком: только не из GUI-потока."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PyQt5.QtCore import QPointF, QRect, Qt
from PyQt5.QtGui import QImage, QPainter, QTransform

from atlas.shared.annotate.model import Crop
from atlas.shared.annotate.paint import paint_shapes
from atlas.shared.viewer.decode import decode_file
from atlas.shared.viewer.levels import L3

JPEG_QUALITY = 90
DEFAULT_MAX_SIDE = 2600


class RenderError(Exception):
    pass


class _PixelMapper:
    """Доли неповёрнутого фото → пиксели картинки."""

    def __init__(self, width, height):
        self._w = width
        self._h = height
        self.unit = float(min(width, height))

    def point(self, x, y):
        return QPointF(x * self._w, y * self._h)


@dataclass
class Rendered:
    photo: QImage
    crop: Optional[QImage]
    shapes_drawn: int


def render(path, shapes, rotation, colors, max_side=DEFAULT_MAX_SIDE):
    """photo — всё фото с обводками и подписями, crop — область «ножниц» (или None), оба повёрнуты так, как человек видел фото.

    Рамка «ножниц» на картинки не рисуется и фото не затемняет: она только задаёт область вырезки.
    """
    image = decode_file(path, L3).convertToFormat(QImage.Format_RGB32)
    drawn = [shape for shape in shapes if not isinstance(shape, Crop)]
    crop_shape = next((shape for shape in shapes if isinstance(shape, Crop)), None)
    if drawn:
        painter = QPainter(image)
        paint_shapes(painter, drawn, _PixelMapper(image.width(), image.height()), colors)
        painter.end()
    crop = None
    if crop_shape is not None:
        crop = image.copy(_pixel_rect(crop_shape, image.width(), image.height()))
    return Rendered(_finish(image, rotation, max_side), _finish(crop, rotation, max_side) if crop is not None else None, len(drawn))


def save_jpeg(image, path, quality=JPEG_QUALITY):
    if not image.save(str(path), "JPG", quality):
        raise RenderError("Не удалось записать файл: {}".format(path))


def _pixel_rect(shape, width, height):
    left, top = int(round(shape.x0 * width)), int(round(shape.y0 * height))
    right, bottom = int(round(shape.x1 * width)), int(round(shape.y1 * height))
    return QRect(left, top, max(1, right - left), max(1, bottom - top))


def _finish(image, rotation, max_side):
    if rotation % 360:
        image = image.transformed(QTransform().rotate(rotation % 360), Qt.SmoothTransformation)
    if max(image.width(), image.height()) > max_side:
        image = image.scaled(max_side, max_side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return image
