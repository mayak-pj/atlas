"""Математика окна просмотра, без Qt.

Состояние — зум (1 = «вписать») и центр в долях фото. Эти числа не зависят ни от размера окна, ни от уровня изображения:
поэтому подмена L1 на L3 ничего не сдвигает, а SyncGroup сможет передавать их между фото разного размера.
Фото здесь такое, каким его видно на экране: у повёрнутого на 90° стороны уже поменяны местами, доли считаются по экрану.
"""
from __future__ import annotations

MIN_ZOOM = 1.0
MAX_ZOOM = 12.0


class ViewState:
    def __init__(self):
        self.view_w = 1.0
        self.view_h = 1.0
        self.photo_w = 1.0  # важны только пропорции
        self.photo_h = 1.0
        self.zoom = MIN_ZOOM
        self.cx = 0.5
        self.cy = 0.5

    def set_view_size(self, width, height):
        self.view_w = float(max(1, width))
        self.view_h = float(max(1, height))
        self._clamp()

    def set_photo_size(self, width, height):
        self.photo_w = float(max(1, width))
        self.photo_h = float(max(1, height))
        self._clamp()

    def set_state(self, zoom, cx, cy):
        self.zoom = min(MAX_ZOOM, max(MIN_ZOOM, zoom))
        self.cx = cx
        self.cy = cy
        self._clamp()

    def state(self):
        return self.zoom, self.cx, self.cy

    def fit(self):
        self.set_state(MIN_ZOOM, 0.5, 0.5)

    def displayed_size(self):
        """Размер всего фото на экране при текущем зуме, в пикселях окна."""
        scale = min(self.view_w / self.photo_w, self.view_h / self.photo_h) * self.zoom
        return self.photo_w * scale, self.photo_h * scale

    def target_rect(self):
        """(x, y, ширина, высота) всего фото в координатах окна."""
        width, height = self.displayed_size()
        return self.view_w / 2 - self.cx * width, self.view_h / 2 - self.cy * height, width, height

    def to_photo(self, x, y):
        """Точка окна → доли фото."""
        left, top, width, height = self.target_rect()
        return (x - left) / width, (y - top) / height

    def zoom_at(self, factor, x, y):
        """Точка фото под (x, y) остаётся на месте, если этому не мешает край фото."""
        px, py = self.to_photo(x, y)
        self.zoom = min(MAX_ZOOM, max(MIN_ZOOM, self.zoom * factor))
        width, height = self.displayed_size()
        self.cx = px - (x - self.view_w / 2) / width
        self.cy = py - (y - self.view_h / 2) / height
        self._clamp()

    def pan_by(self, dx, dy):
        width, height = self.displayed_size()
        self.cx -= dx / width
        self.cy -= dy / height
        self._clamp()

    def _clamp(self):
        width, height = self.displayed_size()
        self.cx = _clamp_axis(self.cx, self.view_w / width)
        self.cy = _clamp_axis(self.cy, self.view_h / height)


def rotated_center(cx, cy, delta):
    """Где окажется точка фото (доли), если фото повернуть на delta градусов по часовой стрелке (кратно 90)."""
    delta %= 360
    if delta == 90:
        return 1.0 - cy, cx
    if delta == 180:
        return 1.0 - cx, 1.0 - cy
    if delta == 270:
        return cy, 1.0 - cx
    return cx, cy


def rotated_size(width, height, rotation):
    """Размер на экране: при 90 и 270 градусах стороны меняются местами."""
    return (height, width) if rotation % 180 else (width, height)


def _clamp_axis(center, visible):
    """visible — какая доля фото помещается в окне. Поместилось всё — по центру, иначе край фото не отходит от края окна."""
    if visible >= 1.0:
        return 0.5
    return min(1.0 - visible / 2, max(visible / 2, center))
