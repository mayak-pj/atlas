"""Чистая логика правил: области, фильтры, имена файлов. Без Qt, диска и базы."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from atlas.core.domain.text import clean_name, normalize_name

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
MAX_PHOTOS = 8
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
    archived_at: Optional[str] = None  # миграция 002: архив, изменение (04.11.2026)
    updated_at: Optional[str] = None
    archived_by: Optional[int] = None
    part_name: Optional[str] = None  # миграция 003: деталь и модель вписываются в форме (14.11.2026)
    model: Optional[str] = None
    read: bool = True
    photos: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def archived(self):
        return self.archived_at is not None


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
    part_name: str = ""
    model: str = ""
    full: bool = False  # новое правило (14.11.2026): заголовок, деталь, модель и комментарий обязательны


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
    part_name, model = clean_name(draft.part_name), clean_name(draft.model)
    if draft.full:
        if not normalize_name(part_name):
            raise RuleError("Впишите деталь: по ней правило покажется в «Сравнении» и найдётся в поиске")
        if not model:
            raise RuleError("Впишите модель")
        if not body:
            raise RuleError("Напишите комментарий: что именно проверять")
        if len(part_name) > TITLE_LIMIT or len(model) > TITLE_LIMIT:
            raise RuleError("Деталь и модель — не длиннее {} знаков".format(TITLE_LIMIT))
        needed[SCOPE_PART] = normalize_name(part_name)
    if draft.scope != SCOPE_GENERAL and not needed[draft.scope]:
        raise RuleError("Откройте папку: область правила берётся из неё")
    return Draft(draft.scope, title, body, draft.kind, draft.project_id, draft.device_id, draft.part_id,
                 draft.name_key, draft.scope_label, tuple(draft.photo_paths), part_name, model, draft.full)


def draft_new(title, part_name, model, body, part=None, photo_paths=()):
    """Новое правило из формы (14.11.2026): «Относится к» больше нет — правило к детали, которую вписали.

    Деталь сравнивается по ключу имени, как сводка: «SSD XS-2280» и «ssd xs2280» — одна. Если вписана открытая
    сейчас деталь — правило запоминает и её вид, проект, устройство (для фильтра по виду).
    """
    name = clean_name(part_name)
    key = normalize_name(name)
    same = part is not None and part.name_key == key
    return Draft(
        SCOPE_PART, title, body, kind=part.kind if same else None, project_id=part.project_id if same else None,
        device_id=part.device_id if same else None, part_id=part.id if same else None, name_key=key or None,
        scope_label=name, photo_paths=tuple(photo_paths), part_name=name, model=clean_name(model), full=True,
    )


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
    return [rule for rule in rules if rule.scope != SCOPE_GENERAL and not rule.archived and applies(rule, part)]


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


EDIT_DAYS = 30  # настройка rules.edit_days: месяц — пока правило узнают все коллеги (14.11.2026)


def locked(rule, today=None, days=EDIT_DAYS):
    """Изменить и удалить можно только первые days суток; дальше — только архив (решение пользователя 04.11.2026).

    Правило — обоснование работы: если к человеку претензия, видно, по какому правилу он делал.
    """
    try:
        created = datetime.strptime(str(rule.created_at)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return True
    return (today or datetime.now()) - created > timedelta(days=days)


def can_edit(rule, developer=False, today=None, days=EDIT_DAYS):
    """Изменить: любой в первые days суток, разработчик — всегда."""
    return developer or not locked(rule, today, days)


def can_delete(developer=False):
    """Удалить насовсем — только разработчик (14.11.2026); остальным — архив."""
    return bool(developer)


def can_restore(rule, user_id, developer=False):
    """Вернуть из архива — тот, кто убрал, или разработчик. Кто убрал, не записано (старый архив) — разработчик."""
    return developer or (rule.archived_by is not None and rule.archived_by == user_id)


def _search_text(rule, author):
    dates = []
    for stamp in (rule.created_at, rule.updated_at):
        try:
            when = datetime.strptime(str(stamp)[:19], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            continue
        dates += [when.strftime("%d.%m.%Y"), when.strftime("%Y-%m-%d")]
    parts = [rule.title, rule.body, author, scope_text(rule), rule.model or ""] + dates
    return " ".join(parts).casefold().replace("ё", "е")


def search(rules, query, names=None):
    """Поиск по заголовку, тексту, детали, модели, автору и дате («14.11», «2026-11», «Петров»): все слова запроса."""
    words = str(query or "").casefold().replace("ё", "е").split()
    if not words:
        return list(rules)
    names = names or {}
    return [rule for rule in rules if all(word in _search_text(rule, names.get(rule.author_id, "")) for word in words)]


def filtered(rules, key):
    """По фильтру; архивные — внизу, внутри групп порядок прежний (свежие первыми)."""
    found = [rule for rule in rules if matches_filter(rule, key)]
    return [rule for rule in found if not rule.archived] + [rule for rule in found if rule.archived]


def unread_count(rules):
    return sum(1 for rule in rules if not rule.read and not rule.archived)


def scope_text(rule):
    """Подпись области для «таблетки»."""
    if rule.scope == SCOPE_GENERAL:
        return "Общее"
    if rule.scope == SCOPE_KIND:
        return "Вид {}".format(rule.kind)
    if rule.part_name:
        return " · ".join(item for item in (rule.part_name, rule.model) if item)
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
