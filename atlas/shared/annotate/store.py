"""Фигуры всех фото в памяти: путь фото → история. Хранение на диске и в базе — шаг 4.2."""
from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal

from atlas.shared.annotate.model import History

MAX_PHOTOS = 300  # забытых фото с фигурами; самые давние уходят первыми


class AnnotationStore(QObject):
    changed = pyqtSignal(str)  # путь фото, у которого изменились фигуры

    def __init__(self, parent=None):
        super().__init__(parent)
        self._histories = {}

    def shapes(self, path):
        history = self._histories.get(str(path))
        return history.shapes if history is not None else ()

    def crop(self, path):
        history = self._histories.get(str(path))
        return history.crop() if history is not None else None

    def can_undo(self, path):
        history = self._histories.get(str(path))
        return history is not None and history.can_undo

    def can_redo(self, path):
        history = self._histories.get(str(path))
        return history is not None and history.can_redo

    def add(self, path, shape):
        path = str(path)
        history = self._histories.pop(path, None) or History()
        self._histories[path] = history  # последний изменённый — в конце
        history.add(shape)
        while len(self._histories) > MAX_PHOTOS:
            del self._histories[next(iter(self._histories))]
        self.changed.emit(path)

    def undo(self, path):
        return self._step(path, "undo")

    def redo(self, path):
        return self._step(path, "redo")

    def clear(self, path):
        history = self._histories.get(str(path))
        if history is not None and history.shapes:
            history.clear()
            self.changed.emit(str(path))

    def _step(self, path, action):
        history = self._histories.get(str(path))
        if history is None or not getattr(history, action)():
            return False
        self.changed.emit(str(path))
        return True
