"""Готовые картинки для базы типов: фото с фигурами и вырезка. Читает файл целиком: только не из GUI-потока."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PyQt5.QtCore import QPointF, QRect, Qt
from PyQt5.QtGui import QImage, QPainter, QTransform

from atlas.shared.annotate.model import Crop, to_screen
from atlas.shared.annotate.paint import paint_shapes, rect_of
from atlas.shared.viewer.decode import decode_file
from atlas.shared.viewer.levels import L3

JPEG_QUALITY = 90
DEFAULT_MAX_SIDE = 2600


class RenderError(Exception):
    pass


class _PixelMapper:
    """Доли неповёрнутого фото → пиксели картинки, уже повёрнутой на rotation (как фото стояло на экране)."""

    def __init__(self, width, height, rotation=0):
        self._w = width
        self._h = height
        self._rotation = rotation % 360
        self.unit = float(min(width, height))

    def point(self, x, y):
        sx, sy = to_screen(x, y, self._rotation)
        return QPointF(sx * self._w, sy * self._h)


@dataclass
class Rendered:
    photo: QImage
    crop: Optional[QImage]
    shapes_drawn: int


def render(path, shapes, rotation, colors, max_side=DEFAULT_MAX_SIDE):
    """photo — всё фото с обводками и подписями, crop — область «ножниц» (или None), оба повёрнуты так, как человек видел фото.

    Рамка «ножниц» на картинки не рисуется и фото не затемняет: она только задаёт область вырезки.
    """
    image = _rotated(decode_file(path, L3).convertToFormat(QImage.Format_RGB32), rotation)
    # Сначала поворот, потом фигуры: подпись на экране всегда горизонтальна и стоит в своей точке — так и в файле.
    # Раньше фигуры рисовались на неповёрнутом фото и поворачивались вместе с ним: подпись уходила боком (04.11.2026).
    mapper = _PixelMapper(image.width(), image.height(), rotation)
    drawn = [shape for shape in shapes if not isinstance(shape, Crop)]
    crop_shape = next((shape for shape in shapes if isinstance(shape, Crop)), None)
    if drawn:
        painter = QPainter(image)
        paint_shapes(painter, drawn, mapper, colors)
        painter.end()
    crop = None
    if crop_shape is not None:
        crop = image.copy(rect_of(crop_shape, mapper).toAlignedRect())
    return Rendered(_finish(image, max_side), _finish(crop, max_side) if crop is not None else None, len(drawn))


def save_jpeg(image, path, quality=JPEG_QUALITY):
    if not image.save(str(path), "JPG", quality):
        raise RenderError("Не удалось записать файл: {}".format(path))


def _rotated(image, rotation):
    if rotation % 360:
        return image.transformed(QTransform().rotate(rotation % 360), Qt.SmoothTransformation)
    return image


def _finish(image, max_side):
    if max(image.width(), image.height()) > max_side:
        image = image.scaled(max_side, max_side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return image
