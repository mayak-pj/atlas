"""Слой фигур поверх PhotoView: рисует их и принимает мышь, пока выбран инструмент.

Один слой обслуживает все окна, фигуры берёт по пути фото окна. Без выбранного инструмента мышь не трогает:
окно ведёт себя как раньше (сдвиг, зум). Выбранный инструмент: левая кнопка рисует, Shift+левая или средняя — сдвиг.
"""
from __future__ import annotations

from PyQt5.QtCore import QObject, Qt, pyqtSignal

from atlas.shared.annotate import model
from atlas.shared.annotate.paint import paint_shapes

TOOL_CROP = "crop"
TOOL_ELLIPSE = "ellipse"
TOOL_LABEL = "label"
TOOLS = (TOOL_CROP, TOOL_ELLIPSE, TOOL_LABEL)
MIN_DRAG = 0.01  # меньше этой доли фото по стороне — это клик, а не выделение


class _Mapper:
    """Доли неповёрнутого фото → пиксели окна."""

    def __init__(self, view):
        self._view = view
        self.unit = view.photo_unit

    def point(self, x, y):
        return self._view.photo_to_widget(x, y)


class AnnotationOverlay(QObject):
    tool_changed = pyqtSignal(object)  # инструмент или None

    def __init__(self, store, colors, ask_text=None, parent=None):
        """colors: {"defect", "outline", "crop", "dim"} — QColor. ask_text(view) → текст подписи или None (отмена)."""
        super().__init__(parent)
        self._store = store
        self._colors = colors
        self._ask_text = ask_text
        self._tool = None
        self._views = []
        self._draft = None  # (окно, начало (x, y) в долях фото, текущая фигура)
        store.changed.connect(self._on_changed)

    @property
    def tool(self):
        return self._tool

    @property
    def views(self):
        return list(self._views)

    def attach(self, view):
        if view not in self._views:
            self._views.append(view)
            view.set_overlay(self)

    def set_tool(self, tool):
        if tool not in TOOLS:
            tool = None
        if tool == self._tool:
            return
        self._tool = tool
        self._draft = None
        for view in self._views:
            view.refresh_cursor()
            view.update()
        self.tool_changed.emit(tool)

    # --- для PhotoView --------------------------------------------------------
    def cursor(self):
        if self._tool == TOOL_LABEL:
            return Qt.IBeamCursor
        return Qt.CrossCursor if self._tool else None

    def paint(self, painter, view):
        if view.path is None or not view.is_current_shown:
            return
        shapes = list(self._store.shapes(view.path))
        if self._draft is not None and self._draft[0] is view:
            shapes.append(self._draft[2])
        if shapes:
            paint_shapes(painter, shapes, _Mapper(view), self._colors, clip=view.inner_rect())

    def mouse_press(self, view, event):
        if self._tool is None or not self.owns(event):
            return False
        if view.path is None or not view.is_current_shown:
            return True  # фото ещё грузится: рисовать не на чем, но и сдвигать в этот момент незачем
        x, y = view.widget_to_photo(event.pos())
        if self._tool == TOOL_LABEL:
            self._place_label(view, x, y)
            return True
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            return True
        self._draft = (view, (x, y), self._shape(x, y, x, y))
        return True

    def mouse_move(self, view, event):
        if self._draft is None or self._draft[0] is not view:
            return False
        x, y = view.widget_to_photo(event.pos())
        start = self._draft[1]
        self._draft = (view, start, self._shape(start[0], start[1], x, y))
        view.update()
        return True

    def mouse_release(self, view, event):
        if self._draft is None or self._draft[0] is not view or event.button() != Qt.LeftButton:
            return False
        _, _, shape = self._draft
        self._draft = None
        view.update()
        if not shape.is_tiny(MIN_DRAG):
            self._store.add(view.path, shape)
        return True

    # --- внутреннее -----------------------------------------------------------
    def owns(self, event):
        """Событие мыши принадлежит рисованию: левая кнопка без Shift/Ctrl."""
        return event.button() == Qt.LeftButton and not event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier)

    def _shape(self, x0, y0, x1, y1):
        cls = model.Crop if self._tool == TOOL_CROP else model.Ellipse
        return cls(x0, y0, x1, y1).normalized().clamped()

    def _place_label(self, view, x, y):
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0) or self._ask_text is None:
            return
        text = self._ask_text(view)
        text = (text or "").strip()
        if text:
            self._store.add(view.path, model.Label(x, y, text))

    def _on_changed(self, path):
        for view in self._views:
            if view.path == path:
                view.update()

