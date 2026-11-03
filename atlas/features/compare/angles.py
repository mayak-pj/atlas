"""Режим «Ракурсы» без Qt: какие фото папки — ракурсы одного SN и что показать в окнах.

Везде «фото» — номер в списке фото папки: отметки меняют сам список, а номера остаются верными.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional

from atlas.core.domain.photo_names import parse_photo_name
from atlas.features.compare.logic import MAX_WINDOWS, neighbor_indexes

MAX_REPEATS_SHOWN = 3  # больше групп повторов в строке не поместится; это ошибка в именах, а не обычный случай


@dataclass(frozen=True)
class AngleSet:
    """Все ракурсы одного артикула и SN. photos: {ракурс: номер фото}, в том числе те, которым не хватило окна."""
    article: str
    sn: str
    photos: Dict[int, int]

    @property
    def first_photo(self):
        return self.photos[min(self.photos)]


@dataclass(frozen=True)
class AnglesPlan:
    views: List[int]  # ракурс каждого окна, по возрастанию, не больше MAX_WINDOWS
    hidden: int  # сколько ещё ракурсов есть в папке
    sets: List[AngleSet]  # по артикулу и SN: папка отсортирована по имени, там все первые ракурсы идут раньше вторых
    unparsed: int  # имя не разобрано: такие фото видны только в «Сравнении»
    repeats: List[List[str]]  # имена файлов с одинаковыми артикулом, ракурсом и SN; показан первый
    available: List[int] = field(default_factory=list)  # все ракурсы папки по возрастанию: кнопки включения


def build_plan(photos, pattern=None) -> AnglesPlan:
    grouped = {}  # (артикул, SN) → {ракурс: [номер фото]}
    unparsed = 0
    for number, photo in enumerate(photos):
        parsed = parse_photo_name(photo.name, pattern)
        if parsed is None:
            unparsed += 1
            continue
        grouped.setdefault((parsed.article, parsed.sn), {}).setdefault(parsed.view, []).append(number)
    sets, repeats, all_views = [], [], set()
    for (article, sn), views in sorted(grouped.items()):
        chosen = {}
        for view, numbers in sorted(views.items()):
            ordered = sorted(numbers, key=lambda number: photos[number].name)
            chosen[view] = ordered[0]
            if len(ordered) > 1:
                repeats.append([photos[number].name for number in ordered])
        all_views.update(chosen)
        sets.append(AngleSet(article, sn, chosen))
    ordered_views = sorted(all_views)
    return AnglesPlan(ordered_views[:MAX_WINDOWS], max(len(ordered_views) - MAX_WINDOWS, 0), sets, unparsed, repeats,
                      ordered_views)


def with_views(plan, views) -> AnglesPlan:
    """Человек выключил часть ракурсов: окна только у включённых, по возрастанию."""
    shown = sorted(views)
    return replace(plan, views=shown, hidden=max(len(plan.available) - MAX_WINDOWS, 0) if len(shown) == MAX_WINDOWS else 0)


def notes(plan) -> List[str]:
    """Что сказать про папку. Текст один на всю папку: строка не меняет высоту при листании, раскладка не прыгает."""
    result = []
    if plan.hidden:
        result.append("Ещё ракурсов: {} — чтобы показать, выключите другой".format(plan.hidden))
    if plan.unparsed:
        result.append("Имя не разобрано у фото: {} (они видны в «Сравнении»)".format(plan.unparsed))
    if plan.repeats:
        groups = [", ".join(names) for names in plan.repeats[:MAX_REPEATS_SHOWN]]
        rest = len(plan.repeats) - len(groups)
        tail = ", и ещё повторов: {}".format(rest) if rest else ""
        result.append("Ошибка в именах, показан первый файл: {}{}".format("; ".join(groups), tail))
    return result


def set_mark(angle_set, photos, views=None):
    """Отметка для точки на ленте: у SN их может быть несколько. Дефект важнее типа, тип важнее замечания."""
    numbers = [number for view, number in angle_set.photos.items() if views is None or view in views]
    marks = [photos[number].mark for number in numbers if photos[number].mark]
    for prefix in ("defect", "type:", "remark"):
        for mark in marks:
            if mark.startswith(prefix):
                return mark
    return None


class AnglesModel:
    """План папки, текущий SN, активное окно. Окно — номер в plan.views."""

    def __init__(self):
        self.plan = build_plan([])
        self._full_views = []
        self.index = 0
        self.active = 0
        self.direction = 1
        self._set_of_photo = {}

    def set_photos(self, photos, pattern=None):
        self.plan = build_plan(photos, pattern)
        self._full_views = list(self.plan.views)
        self.index = 0
        self.active = 0
        self.direction = 1
        self._set_of_photo = {
            number: place for place, angle_set in enumerate(self.plan.sets) for number in angle_set.photos.values()
        }

    def show_all(self):
        """Режим включили заново: снова все ракурсы, сколько помещается."""
        self._set_views(self._full_views)

    def set_view_shown(self, view, shown):
        """Включить или выключить ракурс. False — нельзя: больше окон нет или это последний включённый."""
        views = set(self.plan.views)
        if view not in self.plan.available or (view in views) == shown:
            return False
        if shown and len(views) >= MAX_WINDOWS or not shown and len(views) == 1:
            return False
        self._set_views(views | {view} if shown else views - {view})
        return True

    def _set_views(self, views):
        active_view = self.active_view_number
        self.plan = with_views(self.plan, views)
        self.active = self.plan.views.index(active_view) if active_view in self.plan.views else 0

    @property
    def total(self):
        return len(self.plan.sets)

    @property
    def current(self) -> Optional[AngleSet]:
        return self.plan.sets[self.index] if self.plan.sets else None

    @property
    def active_view_number(self):
        return self.plan.views[self.active] if self.plan.views else None

    def photo_in(self, window) -> Optional[int]:
        """Номер фото в этом окне; None — у SN нет этого ракурса."""
        current = self.current
        return current.photos.get(self.plan.views[window]) if current is not None else None

    def active_photo(self) -> Optional[int]:
        return self.photo_in(self.active) if self.plan.views else None

    def set_active(self, window):
        if not 0 <= window < len(self.plan.views):
            raise ValueError("Нет окна ракурса {}".format(window))
        self.active = window

    def go(self, index):
        """Перейти к SN с этим номером, по краям останавливается. True — SN сменился."""
        if not self.plan.sets:
            return False
        index = min(max(index, 0), self.total - 1)
        changed = index != self.index
        self.direction = 1 if index >= self.index else -1
        self.index = index
        return changed

    def show_photo(self, number):
        """Встать на SN этого фото и его окно: человек продолжает смотреть то же. Фото без SN — ничего не меняется."""
        place = self._set_of_photo.get(number)
        if place is None:
            return
        self.index = place
        for view, photo in self.plan.sets[place].photos.items():
            if photo == number and view in self.plan.views:
                self.active = self.plan.views.index(view)

    def set_of_photo(self, number) -> Optional[int]:
        return self._set_of_photo.get(number)

    def neighbor_photos(self) -> List[int]:
        """Все показываемые ракурсы соседних SN, сначала самое важное."""
        result = []
        for place in neighbor_indexes(self.index, self.total, self.direction):
            photos = self.plan.sets[place].photos
            result.extend(photos[view] for view in self.plan.views if view in photos)
        return result
