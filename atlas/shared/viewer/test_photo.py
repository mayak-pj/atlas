"""JPEG настоящего размера с шумом для проверок: однотонный файл декодировался бы нереально быстро."""
from __future__ import annotations

import os

from PyQt5.QtGui import QBrush, QColor, QImage, QPainter

WIDTH = 3456
HEIGHT = 5184
_NOISE_SIDE = 1024


def save_noise_photo(path, width=WIDTH, height=HEIGHT):
    """False — Qt не смог записать."""
    noise = QImage(os.urandom(_NOISE_SIDE * _NOISE_SIDE), _NOISE_SIDE, _NOISE_SIDE, _NOISE_SIDE, QImage.Format_Grayscale8).copy()
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor("#1F3A5F"))
    painter = QPainter(image)
    painter.setOpacity(0.2)
    painter.setCompositionMode(QPainter.CompositionMode_Overlay)
    painter.fillRect(image.rect(), QBrush(noise))
    painter.end()
    return image.save(str(path), "JPEG", 95)
