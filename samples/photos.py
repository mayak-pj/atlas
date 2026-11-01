"""Тестовые фото плат: JPEG нужного размера, нарисованный Qt. Шум нужен, чтобы файл весил и декодировался как настоящий."""
from __future__ import annotations

import os
import random

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QFont, QGuiApplication, QImage, QPainter, QPen

WIDTH = 3456
HEIGHT = 5184
JPEG_QUALITY = 95
_NOISE_SIZE = 1024
VARIANTS = {"ssd": "#14532D", "board": "#1F3A5F", "power": "#5B2A1A", "flex": "#7A5A12"}


def ensure_gui():
    """Подписи требуют QGuiApplication. Без него поднимается offscreen: окна не нужны."""
    if QGuiApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        return QGuiApplication(["atlas-samples"])
    return QGuiApplication.instance()


def _noise():
    data = os.urandom(_NOISE_SIZE * _NOISE_SIZE)
    image = QImage(data, _NOISE_SIZE, _NOISE_SIZE, _NOISE_SIZE, QImage.Format_Grayscale8)
    return image.copy()  # copy: QImage не владеет байтами data


def draw_photo(variant, type_number, label, seed, width=WIDTH, height=HEIGHT):
    """QImage платы. Расположение деталей зависит от варианта, у «Типа 2» есть лишний чип, кадр чуть сдвинут."""
    layout = random.Random(variant)
    jitter = random.Random(seed)
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor("#20242B"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    unit = width / 100.0
    painter.translate(jitter.uniform(-1, 1) * unit, jitter.uniform(-1, 1) * unit)
    board = QRectF(8 * unit, 8 * unit, width - 16 * unit, height - 16 * unit)
    painter.setPen(QPen(QColor("#C9B37A"), unit / 3))
    painter.setBrush(QColor(VARIANTS.get(variant, VARIANTS["board"])))
    painter.drawRoundedRect(board, 2 * unit, 2 * unit)
    painter.setPen(QPen(QColor("#C9B37A"), unit / 8))
    for _ in range(60):  # дорожки
        x, y = layout.uniform(board.left(), board.right()), layout.uniform(board.top(), board.bottom())
        painter.drawLine(int(x), int(y), int(x + layout.uniform(-25, 25) * unit), int(y))
    painter.setPen(Qt.NoPen)
    for _ in range(14):  # чипы
        w, h = layout.uniform(5, 18) * unit, layout.uniform(5, 18) * unit
        x, y = layout.uniform(board.left(), board.right() - w), layout.uniform(board.top(), board.bottom() - h)
        painter.setBrush(QColor(layout.choice(["#17191D", "#2B2E34", "#3C3F46"])))
        painter.drawRect(QRectF(x, y, w, h))
    if type_number == 2:  # лишний чип — на него смотрит проверяющий
        painter.setBrush(QColor("#0D0E10"))
        painter.drawRect(QRectF(board.center().x() - 8 * unit, board.center().y() - 8 * unit, 16 * unit, 16 * unit))
    font = QFont("Arial")
    font.setPixelSize(max(8, int(3 * unit)))
    painter.setFont(font)
    painter.setPen(QColor("#E6E8EB"))
    painter.drawText(QRectF(board.left() + 2 * unit, board.bottom() - 6 * unit, board.width(), 5 * unit), Qt.AlignLeft, label)
    painter.resetTransform()
    painter.setOpacity(0.18)
    painter.setCompositionMode(QPainter.CompositionMode_Overlay)
    painter.fillRect(image.rect(), QBrush(_noise()))
    painter.end()
    return image


def save_photo(path, variant, type_number, label, seed, width=WIDTH, height=HEIGHT):
    """Уже существующий файл не трогает. False — Qt не смог записать."""
    if path.exists():
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    return draw_photo(variant, type_number, label, seed, width, height).save(str(path), "JPEG", JPEG_QUALITY)
