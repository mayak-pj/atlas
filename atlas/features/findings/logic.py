"""Сводка по детали без Qt: какие детали считать «той же», типы, дефекты, последняя проверка."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Optional, Tuple

from atlas.core.domain.folders import MARK_DEFECT
from atlas.core.domain.text import TIME_FORMAT, normalize_name

DEFAULT_MATCH = 0.85  # findings.name_match: 1 — только одинаковые названия
DEFAULT_LIMIT = 10  # findings.list_limit: сколько дефектов и замечаний показывать
DEFAULT_PROBLEM_DAYS = 30  # findings.problem_days: за сколько суток считать дефекты
DEFAULT_PROBLEM_MIN = 1  # findings.problem_min_defects: сколько дефектов за это время делают деталь «проблемной»
TYPE_KIND = "type"  # TypeRecord.kind: в «Типах» только типы, не примеры дефектов


def match_threshold(value):
    """Порог из настройки; всё, что не число от 0 до 1, — значение по умолчанию."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULT_MATCH
    return number if 0.0 <= number <= 1.0 else DEFAULT_MATCH


def _numbers_agree(first, second):
    """Числа в названиях не противоречат друг другу: «512GB» и «256GB» — разные детали, «512GB» и «512GB v2» — одна.

    По числам у более короткого названия всё должно найтись в более длинном. Общее сходство строк этого не видит
    (у «512GB» и «256GB» оно выше 0,85), а перепутать ёмкость значит смешать истории дефектов разных деталей.
    """
    one = Counter(re.findall(r"\d+", unicodedata.normalize("NFKC", first)))
    two = Counter(re.findall(r"\d+", unicodedata.normalize("NFKC", second)))
    if sum(one.values()) > sum(two.values()):
        one, two = two, one
    return not (one - two)


def is_similar(first, second, threshold=DEFAULT_MATCH):
    """Названия деталей считаются одной деталью: ключи равны (регистр, «е/ё», разделители) или похожи не меньше порога.

    Похожие — только если числа в названиях согласуются (`_numbers_agree`).
    """
    key_a, key_b = normalize_name(first), normalize_name(second)
    if not key_a or not key_b:
        return False
    if key_a == key_b:
        return True
    if threshold >= 1.0 or not _numbers_agree(first, second):
        return False
    matcher = SequenceMatcher(None, key_a, key_b, autojunk=False)
    if matcher.real_quick_ratio() < threshold or matcher.quick_ratio() < threshold:
        return False  # дешёвые верхние оценки: детали в справочнике сотнями, полный расчёт нужен не всем
    return matcher.ratio() >= threshold


def similar_parts(current, parts, threshold=DEFAULT_MATCH):
    """Сама деталь и все детали с таким же или похожим названием (в других устройствах и проектах)."""
    result = [current]
    for part in parts:
        if part.id != current.id and is_similar(current.name, part.name, threshold):
            result.append(part)
    return result


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
    """Деталь «проблемная»: за последние `days` суток было `defects` дефектов, последний отмечен `last`."""

    defects: int
    days: int
    last: str


@dataclass(frozen=True)
class Summary:
    part_id: int
    name: str
    similar_names: Tuple[str, ...]  # названия других деталей, учтённых как «та же»
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


def problem_of(marks, days, min_defects=DEFAULT_PROBLEM_MIN, now=None):
    """Problem, если за `days` суток дефектов (замечания не считаются) не меньше `min_defects`; иначе None."""
    since = since_text(days, now)
    recent = [item.marked_at for item in marks if item.mark == MARK_DEFECT and item.marked_at >= since]
    if len(recent) < max(1, min_defects):
        return None
    return Problem(len(recent), days, max(recent))


def plural(number, forms):
    """Склонение по числу: plural(2, ("дефект", "дефекта", "дефектов")) → «дефекта»."""
    last_two, last = number % 100, number % 10
    if 11 <= last_two <= 14:
        return forms[2]
    return forms[0] if last == 1 else forms[1] if 2 <= last <= 4 else forms[2]


DEFECT_FORMS = ("дефект", "дефекта", "дефектов")
DAY_FORMS = ("день", "дня", "дней")


def problem_text(problem, today=None):
    """«3 дефекта за 30 дней · последний 14.10»."""
    return "{} {} за {} {} · последний {}".format(
        problem.defects, plural(problem.defects, DEFECT_FORMS), problem.days, plural(problem.days, DAY_FORMS),
        short_date(problem.last, today),
    )


def notice_text(name, problem, today=None):
    """Уведомление при открытии папки: «SSD: проблемная деталь — 3 дефекта за 30 дней, последний 14.10. Будьте внимательнее.»"""
    return "{}: проблемная деталь — {}. Будьте внимательнее.".format(name, problem_text(problem, today).replace(" · ", ", "))


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
