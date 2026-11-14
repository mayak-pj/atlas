"""«Качество» (12.5): кнопка со списком режимов. Режим выбран — улучшение включено.

Список — маленькое окно под кнопкой: строка на режим («значок уровня · библиотека · время»), выбор щелчком,
«Выключить» — убрать улучшение; стрелки, Enter и Esc тоже работают. Описаний нет, только «вес» — сколько займёт обработка.
Что делает режим, виджет не знает: выбранное уходит сигналом `changed(режим или None)`.
Названия, значки и время режимов — `data/enhance_modes.json`.
"""
from __future__ import annotations

from PyQt5.QtCore import QPoint, Qt, pyqtSignal
from PyQt5.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from atlas.shared.widgets.icons import set_icon

TEXT_BUTTON = "Качество"
TEXT_OFF = "Выключить"
TIP_BUTTON = ("Мелкие детали и надписи чётче: фото вычисляется заново для видимой части, файл не меняется.\n"
              "Ничего не дорисовывается. Нажмите — выберите режим; включённый работает на любом масштабе")
DEFAULT_ICON = "signal-medium"
ROW_HEIGHT = 36
ROW_FONT_PX = 14
TIME_FONT_PX = 12


class _Row(QPushButton):
    """Одна строка списка: значок и название слева, время справа."""

    def __init__(self, title, icon_name, weight):
        super().__init__(title)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMinimumHeight(ROW_HEIGHT)
        self.setStyleSheet("QPushButton {{ text-align: left; font-size: {}px; padding-left: 10px; }}".format(ROW_FONT_PX))
        if icon_name:
            set_icon(self, icon_name, "text", size=18)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 12, 0)
        layout.addStretch(1)
        if weight:
            label = QLabel(weight)
            label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            label.setStyleSheet("font-size: {}px; background: transparent;".format(TIME_FONT_PX))
            label.setProperty("role", "dim")
            layout.addWidget(label)


class _ModeList(QFrame):
    chosen = pyqtSignal(int)  # номер строки с нуля
    cleared = pyqtSignal()

    def __init__(self, modes, parent):
        super().__init__(parent, Qt.Popup)
        self.setProperty("role", "panel")
        column = QVBoxLayout(self)
        column.setContentsMargins(6, 6, 6, 6)
        column.setSpacing(4)
        self.rows = []
        for number, mode in enumerate(modes):
            row = _Row(mode["title"], mode.get("icon", DEFAULT_ICON), mode.get("weight", ""))
            row.clicked.connect(lambda _=False, n=number: self._pick(n))
            column.addWidget(row)
            self.rows.append(row)
        self.off_row = QPushButton(TEXT_OFF)
        self.off_row.setFocusPolicy(Qt.NoFocus)
        self.off_row.setMinimumHeight(ROW_HEIGHT - 6)
        self.off_row.clicked.connect(lambda _=False: self._off())
        column.addWidget(self.off_row)
        self.current = 0

    def open_at(self, top, bottom, number, can_clear):
        self.current = number
        self._mark()
        self.off_row.setVisible(can_clear)
        self.adjustSize()
        area = (QApplication.screenAt(bottom) or QApplication.primaryScreen()).availableGeometry()
        y = bottom.y()
        if y + self.height() > area.bottom():  # снизу не помещается — над кнопкой
            y = top.y() - self.height()
        x = max(area.left(), min(bottom.x() - self.width() // 2, area.right() - self.width()))
        self.move(x, max(area.top(), y))
        self.show()
        self.setFocus()

    def _mark(self):
        for n, row in enumerate(self.rows):
            row.setChecked(n == self.current)

    def _pick(self, number):
        self.hide()
        self.chosen.emit(number)

    def _off(self):
        self.hide()
        self.cleared.emit()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Up, Qt.Key_Left):
            self.current = max(0, self.current - 1)
            self._mark()
        elif key in (Qt.Key_Down, Qt.Key_Right):
            self.current = min(len(self.rows) - 1, self.current + 1)
            self._mark()
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self._pick(self.current)
        elif key == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)


class EnhanceControl(QPushButton):
    changed = pyqtSignal(object)  # id режима или None

    def __init__(self, modes, default_mode, parent=None):
        super().__init__(TEXT_BUTTON, parent)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setToolTip(TIP_BUTTON)
        self._ids = [mode["id"] for mode in modes]
        self._titles = {mode["id"]: mode["title"] for mode in modes}
        self._icons = {mode["id"]: mode.get("icon", DEFAULT_ICON) for mode in modes}
        self.drum = _ModeList(modes, self)  # имя прежнее: так его знают тесты и экран
        self.drum.chosen.connect(self._on_chosen)
        self.drum.cleared.connect(lambda: self.set_active(False, emit=True))
        self._mode = default_mode if default_mode in self._ids else (self._ids[0] if self._ids else None)
        self._on = False  # включено ли улучшение; не isChecked(): клик по кнопке переключает её сам, раньше нашего кода
        self.clicked.connect(lambda _=False: self.open_drum())
        self._refresh()

    @property
    def mode(self):
        """Выбранный режим, даже если улучшение выключено."""
        return self._mode

    def active_mode(self):
        """Режим, если улучшение включено, иначе None."""
        return self._mode if self._on else None

    def open_drum(self):
        self.setChecked(self._on)  # клик по кнопке уже переключил её, а включает и выключает только список
        number = self._ids.index(self._mode) if self._mode in self._ids else 0
        top = self.mapToGlobal(QPoint(self.width() // 2, 0))
        bottom = self.mapToGlobal(QPoint(self.width() // 2, self.height()))
        self.drum.open_at(top, bottom, number, can_clear=self._on)

    def set_mode(self, mode):
        if mode in self._ids:
            self._mode = mode
            self._refresh()

    def set_active(self, on, emit=False):
        self._on = bool(on)
        self.setChecked(self._on)
        self._refresh()
        if emit:
            self.changed.emit(self.active_mode())

    def _on_chosen(self, number):
        self._mode = self._ids[number]
        self.set_active(True, emit=True)

    def _refresh(self):
        shown = self._on and self._mode in self._ids
        self.setText("{}: {}".format(TEXT_BUTTON, self._titles[self._mode]) if shown else TEXT_BUTTON)
        set_icon(self, self._icons[self._mode] if shown else "eye", "text")
