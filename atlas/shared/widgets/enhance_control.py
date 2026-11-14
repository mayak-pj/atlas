"""«Улучшить» (12.5): кнопка вкл/выкл и список режимов с «весом» — сколько времени займёт обработка.

Что делает режим, виджет не знает: выбранное уходит сигналом `changed(режим или None)`.
Названия и вес режимов — `data/enhance_modes.json`.
"""
from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QAction, QActionGroup, QHBoxLayout, QMenu, QPushButton, QToolButton, QWidget

from atlas.shared.widgets.icons import set_icon

TEXT_BUTTON = "Улучшить"
TIP_BUTTON = ("Мелкие детали и надписи при приближении: фото вычисляется заново для видимой части, файл не меняется.\n"
              "Ничего не дорисовывается. Режим — в списке справа")


class EnhanceControl(QWidget):
    changed = pyqtSignal(object)  # id режима или None

    def __init__(self, modes, default_mode, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.button = QPushButton(TEXT_BUTTON)
        self.button.setCheckable(True)
        self.button.setFocusPolicy(0)
        self.button.setToolTip(TIP_BUTTON)
        set_icon(self.button, "eye", "text")
        self.button.clicked.connect(lambda _=False: self._emit())
        layout.addWidget(self.button)
        self.menu_button = QToolButton()
        self.menu_button.setFocusPolicy(0)
        self.menu_button.setToolTip("Режим улучшения: чем сильнее, тем дольше считается")
        self.menu_button.setMinimumWidth(150)
        self.menu_button.setStyleSheet("QToolButton { padding-right: 18px; }")
        self.menu_button.setPopupMode(QToolButton.InstantPopup)
        self.menu = QMenu(self.menu_button)
        self.menu_button.setMenu(self.menu)
        layout.addWidget(self.menu_button)
        self._group = QActionGroup(self)
        self._actions = {}
        for mode in modes:
            action = QAction("{} — {}".format(mode["title"], mode["weight"]), self.menu)
            action.setCheckable(True)
            action.setToolTip(mode.get("tip", ""))
            action.setData(mode["id"])
            self._group.addAction(action)
            self.menu.addAction(action)
            self._actions[mode["id"]] = action
        self._group.triggered.connect(lambda _a: self._on_mode_chosen())
        self.set_mode(default_mode if default_mode in self._actions else next(iter(self._actions), None))

    @property
    def mode(self):
        """Выбранный режим, даже если кнопка выключена."""
        action = self._group.checkedAction()
        return action.data() if action is not None else None

    def active_mode(self):
        """Режим, если улучшение включено, иначе None."""
        return self.mode if self.button.isChecked() else None

    def set_mode(self, mode):
        action = self._actions.get(mode)
        if action is not None:
            action.setChecked(True)
            self.menu_button.setText(action.text().split(" — ")[0])
            self.menu_button.setToolTip(action.toolTip() or self.menu_button.toolTip())

    def set_active(self, on):
        self.button.setChecked(bool(on))

    def _on_mode_chosen(self):
        self.set_mode(self.mode)
        self.button.setChecked(True)  # выбрал режим — значит, хочет видеть результат
        self._emit()

    def _emit(self):
        self.changed.emit(self.active_mode())
