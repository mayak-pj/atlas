"""Сводка по детали без Qt: типы, дефекты и замечания, последняя проверка, признак «ранее были замечания»."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple

from atlas.core.domain.folders import MARK_DEFECT
from atlas.core.domain.text import TIME_FORMAT

DEFAULT_LIMIT = 10  # findings.list_limit: сколько дефектов и замечаний показывать
DEFAULT_PROBLEM_DAYS = 180  # findings.problem_days: за сколько суток считать замечания
DEFAULT_PROBLEM_MIN = 1  # findings.problem_min_marks: сколько замечаний за это время дают плашку «ранее были замечания»
TYPE_KIND = "type"  # TypeRecord.kind: в «Типах» только типы, не примеры дефектов


@dataclass(frozen=True)
class TypeLine:
    type_no: int
    text: str
    since: str  # ГГГГ-ММ-ДД, самая ранняя запись этого типа
    archived: bool  # все записи типа в архиве


@dataclass(frozen=True)
class FindingLine:
    mark: str  # defect или remark
    sn: str
    kind_text: str  # вид дефекта из справочника; пусто, если не выбран
    when: str  # ГГГГ-ММ-ДД ЧЧ:ММ:СС — когда отмечено
    author: str


@dataclass(frozen=True)
class LastCheck:
    when: str
    author: str


@dataclass(frozen=True)
class Problem:
    """«Ранее были замечания»: за последние `days` суток отмечено `count` замечаний (дефекты тоже), последнее — `last`."""

    count: int
    days: int
    last: str


@dataclass(frozen=True)
class Summary:
    part_id: int
    name: str
    types: Optional[Tuple[TypeLine, ...]]  # None — базы типов нет, блок не показываем
    findings: Tuple[FindingLine, ...]  # самые свежие, не больше list_limit
    total: int  # сколько всего дефектов и замечаний
    defects: int
    remarks: int
    last_check: Optional[LastCheck]
    problem: Optional[Problem] = None  # None — деталь не проблемная


def build_types(records):
    """Типы детали: по записям базы типов, одна строка на номер типа. Название — у самой свежей записи."""
    groups = {}
    for record in records:
        if record.kind == TYPE_KIND and record.type_no is not None:
            groups.setdefault(record.type_no, []).append(record)
    lines = []
    for number in sorted(groups):
        items = groups[number]
        newest = max(items, key=lambda item: (item.created_at, item.id))
        lines.append(TypeLine(
            number, newest.description, min(item.created_at for item in items)[:10],
            all(item.archived_at for item in items),
        ))
    return tuple(lines)


def build_findings(marks, names, limit=DEFAULT_LIMIT):
    """marks — MarkedPhoto, свежие первыми; names — {id пользователя: имя}. → (строки, всего, дефектов, замечаний)."""
    lines = tuple(
        FindingLine(item.mark, item.sn or "", item.defect_kind or "", item.marked_at, names.get(item.marked_by, ""))
        for item in marks[: max(0, int(limit))]
    )
    defects = sum(1 for item in marks if item.mark == MARK_DEFECT)
    return lines, len(marks), defects, len(marks) - defects


def positive_int(value, default):
    """Целое не меньше 1 из настройки; иначе значение по умолчанию."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 1 else default


def problem_of(marks, days, min_marks=DEFAULT_PROBLEM_MIN, now=None):
    """Problem, если за `days` суток отмечено не меньше `min_marks` замечаний. Дефект — тоже замечание, считаются все отметки."""
    since = since_text(days, now)
    recent = [item.marked_at for item in marks if item.marked_at >= since]
    if len(recent) < max(1, min_marks):
        return None
    return Problem(len(recent), days, max(recent))


def plural(number, forms):
    """Склонение по числу: plural(2, ("дефект", "дефекта", "дефектов")) → «дефекта»."""
    last_two, last = number % 100, number % 10
    if 11 <= last_two <= 14:
        return forms[2]
    return forms[0] if last == 1 else forms[1] if 2 <= last <= 4 else forms[2]


MARK_FORMS = ("замечание", "замечания", "замечаний")
DAY_FORMS = ("день", "дня", "дней")


def problem_text(problem, today=None):
    """«3 замечания за 180 дней · последнее 14.10»."""
    return "{} {} за {} {} · последнее {}".format(
        problem.count, plural(problem.count, MARK_FORMS), problem.days, plural(problem.days, DAY_FORMS),
        short_date(problem.last, today),
    )


def notice_text(name, problem, today=None):
    """Уведомление при открытии папки: «SSD: ранее были замечания — 3 замечания за 180 дней, последнее 14.10. Будьте внимательнее.»"""
    return "{}: ранее были замечания — {}. Будьте внимательнее.".format(name, problem_text(problem, today).replace(" · ", ", "))


def since_text(days, now=None):
    """Граница «за N дней» для problem_marks; None — без границы."""
    if days is None:
        return None
    return ((now or datetime.now()) - timedelta(days=days)).strftime(TIME_FORMAT)


def short_date(text, today=None):
    """«14.10» в этом году, «14.10.2025» в другом; пустой текст — пусто."""
    if not text:
        return ""
    moment = datetime.strptime(text[:10], "%Y-%m-%d")
    year = (today or datetime.now()).year
    return moment.strftime("%d.%m") if moment.year == year else moment.strftime("%d.%m.%Y")


def full_date(text):
    return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%d.%m.%Y") if text else ""


def finding_title(line):
    """Вторая строка записи: вид дефекта, а если не выбран — слово по отметке."""
    if line.kind_text:
        return line.kind_text
    return "дефект" if line.mark == MARK_DEFECT else "замечание"
