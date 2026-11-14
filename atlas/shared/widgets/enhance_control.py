"""«Качество» (12.5): кнопка с барабаном режимов, как «Присвоить ТИП». Режим выбран — улучшение включено.

Что делает режим, виджет не знает: выбранное уходит сигналом `changed(режим или None)`.
Названия, «вес» (сколько времени займёт обработка) и подсказки режимов — `data/enhance_modes.json`.
"""
from __future__ import annotations

from PyQt5.QtCore import QPoint, pyqtSignal
from PyQt5.QtWidgets import QPushButton

from atlas.shared.widgets.icons import set_icon
from atlas.shared.widgets.number_drum import NumberDrum

TEXT_BUTTON = "Качество"
TEXT_DRUM_TITLE = "Режим"
TEXT_OFF = "Выключить"
TIP_BUTTON = ("Мелкие детали и надписи чётче: фото вычисляется заново для видимой части, файл не меняется.\n"
              "Ничего не дорисовывается. Нажмите — выберите режим (в нём указано, сколько времени займёт обработка); "
              "включённый режим работает на любом масштабе")


class EnhanceControl(QPushButton):
    changed = pyqtSignal(object)  # id режима или None

    def __init__(self, modes, default_mode, parent=None):
        super().__init__(TEXT_BUTTON, parent)
        self.setCheckable(True)
        self.setFocusPolicy(0)
        self.setToolTip(TIP_BUTTON)
        set_icon(self, "eye", "text")
        self._ids = [mode["id"] for mode in modes]
        labels = {n: mode["title"] for n, mode in enumerate(modes, 1)}
        hints = {n: "Время: {}".format(mode["weight"]) for n, mode in enumerate(modes, 1)}  # без описаний, только «вес»
        self.drum = NumberDrum(TEXT_DRUM_TITLE, 1, max(1, len(modes)), TEXT_OFF, self, labels=labels, hints=hints)
        self.drum.chosen.connect(self._on_chosen)
        self.drum.cleared.connect(lambda: self.set_active(False, emit=True))
        self._mode = default_mode if default_mode in self._ids else (self._ids[0] if self._ids else None)
        self._on = False  # включено ли улучшение; не isChecked(): клик по кнопке переключает её сам, раньше нашего кода
        self.clicked.connect(lambda _=False: self.open_drum())

    @property
    def mode(self):
        """Выбранный режим, даже если улучшение выключено."""
        return self._mode

    def active_mode(self):
        """Режим, если улучшение включено, иначе None."""
        return self._mode if self._on else None

    def open_drum(self):
        self.setChecked(self._on)  # клик по кнопке уже переключил её, а включает и выключает только барабан
        number = self._ids.index(self._mode) + 1 if self._mode in self._ids else 1
        top = self.mapToGlobal(QPoint(self.width() // 2, 0))
        bottom = self.mapToGlobal(QPoint(self.width() // 2, self.height()))
        self.drum.open_at(top, number, can_clear=self.active_mode() is not None, below_point=bottom)  # вниз, как просили

    def set_mode(self, mode):
        if mode in self._ids:
            self._mode = mode
            self._refresh_text()

    def set_active(self, on, emit=False):
        self._on = bool(on)
        self.setChecked(self._on)
        self._refresh_text()
        if emit:
            self.changed.emit(self.active_mode())

    def _on_chosen(self, number):
        self._mode = self._ids[number - 1]
        self.set_active(True, emit=True)

    def _refresh_text(self):
        title = self.drum.labels.get(self._ids.index(self._mode) + 1, "") if self._mode in self._ids else ""
        self.setText("{}: {}".format(TEXT_BUTTON, title) if self._on and title else TEXT_BUTTON)
