"""Столбики QPainter: подпись слева, полоса, число справа. Цвета — из темы."""
from __future__ import annotations

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFontMetrics, QPainter
from PyQt5.QtWidgets import QSizePolicy, QWidget

from atlas.core import theme

ROW_H = 26
BAR_H = 14
LABEL_W = 170
NUM_W = 40
GAP = 10
TEXT_EMPTY = "Пока нет данных"


class BarChart(QWidget):
    """rows — [(подпись, число)]; полоса пропорциональна наибольшему."""

    def __init__(self, color="accent", parent=None):
        super().__init__(parent)
        self._color = color
        self._rows = []
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._resize()

    def rows(self):
        return list(self._rows)

    def set_rows(self, rows):
        self._rows = [(str(text), int(value)) for text, value in rows]
        self._resize()
        self.update()

    def _resize(self):
        self.setFixedHeight(max(1, len(self._rows)) * ROW_H)

    def sizeHint(self):
        from PyQt5.QtCore import QSize

        return QSize(300, self.height())

    def paintEvent(self, _event):
        palette = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(self.font())
        metrics = QFontMetrics(self.font())
        if not self._rows:
            painter.setPen(palette.qcolor("muted"))
            painter.drawText(QRectF(0, 0, self.width(), ROW_H), Qt.AlignVCenter | Qt.AlignLeft, TEXT_EMPTY)
            return
        top = max(value for _text, value in self._rows) or 1
        track_x = LABEL_W + GAP
        track_w = max(0, self.width() - track_x - GAP - NUM_W)
        fill = palette.qcolor(self._color)
        for index, (text, value) in enumerate(self._rows):
            y = index * ROW_H
            painter.setPen(palette.qcolor("text"))
            shown = metrics.elidedText(text, Qt.ElideRight, LABEL_W)
            painter.drawText(QRectF(0, y, LABEL_W, ROW_H), Qt.AlignVCenter | Qt.AlignLeft, shown)
            width = max(3.0, track_w * value / top) if value > 0 else 0.0
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(fill))
            painter.drawRoundedRect(QRectF(track_x, y + (ROW_H - BAR_H) / 2, width, BAR_H), 4, 4)
            painter.setPen(palette.qcolor("text_dim"))
            painter.drawText(QRectF(self.width() - NUM_W, y, NUM_W, ROW_H), Qt.AlignVCenter | Qt.AlignRight, str(value))
