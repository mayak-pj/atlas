"""Фото из базы типов большим: колесо — зум, зажатая кнопка мыши — сдвиг, двойной клик — вписать, Esc — закрыть."""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QVBoxLayout

from atlas.shared.viewer.photo_view import PhotoView

WINDOW_SIZE = (1100, 800)


class PhotoWindow(QDialog):
    def __init__(self, cache, path, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(Path(path).name)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        self.resize(*WINDOW_SIZE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = PhotoView(cache, self)
        layout.addWidget(self.view)
        self.view.set_photo(path)
