"""Лента миниатюр: рисует только то, что помещается, поэтому число фото в папке на неё не влияет.

Цвета передаёт владелец: shared не зависит от темы и от того, что значат отметки.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QSizePolicy, QWidget

from atlas.shared.viewer.levels import L0, NEIGHBOR

CELL_HEIGHT = 72
CELL_WIDTH_PORTRAIT = 54
CELL_WIDTH_LANDSCAPE = 96
GAP = 6
_RADIUS = 6
_DOT = 10


@dataclass(frozen=True)
class FilmItem:
    path: str
    mark_color: Optional[QColor] = None


def visible_range(current, total, fits):
    """(первый, за последним): текущая по центру, у краёв папки лента упирается и не оставляет пустых мест."""
    fits = min(max(1, fits), total)
    first = min(max(current - fits // 2, 0), total - fits)
    return first, first + fits


class Filmstrip(QWidget):
    clicked = pyqtSignal(int)  # номер фото

    def __init__(self, cache, colors, parent=None):
        """colors: {"border", "active", "empty", "text", "text_bg"} — QColor."""
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(CELL_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self._cache = cache
        self._colors = colors
        self._items = []
        self._current = 0
        self._cell_width = CELL_WIDTH_PORTRAIT
        self._thumbs = {}  # путь → QPixmap под размер ячейки; только видимые
        cache.ready.connect(self._on_ready)

    @property
    def current(self):
        return self._current

    def set_items(self, items):
        self._items = list(items)
        self._current = 0
        self._thumbs = {}
        self.update()

    def set_mark(self, index, color):
        """Новая отметка у фото: точка меняется сразу, без перечитывания папки."""
        self._items[index] = FilmItem(self._items[index].path, color)
        self.update()

    def set_current(self, index):
        """Запросы миниатюр не отправляет: при удержании стрелки чтение нужно текущему фото, см. request_visible."""
        self._current = index
        self.update()

    def set_portrait(self, portrait):
        width = CELL_WIDTH_PORTRAIT if portrait else CELL_WIDTH_LANDSCAPE
        if width != self._cell_width:
            self._cell_width = width
            self._thumbs = {}
            self.request_visible()
            self.update()

    def visible(self):
        fits = (self.width() + GAP) // (self._cell_width + GAP)
        return visible_range(self._current, len(self._items), fits) if self._items else (0, 0)

    def request_visible(self):
        """Запросить миниатюры видимой части. Ближние к текущей — последними: в очереди новые идут первыми."""
        first, last = self.visible()
        paths = {item.path for item in self._items[first:last]}
        self._thumbs = {path: thumb for path, thumb in self._thumbs.items() if path in paths}
        for index in sorted(range(first, last), key=lambda number: -abs(number - self._current)):
            path = self._items[index].path
            if path in self._thumbs:
                continue
            hit = self._cache.get(path, L0, NEIGHBOR, exact=True)
            if hit is not None and hit.level == L0:  # L3 из памяти уменьшать в GUI-потоке незачем: L0 уже в очереди
                self._adopt(path, hit.image)

    def _adopt(self, path, image):
        ratio = self.devicePixelRatioF()
        pixmap = QPixmap.fromImage(image).scaled(
            int(self._cell_width * ratio), int(CELL_HEIGHT * ratio), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        pixmap.setDevicePixelRatio(ratio)
        self._thumbs[path] = pixmap

    def _on_ready(self, path, level, image):
        if level != L0:
            return
        first, last = self.visible()
        if any(item.path == path for item in self._items[first:last]):
            self._adopt(path, image)
            self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.request_visible()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        first, last = self.visible()
        index = first + event.pos().x() // (self._cell_width + GAP)
        inside = event.pos().x() % (self._cell_width + GAP) < self._cell_width
        if inside and first <= index < last:
            self.clicked.emit(index)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        first, last = self.visible()
        for offset, index in enumerate(range(first, last)):
            self._paint_cell(painter, QRectF(offset * (self._cell_width + GAP), 0, self._cell_width, CELL_HEIGHT), index)

    def _paint_cell(self, painter, rect, index):
        colors = self._colors
        item = self._items[index]
        painter.setPen(Qt.NoPen)
        painter.setBrush(colors["empty"])
        painter.drawRoundedRect(rect, _RADIUS, _RADIUS)
        thumb = self._thumbs.get(item.path)
        if thumb is not None:
            ratio = thumb.devicePixelRatioF()
            width, height = thumb.width() / ratio, thumb.height() / ratio
            target = QRectF(rect.center().x() - width / 2, rect.center().y() - height / 2, width, height)
            painter.drawPixmap(target, thumb, QRectF(thumb.rect()))
        text = str(index + 1)
        metrics = painter.fontMetrics()
        back = QRectF(rect.left() + 3, rect.bottom() - metrics.height() - 3, metrics.horizontalAdvance(text) + 6, metrics.height())
        painter.setBrush(colors["text_bg"])
        painter.drawRoundedRect(back, 3, 3)
        painter.setPen(colors["text"])
        painter.drawText(back, Qt.AlignCenter, text)
        if item.mark_color is not None:
            painter.setPen(QPen(colors["text_bg"], 1))
            painter.setBrush(item.mark_color)
            painter.drawEllipse(QRectF(rect.right() - _DOT - 4, rect.top() + 4, _DOT, _DOT))
        painter.setBrush(Qt.NoBrush)
        active = index == self._current
        painter.setPen(QPen(colors["active"] if active else colors["border"], 2))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), _RADIUS, _RADIUS)
