"""Раскладка с переносом по строкам (для тегов)."""
from __future__ import annotations

from PyQt5.QtCore import QPoint, QRect, QSize, Qt
from PyQt5.QtWidgets import QLayout


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=10):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _layout(self, rect, apply):
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, row_height = area.x(), area.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > area.right() + 1 and row_height > 0:
                x = area.x()
                y += row_height + self._spacing
                row_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y() + margins.bottom()
