"""Выбор номера типа (12.13): плитки с номерами вместо барабана, «Присвоить ТИП».

Окошко под кнопкой: сетка 4×3 (страница — 12 номеров), текущий номер подсвечен цветом типа, как точка на миниатюре.
Щелчок по плитке — выбрать. Колесо мыши и стрелки листают номер (страница перелистывается сама), цифра сразу встаёт
на плитку и через миг выбирается (успели вторую — «12»), Enter или пробел — выбрать, Esc или щелчок мимо — закрыть.
Что значит номер, окошко не знает: выбранное уходит сигналом. Тот же состав, что был у барабана (`NumberDrum`).
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from atlas.shared.widgets.icons import set_icon

COLUMNS = 4
PAGE_ROWS = 3
PAGE = COLUMNS * PAGE_ROWS
TILE_W = 52
TILE_H = 40
TILE_FONT_PX = 16
TYPE_DELAY_MS = 650  # пауза после цифры: успеть набрать вторую
WHEEL_STEP = 120
TEXT_HINT = "Колесо или цифры — номер, Enter — выбрать"


def tone_of(number):
    """Цвет плитки, как у точки типа на миниатюре: 1 — зелёный, 2 — янтарный, дальше — бирюзовый."""
    return "ok" if number == 1 else "type2" if number == 2 else "type3"


class TypePicker(QFrame):
    """Всплывающие плитки. chosen(номер) — выбрали; cleared() — «Снять»."""

    chosen = pyqtSignal(int)
    cleared = pyqtSignal()

    def __init__(self, title, minimum=1, maximum=99, clear_text="", parent=None):
        super().__init__(parent, Qt.Popup)
        self.setProperty("role", "panel")
        self.title, self.minimum, self.maximum = title, minimum, maximum
        self.value = minimum
        self._page = 0
        self._typed = ""
        self._wheel_rest = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(TYPE_DELAY_MS)
        self._timer.timeout.connect(self.choose)
        column = QVBoxLayout(self)
        column.setContentsMargins(10, 8, 10, 10)
        column.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setProperty("role", "caption")
        head.addWidget(self.title_label)
        head.addStretch(1)
        self.prev_button = self._arrow("chevron-left", -1)
        self.range_label = QLabel("")
        self.range_label.setProperty("role", "mono")
        self.range_label.setAlignment(Qt.AlignCenter)
        self.range_label.setMinimumWidth(56)
        self.next_button = self._arrow("chevron-right", 1)
        head.addWidget(self.prev_button)
        head.addWidget(self.range_label)
        head.addWidget(self.next_button)
        column.addLayout(head)
        grid = QGridLayout()
        grid.setSpacing(6)
        self.tiles = []
        for index in range(PAGE):
            tile = QPushButton("")
            tile.setCheckable(True)
            tile.setFocusPolicy(Qt.NoFocus)
            tile.setFixedSize(TILE_W, TILE_H)
            tile.setStyleSheet("QPushButton {{ font-size: {}px; font-weight: 600; padding: 0; }}".format(TILE_FONT_PX))
            tile.clicked.connect(lambda _=False, i=index: self._click(i))
            grid.addWidget(tile, index // COLUMNS, index % COLUMNS)
            self.tiles.append(tile)
        column.addLayout(grid)
        self.hint_label = QLabel(TEXT_HINT)
        self.hint_label.setProperty("role", "dim")
        self.hint_label.setAlignment(Qt.AlignCenter)
        column.addWidget(self.hint_label)
        self.clear_button = QPushButton(clear_text)
        self.clear_button.setFocusPolicy(Qt.NoFocus)
        self.clear_button.clicked.connect(lambda _=False: self._clear())
        column.addWidget(self.clear_button)
        self.clear_button.hide()
        self._refresh()

    def _arrow(self, icon_name, delta):
        button = QPushButton("")
        set_icon(button, icon_name, "text", size=16)
        button.setFocusPolicy(Qt.NoFocus)
        button.setFixedSize(26, 26)
        button.setStyleSheet("QPushButton { padding: 0; min-width: 26px; }")
        button.clicked.connect(lambda _=False: self._turn(delta))
        return button

    def open_at(self, global_point, value=None, can_clear=False, below_point=None):
        """Показать над точкой (обычно — над кнопкой); value — какой номер подсветить. За экран не выходит."""
        self._typed = ""
        self._timer.stop()
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
        self._page = (self.value - self.minimum) // PAGE
        self._refresh()

    def _first(self):
        return self.minimum + self._page * PAGE

    def _pages(self):
        return (self.maximum - self.minimum) // PAGE + 1

    def _turn(self, delta):
        """Стрелки в заголовке: на страницу вперёд или назад; номер встаёт на то же место страницы."""
        page = max(0, min(self._pages() - 1, self._page + delta))
        if page != self._page:
            offset = (self.value - self.minimum) % PAGE
            self._timer.stop()
            self._typed = ""
            self.set_value(min(self.maximum, self.minimum + page * PAGE + offset))

    def _refresh(self):
        first = self._first()
        last = min(self.maximum, first + PAGE - 1)
        self.range_label.setText("{}–{}".format(first, last))
        self.prev_button.setEnabled(self._page > 0)
        self.next_button.setEnabled(self._page < self._pages() - 1)
        for index, tile in enumerate(self.tiles):
            number = first + index
            tile.setVisible(number <= self.maximum)
            tile.setText(str(number))
            current = number == self.value
            tone = tone_of(number)
            if tile.property("tone") != tone:
                tile.setProperty("tone", tone)
            tile.setChecked(current)
            tile.style().unpolish(tile)
            tile.style().polish(tile)

    def _click(self, index):
        self.set_value(self._first() + index)
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

    def wheelEvent(self, event):
        self._wheel_rest += event.angleDelta().y()
        steps = int(self._wheel_rest / WHEEL_STEP)
        if steps:
            self._wheel_rest -= steps * WHEEL_STEP
            self._timer.stop()
            self._typed = ""
            self.set_value(self.value - steps)  # колесо на себя — номер больше, как прокрутка списка вниз
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
        elif key in (Qt.Key_Left, Qt.Key_Up):
            self._step(-COLUMNS if key == Qt.Key_Up else -1)
        elif key in (Qt.Key_Right, Qt.Key_Down):
            self._step(COLUMNS if key == Qt.Key_Down else 1)
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.choose()
        elif key == Qt.Key_Escape:
            self._timer.stop()
            self.hide()
        else:
            super().keyPressEvent(event)

    def _step(self, delta):
        self._typed = ""
        self._timer.stop()
        self.set_value(self.value + delta)
