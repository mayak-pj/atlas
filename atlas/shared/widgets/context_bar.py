"""Строка контекста: [A/B] › Проект › Устройство › Деталь · путь к папке."""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy

SEPARATOR = "›"  # ›


class _PathLabel(QLabel):
    """Длинный путь сокращается в середине, полный — в подсказке: строка не должна раздвигать окно."""

    def __init__(self):
        super().__init__()
        self.full_text = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def set_path(self, text):
        self.full_text = text
        self.setToolTip(text)
        self._elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        self.setText(self.fontMetrics().elidedText(self.full_text, Qt.ElideMiddle, self.width()))


class ContextBar(QFrame):
    def __init__(self, show_kind=True, parent=None):
        super().__init__(parent)
        self.setObjectName("ContextBar")
        self._show_kind = show_kind
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 6)
        layout.setSpacing(8)
        self._kind = QLabel()
        self._kind.setObjectName("KindBadge")
        self._chain = QLabel()
        self._chain.setObjectName("ContextCurrent")
        self._path = _PathLabel()
        self._path.setObjectName("ContextPath")
        layout.addWidget(self._kind)
        layout.addWidget(self._chain)
        layout.addWidget(self._path, 1)
        self.clear()

    def set_context(self, kind=None, project=None, device=None, part=None, path=None):
        """Пустые части не показываются. kind — «A» или «B»."""
        self._kind.setText(kind or "")
        self._kind.setVisible(bool(kind) and self._show_kind)
        chain = " {} ".format(SEPARATOR).join(p for p in (project, device, part) if p)
        self._chain.setText(chain)
        self._chain.setVisible(bool(chain))
        self._path.set_path(str(path) if path else "")
        self._path.setVisible(bool(path))
        self.setVisible(bool(kind or chain or path))

    def clear(self):
        self.set_context()

    def set_show_kind(self, value):
        self._show_kind = value
        self._kind.setVisible(value and bool(self._kind.text()))

    @property
    def chain_text(self):
        return self._chain.text()
