from __future__ import annotations

import json
import logging

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QHBoxLayout, QInputDialog, QPushButton, QShortcut, QWidget

from atlas.core import theme
from atlas.core.feature import Feature
from atlas.shared.annotate.overlay import TOOL_CROP, TOOL_ELLIPSE, TOOL_LABEL, AnnotationOverlay
from atlas.shared.annotate.store import AnnotationStore

log = logging.getLogger("atlas.annotate_tools")

SLOT_TOOLBAR = "compare.toolbar"
PANEL_KEY = "annotate_tools"
DIM_ALPHA = 140
DEFAULT_KEYS = {"undo": "Ctrl+Z", "redo": "Ctrl+Y"}
TOOL_TEXT = {TOOL_CROP: "Вырезать", TOOL_ELLIPSE: "Обвести", TOOL_LABEL: "Подпись"}
TOOL_TIPS = {
    TOOL_CROP: "Ножницы: выделить область рамкой (она уйдёт в базу типов). Сдвиг при выбранном инструменте — Shift+мышь",
    TOOL_ELLIPSE: "Обвести дефект эллипсом: растяните рамку. Сдвиг при выбранном инструменте — Shift+мышь",
    TOOL_LABEL: "Подпись: щёлкните там, где она должна стоять",
}
LABEL_DIALOG_TITLE = "Подпись"
LABEL_DIALOG_TEXT = "Текст подписи:"
TEXT_NO_PHOTO = "Откройте фото, чтобы разметить его"


def _tool_icon(tool, color, size=16):
    """Значки рисуются кодом, как в макете (ножницы и круг); у подписи — «Аа» текстом самой кнопки."""
    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(QPen(color, 1.6))
    painter.setBrush(Qt.NoBrush)
    if tool == TOOL_ELLIPSE:
        painter.drawEllipse(QRectF(1.5, 3.5, size - 3, size - 7))
    elif tool == TOOL_CROP:
        painter.drawEllipse(QRectF(2, 2, 4, 4))
        painter.drawEllipse(QRectF(2, size - 6, 4, 4))
        painter.drawLine(QPointF(size - 2, 2.5), QPointF(5.5, size - 5.5))
        painter.drawLine(QPointF(size - 2, size - 2.5), QPointF(7.5, 7.5))
    painter.end()
    return QIcon(pixmap)


class AnnotateToolsFeature(Feature):
    """Сервис «annotations»: shapes(path), crop(path) — фигуры фото (доли неповёрнутого фото), store — AnnotationStore.

    Фигуры живут в памяти, пока открыта программа; на диск и в базу их пишет шаг 4.2 («В базу»).
    """

    def on_start(self):
        tokens = theme.current()
        dim = QColor(tokens.qcolor("bg"))
        dim.setAlpha(DIM_ALPHA)
        colors = {
            "defect": tokens.qcolor("defect"),
            "outline": tokens.qcolor("bg"),
            "crop": tokens.qcolor("text"),
            "dim": dim,
        }
        self.store = AnnotationStore()
        self.overlay = AnnotationOverlay(self.store, colors, ask_text=self._ask_text)
        self.overlay.tool_changed.connect(self._on_tool_changed)
        self.widget = QWidget()
        row = QHBoxLayout(self.widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.tool_buttons = {}
        icon_color = tokens.qcolor("text")
        for tool in (TOOL_CROP, TOOL_ELLIPSE, TOOL_LABEL):
            button = QPushButton(TOOL_TEXT[tool])
            button.setCheckable(True)
            button.setFocusPolicy(Qt.NoFocus)  # стрелки и пробел принадлежат экрану сравнения
            button.setToolTip(TOOL_TIPS[tool])
            if tool == TOOL_LABEL:
                button.setText("Аа  " + TOOL_TEXT[tool])
            else:
                button.setIcon(_tool_icon(tool, icon_color))
                button.setIconSize(QSize(16, 16))
            button.clicked.connect(lambda checked, t=tool: self.select_tool(t if checked else None))
            self.tool_buttons[tool] = button
            row.addWidget(button)
        keys = self._keys()
        self.undo_button = self._action_button("Отменить", "Отменить последнее действие на этом фото ({})".format(keys["undo"]), self.undo)
        self.redo_button = self._action_button("Вернуть", "Вернуть отменённое ({})".format(keys["redo"]), self.redo)
        row.addWidget(self.undo_button)
        row.addWidget(self.redo_button)
        self._shortcuts = []
        for name, action in (("undo", self.undo), ("redo", self.redo)):
            shortcut = QShortcut(QKeySequence(keys[name]), self.widget, context=Qt.WindowShortcut)
            shortcut.activated.connect(action)
            self._shortcuts.append(shortcut)
        self.store.changed.connect(lambda _path: self._refresh_buttons())
        if self.ctx.shell is not None:
            self.ctx.shell.add_panel(SLOT_TOOLBAR, self.widget, key=PANEL_KEY)
        self.ctx.services.register("annotations", self)
        self._refresh_buttons()

    def on_stop(self):
        self.ctx.services.unregister("annotations")
        self.overlay.set_tool(None)

    # --- сервис ---------------------------------------------------------------
    def shapes(self, path):
        return self.store.shapes(path)

    def crop(self, path):
        return self.store.crop(path)

    # --- действия -------------------------------------------------------------
    def select_tool(self, tool):
        """tool или None. Включает слой на всех окнах compare (они могли появиться позже старта)."""
        compare = self.ctx.services.get_optional("compare")
        if tool is not None and compare is None:
            tool = None
        if compare is not None:
            for view in compare.views():
                self.overlay.attach(view)
        self.overlay.set_tool(tool)
        self._on_tool_changed(self.overlay.tool)

    def undo(self):
        self._step(self.store.undo)

    def redo(self):
        self._step(self.store.redo)

    def _step(self, action):
        if not self.widget.isVisible():  # сочетание клавиш окна, а вкладка другая
            return
        view = self._active_view()
        if view is not None and view.path is not None:
            action(view.path)

    # --- внутреннее -----------------------------------------------------------
    def _active_view(self):
        compare = self.ctx.services.get_optional("compare")
        return compare.active_view() if compare is not None else None

    def _ask_text(self, view):
        text, ok = QInputDialog.getText(view.window(), LABEL_DIALOG_TITLE, LABEL_DIALOG_TEXT)
        return text if ok else None

    def _on_tool_changed(self, tool):
        for name, button in self.tool_buttons.items():
            button.setChecked(name == tool)

    def _action_button(self, text, tip, action):
        button = QPushButton(text)
        button.setFocusPolicy(Qt.NoFocus)
        button.setToolTip(tip)
        button.clicked.connect(lambda _=False: action())
        return button

    def _refresh_buttons(self):
        view = self._active_view()
        path = view.path if view is not None else None
        self.undo_button.setEnabled(path is not None and self.store.can_undo(path))
        self.redo_button.setEnabled(path is not None and self.store.can_redo(path))

    def _keys(self):
        keys = dict(DEFAULT_KEYS)
        try:
            data = json.loads((self.ctx.paths.data / "hotkeys.json").read_text(encoding="utf-8-sig"))
            keys.update(data.get("annotate", {}))
        except (OSError, ValueError, AttributeError) as exc:
            log.warning("Нет горячих клавиш разметки (%s), взяты стандартные", exc)
        return keys
