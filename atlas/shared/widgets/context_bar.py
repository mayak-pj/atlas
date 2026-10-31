"""Строка контекста: [КК/СТ] › Проект › Устройство › Деталь · путь к папке."""
from __future__ import annotations

from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel

SEPARATOR = "›"  # ›


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
        self._path = QLabel()
        self._path.setObjectName("ContextPath")
        layout.addWidget(self._kind)
        layout.addWidget(self._chain)
        layout.addStretch(1)
        layout.addWidget(self._path)
        self.clear()

    def set_context(self, kind=None, project=None, device=None, part=None, path=None):
        """Пустые части не показываются. kind — «КК» или «СТ»."""
        self._kind.setText(kind or "")
        self._kind.setVisible(bool(kind) and self._show_kind)
        chain = " {} ".format(SEPARATOR).join(p for p in (project, device, part) if p)
        self._chain.setText(chain)
        self._chain.setVisible(bool(chain))
        self._path.setText(str(path) if path else "")
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
