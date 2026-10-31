"""NameTag: «таблетка» с цветным кружком инициалов и фамилией. Рисуется вручную (без эмодзи и шрифтовых значков)."""
from __future__ import annotations

from PyQt5.QtCore import QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QFontMetrics, QPainter, QPen
from PyQt5.QtWidgets import QAbstractButton, QSizePolicy

from atlas.core import theme


def initials_of(name):
    """«Смирнова» → «СМ»; пустое имя → «?»."""
    letters = [ch for ch in name if ch.isalpha()]
    return "".join(letters[:2]).upper() or "?"


class NameTag(QAbstractButton):
    """compact=True — для верхней полосы (ниже, без выбора); иначе — крупный тег выбора на входе."""

    def __init__(self, name, color="#7DB4FF", compact=False, parent=None):
        super().__init__(parent)
        self._name = name
        self._color = color
        self._compact = compact
        self.setCheckable(not compact)
        if compact:
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.setFocusPolicy(Qt.NoFocus)
        else:
            self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setText(name)

    @property
    def name(self):
        return self._name

    def _metrics(self):
        font = self.font()
        font.setWeight(63)  # DemiBold
        font.setPixelSize(13 if self._compact else 14)
        return font, self._height(), 22 if self._compact else 30

    def _height(self):
        return 32 if self._compact else 44

    def sizeHint(self):
        font, height, avatar = self._metrics()
        width = QFontMetrics(font).horizontalAdvance(self._name)
        pad = 4 if self._compact else 6
        return QSize(pad + avatar + 8 + width + 14, height)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        th = theme.current()
        font, height, avatar = self._metrics()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        selected = self.isChecked()
        if self._compact:
            fill, border = th.qcolor("tag"), th.qcolor("border_strong")
        elif selected:
            fill, border = th.qcolor("accent_soft"), th.qcolor("accent")
        else:
            fill = th.qcolor("tag")
            border = th.qcolor("accent") if self.underMouse() else th.qcolor("border_strong")
        if selected and not self._compact:  # «ореол» выбранного
            halo = QColor(th.qcolor("accent"))
            halo.setAlpha(64)
            painter.setPen(QPen(halo, 3))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-0.5, -0.5, 0.5, 0.5), rect.height() / 2, rect.height() / 2)
        painter.setPen(QPen(border, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        pad = 4 if self._compact else 6
        circle = QRectF(pad + 1, (self.height() - avatar) / 2, avatar, avatar)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self._color))
        painter.drawEllipse(circle)
        small = self.font()
        small.setPixelSize(10 if self._compact else 13)
        small.setBold(True)
        painter.setFont(small)
        painter.setPen(th.qcolor("bg"))
        painter.drawText(circle, Qt.AlignCenter, initials_of(self._name))
        painter.setFont(font)
        painter.setPen(th.qcolor("text"))
        text = QRectF(circle.right() + 8, 0, self.width() - circle.right() - 12, self.height())
        painter.drawText(text, Qt.AlignVCenter | Qt.AlignLeft, self._name)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)
