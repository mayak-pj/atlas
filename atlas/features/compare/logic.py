"""Логика экрана сравнения без Qt: какое фото в каком окне и как окна стоят в сетке."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

from atlas.core.domain.photo_names import parse_photo_name

log = logging.getLogger("atlas.compare")

MAX_WINDOWS = 4
MAX_CURRENTS = MAX_WINDOWS - 1  # при 2–4 окнах первое — эталон
DEFAULT_MARK_KEYS = {"type:1": "1", "type:2": "2", "type:3": "3", "defect": "D", "remark": "R"}
DEFAULT_HOTKEYS = {
    "prev": "Left", "next": "Right", "flicker": "Space", "rotate_left": "PgUp", "rotate_right": "PgDown",
    "toggle_ui": "H",
    "marks": DEFAULT_MARK_KEYS,
}
ROTATE_STEP = 90
DEFAULT_DEFECT_KINDS = ["Сбит / повреждён элемент", "Размытое фото", "Прислано не то фото"]
NEIGHBORS_AHEAD = 2  # по ходу листания; при удержании стрелки чтение успевает за показом (замер --viewbench)
NEIGHBORS_BEHIND = 1


@dataclass(frozen=True)
class PhotoItem:
    id: Optional[int]
    path: str
    mark: Optional[str] = None
    sn: Optional[str] = None
    defect_kind: Optional[str] = None
    rotation: int = 0  # градусы по часовой стрелке, сохранённые в базе

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


def next_rotation(rotation, delta):
    """Новый поворот, 0–270: четыре поворота в одну сторону возвращают к исходному."""
    return (rotation + delta) % 360


def same_angle(photos, number, pattern=None):
    """Номера всех фото того же ракурса, что и это. Имя не разобрано — ракурс неизвестен, только само фото."""
    parsed = parse_photo_name(photos[number].name, pattern)
    if parsed is None:
        return [number]
    names = (parse_photo_name(photo.name, pattern) for photo in photos)
    return [index for index, other in enumerate(names) if other is not None and other.view == parsed.view]


def turn_angle(photos, number, delta, pattern=None):
    """Весь ракурс получает один новый поворот, даже если раньше фото были повёрнуты по-разному. Меняет список на месте."""
    rotation = next_rotation(photos[number].rotation, delta)
    changed = {}
    for index in same_angle(photos, number, pattern):
        photos[index] = replace(photos[index], rotation=rotation)
        changed[index] = rotation
    return changed


def mark_token(mark):
    """Токен цвета точки на миниатюре, как в макете; None — отметки нет."""
    if not mark:
        return None
    if mark == "type:1":
        return "ok"
    if mark.startswith("type:"):
        return "type2"
    return {"defect": "defect", "remark": "remark"}.get(mark)


def mark_label(mark):
    """Подпись кнопки и счётчика: «Тип 2», «Дефект», «Замечание»."""
    if mark.startswith("type:"):
        return "Тип {}".format(mark.split(":", 1)[1])
    return {"defect": "Дефект", "remark": "Замечание"}.get(mark, mark)


def toggle_mark(current, wanted):
    """Та же отметка ещё раз — снимает её."""
    return None if current == wanted else wanted


def default_sn(photo, pattern=None):
    """SN для поля: уже сохранённый, иначе из имени файла, иначе пусто (имя не разобрано — вводят руками)."""
    if photo.sn:
        return photo.sn
    parsed = parse_photo_name(photo.name, pattern)
    return parsed.sn if parsed else ""


def mark_counts(photos):
    """{отметка: сколько, None: без отметки}."""
    counts = {None: 0}
    for photo in photos:
        counts[photo.mark] = counts.get(photo.mark, 0) + 1
    return counts


def counts_text(photos, mark_keys):
    """«Тип 1: 3 · Дефект: 1 · Без отметки: 12» — только то, что есть, плюс всегда «Без отметки»."""
    counts = mark_counts(photos)
    parts = ["{}: {}".format(mark_label(mark), counts[mark]) for mark in mark_keys if counts.get(mark)]
    parts.append("Без отметки: {}".format(counts[None]))
    return " · ".join(parts)


def load_defect_kinds(data_dir):
    """Виды дефекта из data/defect_kinds.json; нет файла — временный список."""
    path = Path(data_dir) / "defect_kinds.json"
    try:
        kinds = [str(kind).strip() for kind in json.loads(path.read_text(encoding="utf-8-sig"))["kinds"]]
        return [kind for kind in kinds if kind]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("Нет списка видов дефекта в %s (%s), взят временный", path, exc)
        return list(DEFAULT_DEFECT_KINDS)


def neighbor_since(today, year_only=True, days=0):
    """С какой даты («ГГГГ-ММ-ДД») искать такую же деталь в соседних проектах; None — без ограничения.

    year_only — с 1 января текущего года; иначе days > 0 — последние days суток; иначе без ограничения.
    """
    if year_only:
        return date(today.year, 1, 1).isoformat()
    if days and days > 0:
        return (today - timedelta(days=int(days))).isoformat()
    return None


def reference_angles(photos, pattern=None):
    """{ракурс: индекс первого фото с таким ракурсом} по именам файлов; имя не разобрано — фото пропускается."""
    result = {}
    for number, photo in enumerate(photos):
        parsed = parse_photo_name(photo.name, pattern)
        if parsed is not None and parsed.view not in result:
            result[parsed.view] = number
    return dict(sorted(result.items()))


def photo_of_angle(photos, index, view, pattern=None):
    """Номер фото нужного ракурса вместо фото index: того же артикула и SN, иначе первое с этим ракурсом, иначе None."""
    current = parse_photo_name(photos[index].name, pattern)
    first = None
    for number, photo in enumerate(photos):
        parsed = parse_photo_name(photo.name, pattern)
        if parsed is None or parsed.view != view:
            continue
        if current is not None and (parsed.article, parsed.sn) == (current.article, current.sn):
            return number
        if first is None:
            first = number
    return first


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
        self.ref_photos = []  # фото найденной папки эталона; пусто — эталон одиночный (первое фото папки или путь)
        self.ref_index = 0
        self.reference_active = False  # активно окно эталона: стрелки листают найденную папку
        self.count = 1
        self.active = 0
        self.direction = 1  # знак последнего шага: что предзагружать
        self._indexes = [0] * MAX_CURRENTS

    @property
    def currents_count(self):
        return max(1, self.count - 1)

    @property
    def has_reference_folder(self):
        return bool(self.ref_photos)

    @property
    def shown_photos(self):
        """Что листает активное окно: фото найденной папки (эталон) или текущей папки."""
        return self.ref_photos if self.reference_active else self.photos

    @property
    def shown_index(self):
        return self.ref_index if self.reference_active else self.active_index

    def set_reference(self, photo):
        """Одиночный эталон: найденная папка забывается."""
        self.reference = photo
        self.ref_photos = []
        self.ref_index = 0
        self.reference_active = False

    def set_reference_folder(self, photos, index=0):
        """Эталон — фото другой папки; листается, когда его окно активно."""
        if not photos:
            raise ValueError("В папке эталона нет фото")
        self.ref_photos = list(photos)
        self.go_reference(index)
        self.direction = 1

    def go_reference(self, index):
        self.ref_index = min(max(index, 0), len(self.ref_photos) - 1)
        self.reference = self.ref_photos[self.ref_index]

    def set_reference_active(self, active):
        """Эталон активным может быть только найденная папка и только если эталон на экране."""
        self.reference_active = bool(active) and self.has_reference_folder and self.count > 1

    def set_photos(self, photos):
        """Новая папка. Раскладка сохраняется, эталон пока — первое фото папки."""
        self.photos = list(photos)
        self.set_reference(self.photos[0] if self.photos else None)
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
        if count == 1:
            self.reference_active = False
        if self.currents_count > before:
            self._spread_from(before - 1)
        self.active = min(self.active, self.currents_count - 1)

    def set_active(self, window):
        if not 0 <= window < self.currents_count:
            raise ValueError("Нет текущего окна {}".format(window))
        self.active = window
        self.reference_active = False

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
        return self.go(self.shown_index + step)

    def go(self, index):
        """Перейти в активном окне к фото с этим номером. True — фото сменилось."""
        if self.reference_active:
            index = min(max(index, 0), len(self.ref_photos) - 1)
            changed = index != self.ref_index
            self.direction = 1 if index >= self.ref_index else -1
            self.go_reference(index)
            return changed
        if not self.photos:
            return False
        index = min(max(index, 0), len(self.photos) - 1)
        changed = index != self.active_index
        self.direction = 1 if index >= self.active_index else -1
        self._indexes[self.active] = index
        return changed

    def rotate_active(self, delta, pattern=None):
        """Только активное окно (синхронность выключена). Вернёт {номер фото папки: поворот} для записи в базу.

        Активен эталон — поворачивается его ракурс в памяти, в базу ничего не идёт: это чужие фото.
        """
        if self.reference_active:
            turn_angle(self.ref_photos, self.ref_index, delta, pattern)
            self.reference = self.ref_photos[self.ref_index]
            return {}
        return self.rotate_angle(self.active_index, delta, pattern) if self.photos else {}

    def show_angle(self, view, pattern=None):
        """Текущие окна переходят на этот ракурс; нет его в папке — окна не меняются. Вернёт номера окон, где фото сменилось."""
        changed = []
        for window in range(self.currents_count):
            number = photo_of_angle(self.photos, self._indexes[window], view, pattern) if self.photos else None
            if number is not None and number != self._indexes[window]:
                self._indexes[window] = number
                changed.append(window)
        return changed

    def set_mark(self, index, mark, sn, defect_kind):
        """Новая отметка у фото с этим номером. Эталон, если это то же фото, остаётся как был: он только для показа."""
        old = self.photos[index]
        new_sn = old.sn if sn is None else (sn or None)  # None — не менять, как в сервисе folders
        self.photos[index] = replace(old, mark=mark, sn=new_sn, defect_kind=defect_kind)

    def rotate_angle(self, index, delta, pattern=None):
        """Повернуть фото с этим номером и все фото его ракурса; вернёт {номер: поворот} для записи в базу."""
        return turn_angle(self.photos, index, delta, pattern)

    def rotate_windows(self, delta, pattern=None):
        """«Сравнение»: всё вместе. Вернёт {номер фото папки: поворот} — это запишется в базу.

        Эталон поворачивается только в памяти, вместе со своим ракурсом в найденной папке: это чужие фото.
        Окна одного ракурса поворачиваются один раз. Эталон при одном окне тоже: он появится в «мигалке».
        """
        if self.ref_photos:
            turn_angle(self.ref_photos, self.ref_index, delta, pattern)
            self.reference = self.ref_photos[self.ref_index]
        elif self.reference is not None:
            self.reference = replace(self.reference, rotation=next_rotation(self.reference.rotation, delta))
        changed = {}
        if self.photos:
            for window in range(self.currents_count):
                if self._indexes[window] not in changed:
                    changed.update(self.rotate_angle(self._indexes[window], delta, pattern))
        return changed

    def _spread_from(self, window):
        last = max(len(self.photos) - 1, 0)
        for number in range(window + 1, MAX_CURRENTS):
            self._indexes[number] = min(self._indexes[number - 1] + 1, last)
