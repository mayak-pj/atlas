"""Знак ATLAS из макета (скруглённый квадрат с буквой A), рисуется кодом."""
from __future__ import annotations

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QWidget

from atlas.core import theme


class LogoMark(QWidget):
    def __init__(self, size=44, parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)

    def sizeHint(self):
        return QSize(self._size, self._size)

    def paintEvent(self, event):
        th = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        scale = self._size / 44.0
        painter.scale(scale, scale)
        painter.setPen(QPen(th.qcolor("accent"), 2))
        painter.setBrush(th.qcolor("accent_soft"))
        painter.drawRoundedRect(QRectF(2, 2, 40, 40), 10, 10)
        pen = QPen(th.qcolor("text"), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        path = QPainterPath(QPointF(12, 31))
        path.lineTo(22, 11)
        path.lineTo(32, 31)
        painter.drawPath(path)
        painter.drawLine(QPointF(16, 24), QPointF(28, 24))
