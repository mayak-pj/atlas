"""Дашборд без Qt: границы периода и сбор цифр из готовых выборок."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Tuple

from atlas.core.domain.text import TIME_FORMAT

WEEK, MONTH, YEAR = "week", "month", "year"
PERIODS = ((WEEK, "Неделя"), (MONTH, "Месяц"), (YEAR, "Год"))
PERIOD_NOTE = {WEEK: "за неделю", MONTH: "за месяц", YEAR: "за год"}
MONTHS = ("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь",
          "Декабрь")
CLEAN_DAYS = 90  # «детали без проблем» — за этот срок
TOP_LIMIT = 5
CLEAN_LIMIT = 30
NO_KIND = "Вид не указан"
ALL_KINDS = ""  # фильтр по виду проекта: пусто — все


def _text(moment):
    return moment.strftime(TIME_FORMAT)


def period_range(period, today=None):
    """(с, по, подпись): календарная неделя с понедельника, месяц, год; «по» не включается."""
    today = today or date.today()
    if period == WEEK:
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=7)
        label = "Неделя {:02d}.{:02d} – {:02d}.{:02d}".format(start.day, start.month, (end - timedelta(days=1)).day,
                                                             (end - timedelta(days=1)).month)
    elif period == MONTH:
        start = today.replace(day=1)
        end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
        label = "{} {}".format(MONTHS[start.month - 1], start.year)
    elif period == YEAR:
        start, end = date(today.year, 1, 1), date(today.year + 1, 1, 1)
        label = "{} год".format(today.year)
    else:
        raise ValueError("Неизвестный период: {}".format(period))
    return _text(datetime(start.year, start.month, start.day)), _text(datetime(end.year, end.month, end.day)), label


def clean_range(today=None):
    """Последние CLEAN_DAYS суток, включая сегодня: (с, по)."""
    today = today or date.today()
    end = datetime(today.year, today.month, today.day) + timedelta(days=1)
    return _text(end - timedelta(days=CLEAN_DAYS)), _text(end)


@dataclass
class Stats:
    label: str = ""
    note: str = ""
    folders: int = 0
    photos: int = 0
    problems: int = 0
    problem_parts: int = 0
    new_types: int = 0
    top_parts: List[Tuple[str, int]] = field(default_factory=list)
    kinds: List[Tuple[str, int]] = field(default_factory=list)
    clean_parts: List[str] = field(default_factory=list)
    clean_more: int = 0  # сколько не поместилось в список


def _wanted(parts, part_id, kind):
    part = parts.get(part_id)
    if part is None:
        return False
    return kind == ALL_KINDS or part.kind == kind


def _top(counter, limit):
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]


def build(parts, activity, clean_activity, new_type_part_ids, kind=ALL_KINDS, label="", note=""):
    """parts — {id: Part}; activity — за период, clean_activity — за CLEAN_DAYS (оба `Activity` ядра);
    new_type_part_ids — part_id у каждого нового типа за период."""
    stats = Stats(label=label, note=note)
    for _folder_id, part_id, photos in activity.done:
        if _wanted(parts, part_id, kind):
            stats.folders += 1
            stats.photos += photos
    by_part, by_kind = Counter(), Counter()
    for part_id, defect_kind in activity.problems:
        if _wanted(parts, part_id, kind):
            by_part[part_id] += 1
            by_kind[(defect_kind or "").strip() or NO_KIND] += 1
    stats.problems = sum(by_part.values())
    stats.problem_parts = len(by_part)
    stats.new_types = sum(1 for part_id in new_type_part_ids if _wanted(parts, part_id, kind))
    named = Counter()
    for part_id, count in by_part.items():
        named[parts[part_id].name] += count
    stats.top_parts = _top(named, TOP_LIMIT)
    stats.kinds = _top(by_kind, TOP_LIMIT + 3)
    bad = {part_id for part_id, _kind in clean_activity.problems}
    clean = sorted({parts[part_id].name for _f, part_id, _p in clean_activity.done
                    if part_id not in bad and _wanted(parts, part_id, kind)}, key=str.casefold)
    stats.clean_parts, stats.clean_more = clean[:CLEAN_LIMIT], max(0, len(clean) - CLEAN_LIMIT)
    return stats
