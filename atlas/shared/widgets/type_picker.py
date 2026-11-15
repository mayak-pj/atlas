"""Выбор номера типа (12.13): короткий список под кнопкой «Присвоить ТИП».

Типов обычно 2–4, поэтому окошко маленькое: три строки с номерами сверху вниз, как список режимов «Качества».
Номера по центру, текущий подсвечен цветом типа (у типов 1–20 свои цвета, как точка на миниатюре). Щелчок по строке — выбрать. Больше трёх типов
бывает редко: колесо мыши и стрелки сдвигают список (номера до 99), цифра сразу встаёт на номер и через миг
выбирается (успели вторую — «12»). Enter или пробел — выбрать, Esc или щелчок мимо — закрыть.
Что значит номер, окошко не знает: выбранное уходит сигналом.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication, QFrame, QPushButton, QVBoxLayout

from atlas.shared.type_tones import type_tone

ROWS = 3
ROW_HEIGHT = 34
ROW_FONT_PX = 15
LIST_WIDTH = 96  # узкое окошко: цифра по центру, влезает «Снять тип»
TYPE_DELAY_MS = 650  # пауза после цифры: успеть набрать вторую
WHEEL_STEP = 120


class TypePicker(QFrame):
    """Всплывающий список. chosen(номер) — выбрали; cleared() — «Снять»."""

    chosen = pyqtSignal(int)
    cleared = pyqtSignal()

    def __init__(self, title, minimum=1, maximum=99, clear_text="", parent=None):
        super().__init__(parent, Qt.Popup)
        self.setProperty("role", "panel")
        self.title, self.minimum, self.maximum = title, minimum, maximum
        self.value = minimum
        self._first = minimum  # номер в верхней строке
        self._typed = ""
        self._wheel_rest = 0
        self.setMinimumWidth(LIST_WIDTH)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(TYPE_DELAY_MS)
        self._timer.timeout.connect(self.choose)
        column = QVBoxLayout(self)
        column.setContentsMargins(6, 6, 6, 6)
        column.setSpacing(4)
        self.tiles = []  # строки списка (имя прежнее: так их знают тесты)
        for index in range(ROWS):
            row = QPushButton("")
            row.setCheckable(True)
            row.setFocusPolicy(Qt.NoFocus)
            row.setMinimumHeight(ROW_HEIGHT)
            row.setStyleSheet("QPushButton {{ font-size: {}px; font-weight: 600; padding: 0; }}".format(ROW_FONT_PX))
            row.clicked.connect(lambda _=False, i=index: self._click(i))
            column.addWidget(row)
            self.tiles.append(row)
        self.clear_button = QPushButton(clear_text)
        self.clear_button.setFocusPolicy(Qt.NoFocus)
        self.clear_button.setMinimumHeight(ROW_HEIGHT - 6)
        self.clear_button.clicked.connect(lambda _=False: self._clear())
        column.addWidget(self.clear_button)
        self.clear_button.hide()
        self._refresh()

    def open_at(self, global_point, value=None, can_clear=False, below_point=None):
        """Показать над точкой (обычно — над кнопкой); value — какой номер подсветить. За экран не выходит."""
        self._typed = ""
        self._timer.stop()
        self._first = self.minimum
        self.set_value(value if value is not None else self.minimum)
        self.clear_button.setVisible(bool(can_clear and self.clear_button.text()))
        self.adjustSize()
        x = global_point.x() - self.width() // 2
        y = below_point.y() if below_point is not None else global_point.y() - self.height()
        area = (QApplication.screenAt(global_point) or QApplication.primaryScreen()).availableGeometry()
        if y + self.height() > area.bottom():
            y = global_point.y() - self.height()
        x = max(area.left(), min(x, area.right() - self.width()))
        self.move(x, max(area.top(), y))
        self.show()
        self.setFocus()

    def set_value(self, value):
        self.value = max(self.minimum, min(self.maximum, int(value)))
        if self.value < self._first:  # список сдвигается ровно настолько, чтобы номер был виден
            self._first = self.value
        elif self.value > self._first + ROWS - 1:
            self._first = self.value - ROWS + 1
        self._refresh()

    def _refresh(self):
        for index, row in enumerate(self.tiles):
            number = self._first + index
            row.setVisible(number <= self.maximum)
            row.setText(str(number))
            tone = type_tone(number)
            if row.property("tone") != tone:
                row.setProperty("tone", tone)
            row.setChecked(number == self.value)
            row.style().unpolish(row)
            row.style().polish(row)

    def _click(self, index):
        self.set_value(self._first + index)
        self.choose()

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

    def _step(self, delta):
        self._typed = ""
        self._timer.stop()
        self.set_value(self.value + delta)

    def wheelEvent(self, event):
        self._wheel_rest += event.angleDelta().y()
        steps = int(self._wheel_rest / WHEEL_STEP)
        if steps:
            self._wheel_rest -= steps * WHEEL_STEP
            self._step(-steps)  # колесо на себя — номер больше, как прокрутка списка вниз
        event.accept()

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
            self._step(-1)
        elif key in (Qt.Key_Down, Qt.Key_Right):
            self._step(1)
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.choose()
        elif key == Qt.Key_Escape:
            self._timer.stop()
            self.hide()
        else:
            super().keyPressEvent(event)
