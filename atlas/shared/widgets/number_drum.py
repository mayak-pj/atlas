"""Барабан номера (14.11.2026): маленькое всплывающее окошко под одну цифру — «Присвоить ТИП».

Колесо мыши и стрелки листают номера от 1; нажатая цифра сразу встаёт на барабан и через миг выбирается
(успели нажать вторую — «12»); Enter, пробел или щелчок по середине — выбрать; Esc или щелчок мимо — закрыть.
Цвета — из темы; что значит номер, барабан не знает: выбранное уходит сигналом.
"""
from __future__ import annotations

from PyQt5.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import QFrame, QPushButton, QVBoxLayout, QWidget

from atlas.core import theme

ROW_HEIGHT = 34
ROWS = 5  # видно: два выше, выбранный, два ниже
DRUM_WIDTH = 96
TYPE_DELAY_MS = 650  # пауза после цифры: успеть набрать вторую
WHEEL_STEP = 120


class _Wheel(QWidget):
    """Сам барабан: рисует номера, листается колесом."""

    picked = pyqtSignal()

    def __init__(self, drum):
        super().__init__(drum)
        self.drum = drum
        self._wheel_rest = 0
        self.setFixedSize(DRUM_WIDTH, ROW_HEIGHT * ROWS)
        self.setCursor(Qt.PointingHandCursor)

    def wheelEvent(self, event):
        self._wheel_rest += event.angleDelta().y()
        steps = int(self._wheel_rest / WHEEL_STEP)
        if steps:
            self._wheel_rest -= steps * WHEEL_STEP
            self.drum.set_value(self.drum.value - steps)  # колесо на себя — номер больше, как прокрутка списка вниз
        event.accept()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        row = int(event.pos().y() // ROW_HEIGHT) - ROWS // 2
        if row == 0:
            self.picked.emit()
        else:
            self.drum.set_value(self.drum.value + row)

    def paintEvent(self, event):
        tokens = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        middle = QRectF(4, ROW_HEIGHT * (ROWS // 2), self.width() - 8, ROW_HEIGHT)
        painter.setPen(Qt.NoPen)
        painter.setBrush(tokens.qcolor("accent_soft"))
        painter.drawRoundedRect(middle, 7, 7)
        font = QFont(self.font())
        for offset in range(-(ROWS // 2), ROWS // 2 + 1):
            number = self.drum.value + offset
            if not self.drum.minimum <= number <= self.drum.maximum:
                continue
            rect = QRectF(0, ROW_HEIGHT * (offset + ROWS // 2), self.width(), ROW_HEIGHT)
            font.setBold(offset == 0)
            font.setPointSizeF(max(8.0, (self.font().pointSizeF() if self.font().pointSizeF() > 0 else 10.0)
                                   * (1.6 if offset == 0 else 1.15 - 0.15 * abs(offset))))
            painter.setFont(font)
            color = QColor(tokens.qcolor("text"))
            color.setAlphaF(1.0 if offset == 0 else 0.55 - 0.2 * (abs(offset) - 1))
            painter.setPen(color)
            painter.drawText(rect, Qt.AlignCenter, str(number))


class NumberDrum(QFrame):
    """Всплывающий барабан. chosen(номер) — выбрали; cleared() — «Снять»."""

    chosen = pyqtSignal(int)
    cleared = pyqtSignal()

    def __init__(self, title, minimum=1, maximum=99, clear_text="", parent=None):
        super().__init__(parent, Qt.Popup)
        self.setProperty("role", "panel")
        self.title, self.minimum, self.maximum = title, minimum, maximum
        self.value = minimum
        self._typed = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(TYPE_DELAY_MS)
        self._timer.timeout.connect(self.choose)
        column = QVBoxLayout(self)
        column.setContentsMargins(8, 8, 8, 8)
        column.setSpacing(6)
        self.wheel = _Wheel(self)
        self.wheel.picked.connect(self.choose)
        column.addWidget(self.wheel, 0, Qt.AlignHCenter)
        self.ok_button = QPushButton("")
        self.ok_button.setProperty("role", "primary")
        self.ok_button.setFocusPolicy(Qt.NoFocus)
        self.ok_button.clicked.connect(lambda _=False: self.choose())
        column.addWidget(self.ok_button)
        self.clear_button = QPushButton(clear_text)
        self.clear_button.setFocusPolicy(Qt.NoFocus)
        self.clear_button.clicked.connect(lambda _=False: self._clear())
        column.addWidget(self.clear_button)
        self.clear_button.hide()
        self._refresh()

    def open_at(self, global_point, value=None, can_clear=False):
        """Показать над точкой (обычно — над кнопкой); value — с какого номера начать."""
        self._typed = ""
        self._timer.stop()
        self.set_value(value if value is not None else self.minimum)
        self.clear_button.setVisible(bool(can_clear and self.clear_button.text()))
        self.adjustSize()
        self.move(global_point.x() - self.width() // 2, global_point.y() - self.height())
        self.show()
        self.setFocus()

    def set_value(self, value):
        self.value = max(self.minimum, min(self.maximum, int(value)))
        self._refresh()

    def _refresh(self):
        self.ok_button.setText("{} {}".format(self.title, self.value))
        self.wheel.update()

    def choose(self):
        self._timer.stop()
        self._typed = ""
        value = self.value
        self.hide()
        self.chosen.emit(value)

    def _clear(self):
        self._timer.stop()
        self.hide()
        self.cleared.emit()

    def keyPressEvent(self, event):
        key = event.key()
        if Qt.Key_0 <= key <= Qt.Key_9:
            typed = self._typed + chr(key)
            if int(typed) > self.maximum or not int(typed):
                typed = chr(key)  # «0» или слишком большое: набор заново
            if int(typed) >= self.minimum:
                self._typed = typed
                self.set_value(int(typed))
                self._timer.start()  # через миг выберется; вторая цифра успевает — «12»
        elif key in (Qt.Key_Up, Qt.Key_Left):
            self._typed = ""
            self._timer.stop()
            self.set_value(self.value - 1)
        elif key in (Qt.Key_Down, Qt.Key_Right):
            self._typed = ""
            self._timer.stop()
            self.set_value(self.value + 1)
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.choose()
        elif key == Qt.Key_Escape:
            self._timer.stop()
            self.hide()
        else:
            super().keyPressEvent(event)
