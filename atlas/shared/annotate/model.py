"""Фигуры и история отмены, без Qt.

Все координаты — доли неповёрнутого фото (0…1 по ширине и высоте исходника). Поэтому поворот на 90°, зум, уровень картинки
и размер окна фигуры не меняют: окно само переводит доли в пиксели (`geometry`).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Tuple

from atlas.shared.viewer.view_state import rotated_center

HISTORY_DEPTH = 100  # сколько шагов отмены помним на одно фото


@dataclass(frozen=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    def normalized(self):
        return replace(self, x0=min(self.x0, self.x1), y0=min(self.y0, self.y1), x1=max(self.x0, self.x1), y1=max(self.y0, self.y1))

    def clamped(self):
        def clip(value):
            return min(1.0, max(0.0, value))
        return replace(self, x0=clip(self.x0), y0=clip(self.y0), x1=clip(self.x1), y1=clip(self.y1))

    def is_tiny(self, minimum):
        """Слишком мала, чтобы быть намеренной (случайный клик): в долях фото по каждой стороне."""
        return abs(self.x1 - self.x0) < minimum or abs(self.y1 - self.y0) < minimum


@dataclass(frozen=True)
class Crop(Rect):
    """«Ножницы»: область, которую шаг 4.2 вырежет в базу типов. На фото одна."""


@dataclass(frozen=True)
class Ellipse(Rect):
    """Обводка: эллипс, вписанный в прямоугольник."""


@dataclass(frozen=True)
class Label:
    """Подпись: левый верхний угол текста и сам текст. Размер шрифта — доля фото, задаётся в style."""
    x: float
    y: float
    text: str


def to_screen(x, y, rotation):
    """Точка неповёрнутого фото → доли фото, каким его видно при повороте rotation (градусы по часовой, кратно 90)."""
    return rotated_center(x, y, rotation % 360)


def from_screen(x, y, rotation):
    """Обратное: точка на экране (доли повёрнутого фото) → доли неповёрнутого."""
    return rotated_center(x, y, (-rotation) % 360)


class History:
    """Фигуры одного фото и отмена/повтор. Состояние — неизменяемый кортеж: отмена просто возвращается на прежний."""

    def __init__(self):
        self._states = [()]
        self._pos = 0

    @property
    def shapes(self) -> Tuple:
        return self._states[self._pos]

    @property
    def can_undo(self):
        return self._pos > 0

    @property
    def can_redo(self):
        return self._pos < len(self._states) - 1

    def add(self, shape):
        """Новая фигура; ножницы заменяют прежние. Повтор после этого пропадает."""
        shapes = self.shapes
        if isinstance(shape, Crop):
            shapes = tuple(item for item in shapes if not isinstance(item, Crop))
        self._push(shapes + (shape,))

    def clear(self):
        if self.shapes:
            self._push(())

    def undo(self):
        if not self.can_undo:
            return False
        self._pos -= 1
        return True

    def redo(self):
        if not self.can_redo:
            return False
        self._pos += 1
        return True

    def _push(self, shapes):
        del self._states[self._pos + 1:]
        self._states.append(shapes)
        if len(self._states) > HISTORY_DEPTH:
            del self._states[0]
        self._pos = len(self._states) - 1

    def crop(self):
        for shape in self.shapes:
            if isinstance(shape, Crop):
                return shape
        return None
