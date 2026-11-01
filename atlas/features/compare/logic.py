"""Логика экрана сравнения без Qt: какое фото в каком окне и как окна стоят в сетке."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

MAX_WINDOWS = 4
MAX_CURRENTS = MAX_WINDOWS - 1  # при 2–4 окнах первое — эталон
DEFAULT_HOTKEYS = {"prev": "Left", "next": "Right", "flicker": "Space"}
NEIGHBORS_AHEAD = 2  # по ходу листания; при удержании стрелки чтение успевает за показом (замер --viewbench)
NEIGHBORS_BEHIND = 1


@dataclass(frozen=True)
class PhotoItem:
    id: Optional[int]
    path: str
    mark: Optional[str] = None

    @property
    def name(self):
        return Path(self.path).name


def photo_path(folder_path, rel_path):
    """rel_path хранится через «/», folder_path может быть UNC с кириллицей."""
    return str(Path(folder_path).joinpath(*rel_path.split("/")))


def grid_cells(count, portrait) -> List[Tuple[int, int, int, int]]:
    """(строка, столбец, строк, столбцов) для каждого окна, первое — эталон при count > 1.

    Вертикальные фото — в ряд: так они крупнее. Горизонтальные при 3 окнах: эталон слева на всю высоту, текущие друг под другом.
    """
    if portrait or count <= 2:
        return [(0, column, 1, 1) for column in range(count)]
    if count == 3:
        return [(0, 0, 2, 1), (0, 1, 1, 1), (1, 1, 1, 1)]
    return [(0, 0, 1, 1), (0, 1, 1, 1), (1, 0, 1, 1), (1, 1, 1, 1)]


def mark_token(mark):
    """Токен цвета точки на миниатюре, как в макете; None — отметки нет."""
    if not mark:
        return None
    if mark == "type:1":
        return "ok"
    if mark.startswith("type:"):
        return "type2"
    return {"defect": "defect", "remark": "remark"}.get(mark)


def neighbor_indexes(index, total, direction):
    """Какие фото подготовить, сначала самое важное. direction — знак последнего шага (1 или -1)."""
    ahead = [index + direction * step for step in range(1, NEIGHBORS_AHEAD + 1)]
    behind = [index - direction * step for step in range(1, NEIGHBORS_BEHIND + 1)]
    return [number for number in ahead + behind if 0 <= number < total]


def position_text(index, total):
    return "{} / {}".format(index + 1, total)


class CompareModel:
    """Фото папки, эталон, индексы текущих окон. Окно здесь — номер текущего окна, 0…MAX_CURRENTS-1."""

    def __init__(self):
        self.photos = []
        self.reference = None  # PhotoItem
        self.count = 1
        self.active = 0
        self.direction = 1  # знак последнего шага: что предзагружать
        self._indexes = [0] * MAX_CURRENTS

    @property
    def currents_count(self):
        return max(1, self.count - 1)

    def set_photos(self, photos):
        """Новая папка. Раскладка сохраняется, эталон пока — первое фото папки."""
        self.photos = list(photos)
        self.reference = self.photos[0] if self.photos else None
        self.active = 0
        self.direction = 1
        self._indexes = [0] * MAX_CURRENTS
        self._spread_from(0)

    def set_layout(self, count):
        """Активное окно сохраняет своё фото. Появившиеся окна показывают следующие фото за предыдущим окном."""
        if not 1 <= count <= MAX_WINDOWS:
            raise ValueError("Раскладка {} фото не поддерживается".format(count))
        before = self.currents_count
        self.count = count
        if self.currents_count > before:
            self._spread_from(before - 1)
        self.active = min(self.active, self.currents_count - 1)

    def set_active(self, window):
        if not 0 <= window < self.currents_count:
            raise ValueError("Нет текущего окна {}".format(window))
        self.active = window

    def index(self, window):
        return self._indexes[window]

    def current(self, window):
        """PhotoItem текущего окна или None, если папка пуста."""
        return self.photos[self._indexes[window]] if self.photos else None

    @property
    def active_index(self):
        return self._indexes[self.active]

    def flip(self, step):
        """Листает активное окно, по краям папки останавливается. True — фото сменилось."""
        return self.go(self.active_index + step)

    def go(self, index):
        """Перейти в активном окне к фото с этим номером. True — фото сменилось."""
        if not self.photos:
            return False
        index = min(max(index, 0), len(self.photos) - 1)
        changed = index != self.active_index
        self.direction = 1 if index >= self.active_index else -1
        self._indexes[self.active] = index
        return changed

    def _spread_from(self, window):
        last = max(len(self.photos) - 1, 0)
        for number in range(window + 1, MAX_CURRENTS):
            self._indexes[number] = min(self._indexes[number - 1] + 1, last)
