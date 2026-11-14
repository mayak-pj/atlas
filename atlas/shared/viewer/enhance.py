"""Улучшение фото при приближении: резкость мелких элементов и лёгкий контраст. Только из рабочего потока.

Файл и кэш не меняются: улучшается копия видимой части, уже растянутая до размера на экране.
Без numpy и opencv — только QPainter и режимы наложения (high-pass + «жёсткий свет»):
  размытая копия → контрастная «разность» H = 0,5·(фото − размытое) + 0,5 → фото ← «жёсткий свет»(фото, H).
Яркость в целом не меняется, усиливаются только границы: края деталей, надписи, дорожки.
"""
from __future__ import annotations

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QImage, QPainter

MIN_SCALE = 1.25  # пикселей экрана на пиксель фото, с которого улучшаем: меньше — картинка и так чёткая
MAX_PIXELS = 4_000_000  # больше не делаем: окно на весь экран при зуме 12× заняло бы слишком долго
DEFAULT_AMOUNT = 1.0  # 0 — выключено, 1 — обычная сила, до 3
_BLUR_DIVISOR = 3  # размытие: фото уменьшаем в 3 раза и растягиваем (радиус ~3 пикселя фото)


def wants_enhance(scale, amount):
    """Нужно ли улучшать при таком масштабе (пикселей экрана на пиксель фото)."""
    return amount > 0 and scale >= MIN_SCALE


def enhanced_crop(image, source, width, height, amount=DEFAULT_AMOUNT):
    """Часть фото `source` (QRectF в пикселях `image`), растянутая до width×height и улучшенная; None — не вышло.

    Не больше MAX_PIXELS: иначе None, окно рисуется как обычно.
    """
    width, height = int(width), int(height)
    if width < 1 or height < 1 or width * height > MAX_PIXELS or amount <= 0:
        return None
    crop = image.copy(source.toAlignedRect().intersected(image.rect()))
    if crop.isNull():
        return None
    base = crop.convertToFormat(QImage.Format_RGB32)
    base = base.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    small = base.scaled(  # радиус размытия — несколько пикселей самого фото, а не экрана
        max(1, crop.width() // _BLUR_DIVISOR), max(1, crop.height() // _BLUR_DIVISOR), Qt.IgnoreAspectRatio, Qt.SmoothTransformation
    )
    blurred = small.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    blurred.invertPixels()  # 255 − размытое
    high = QImage(width, height, QImage.Format_RGB32)
    high.fill(0)
    painter = QPainter(high)
    painter.setCompositionMode(QPainter.CompositionMode_Plus)
    painter.setOpacity(0.5)
    painter.drawImage(0, 0, base)
    painter.drawImage(0, 0, blurred)  # 0,5·фото + 0,5·(255 − размытое) = 0,5·(фото − размытое) + 127,5
    painter.end()
    result = QImage(base)
    result.detach()
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode_HardLight)
    for _ in range(max(1, int(round(amount)))):
        painter.drawImage(0, 0, high)
    painter.end()
    return result
