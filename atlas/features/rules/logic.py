"""Чистая логика правил: области, фильтры, имена файлов. Без Qt, диска и базы."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

SCOPE_GENERAL = "general"
SCOPE_KIND = "kind"
SCOPE_PROJECT = "project"
SCOPE_DEVICE = "device"
SCOPE_PART = "part"
SCOPES = (SCOPE_GENERAL, SCOPE_KIND, SCOPE_PROJECT, SCOPE_DEVICE, SCOPE_PART)
FILTER_ALL = "all"
FILTER_GENERAL = "general"
FILTER_PART = "part"  # «К детали»: всё, что не общее и не на весь вид
FILTER_KIND_PREFIX = "kind:"
TITLE_LIMIT = 200
BODY_LIMIT = 5000
MAX_PHOTOS = 6
_ILLEGAL = re.compile(r"[^0-9A-Za-z_-]")


class RuleError(ValueError):
    """Правило заполнено неверно: текст можно показать человеку."""


@dataclass(frozen=True)
class Rule:
    id: int
    scope: str
    kind: Optional[str]
    project_id: Optional[int]
    device_id: Optional[int]
    part_id: Optional[int]
    name_key: Optional[str]
    scope_label: str
    title: str
    body: str
    author_id: Optional[int]
    created_at: str
    read: bool = True
    photos: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Draft:
    """Что человек ввёл в форму. Область берётся из открытой детали, сама по себе её не выбрать."""

    scope: str
    title: str
    body: str
    kind: Optional[str] = None
    project_id: Optional[int] = None
    device_id: Optional[int] = None
    part_id: Optional[int] = None
    name_key: Optional[str] = None
    scope_label: str = ""
    photo_paths: Tuple[str, ...] = ()


def checked(draft):
    """Draft с подчищенным текстом или RuleError."""
    title = " ".join(draft.title.split())
    body = draft.body.strip()
    if draft.scope not in SCOPES:
        raise RuleError("Неизвестная область правила")
    if not title:
        raise RuleError("Напишите заголовок: коротко, что проверять")
    if len(title) > TITLE_LIMIT:
        raise RuleError("Заголовок длиннее {} знаков".format(TITLE_LIMIT))
    if len(body) > BODY_LIMIT:
        raise RuleError("Описание длиннее {} знаков".format(BODY_LIMIT))
    if len(draft.photo_paths) > MAX_PHOTOS:
        raise RuleError("Фото не больше {}".format(MAX_PHOTOS))
    needed = {SCOPE_KIND: draft.kind, SCOPE_PROJECT: draft.project_id, SCOPE_DEVICE: draft.device_id, SCOPE_PART: draft.part_id}
    if draft.scope != SCOPE_GENERAL and not needed[draft.scope]:
        raise RuleError("Откройте папку: область правила берётся из неё")
    return Draft(draft.scope, title, body, draft.kind, draft.project_id, draft.device_id, draft.part_id,
                 draft.name_key, draft.scope_label, tuple(draft.photo_paths))


def applies(rule, part):
    """Правило относится к этой детали (Part ядра). Общие — ко всем, но в «правила к детали» их не кладут: см. for_part."""
    if rule.scope == SCOPE_GENERAL:
        return True
    if part is None:
        return False
    if rule.scope == SCOPE_KIND:
        return rule.kind == part.kind
    if rule.scope == SCOPE_PROJECT:
        return rule.project_id == part.project_id
    if rule.scope == SCOPE_DEVICE:
        return rule.device_id == part.device_id
    return rule.name_key == part.name_key


def for_part(rules, part):
    """Правила к детали: всё, что названо про неё, её устройство, проект или вид; общие не входят."""
    return [rule for rule in rules if rule.scope != SCOPE_GENERAL and applies(rule, part)]


def matches_filter(rule, key):
    if key == FILTER_ALL:
        return True
    if key == FILTER_GENERAL:
        return rule.scope == SCOPE_GENERAL
    if key == FILTER_PART:
        return rule.scope in (SCOPE_PROJECT, SCOPE_DEVICE, SCOPE_PART)
    if key.startswith(FILTER_KIND_PREFIX):
        return rule.kind == key[len(FILTER_KIND_PREFIX):]
    return True


def filtered(rules, key):
    return [rule for rule in rules if matches_filter(rule, key)]


def unread_count(rules):
    return sum(1 for rule in rules if not rule.read)


def scope_text(rule):
    """Подпись области для «таблетки»."""
    if rule.scope == SCOPE_GENERAL:
        return "Общее"
    if rule.scope == SCOPE_KIND:
        return "Вид {}".format(rule.kind)
    return rule.scope_label


def scope_label_for(scope, part):
    """Подпись области по открытой детали (Part ядра)."""
    if scope == SCOPE_GENERAL or part is None:
        return ""
    if scope == SCOPE_KIND:
        return "Вид {}".format(part.kind)
    if scope == SCOPE_PROJECT:
        return "{} · {}".format(part.kind, part.project)
    if scope == SCOPE_DEVICE:
        return "{} · {} · {}".format(part.kind, part.project, part.device)
    return "{} · {}".format(part.kind, part.name)


def draft_for(scope, part, title, body, photo_paths=()):
    """Draft из формы и открытой детали."""
    if scope == SCOPE_GENERAL or part is None:
        return Draft(SCOPE_GENERAL, title, body, photo_paths=tuple(photo_paths))
    return Draft(
        scope, title, body, kind=part.kind,
        project_id=part.project_id if scope in (SCOPE_PROJECT, SCOPE_DEVICE, SCOPE_PART) else None,
        device_id=part.device_id if scope in (SCOPE_DEVICE, SCOPE_PART) else None,
        part_id=part.id if scope == SCOPE_PART else None,
        name_key=part.name_key if scope == SCOPE_PART else None,
        scope_label=scope_label_for(scope, part), photo_paths=tuple(photo_paths),
    )


def photo_rel(stamp, unique, number):
    """Имя файла фото: время и случайный хвост — номера правила до записи в базу ещё нет."""
    return "rule_{}_{}_{}.jpg".format(_ILLEGAL.sub("", stamp), _ILLEGAL.sub("", unique), number)


def thumb_rel(rel):
    return rel[:-4] + "_t.jpg" if rel.endswith(".jpg") else rel + "_t.jpg"


def short_date(text, today=None):
    """«сегодня 08:51», «вчера», «12.10», «12.10.2025»."""
    if not text:
        return ""
    try:
        when = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ""
    today = today or datetime.now()
    days = (today.date() - when.date()).days
    if days == 0:
        return "сегодня " + when.strftime("%H:%M")
    if days == 1:
        return "вчера"
    return when.strftime("%d.%m") if when.year == today.year else when.strftime("%d.%m.%Y")
