"""Чистая логика комментариев: проверка, срок жизни, кому видно. Без Qt, диска и базы."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

BODY_LIMIT = 3000
DEFAULT_MAX_PHOTOS = 4
DEFAULT_LIFETIMES = ((7, "7 дней"), (1, "1 день"), (30, "30 дней"), (None, "не удалять"))
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_ILLEGAL = re.compile(r"[^0-9A-Za-z_-]")


class CommentError(ValueError):
    """Сообщение заполнено неверно: текст можно показать человеку."""


@dataclass(frozen=True)
class Comment:
    id: int
    author_id: int
    to_user_id: Optional[int]
    body: str
    part_id: Optional[int]
    folder_id: Optional[int]
    part_label: str
    earlier_error: bool
    created_at: str
    expires_at: Optional[str]
    done: bool = False
    photos: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Draft:
    body: str
    to_user_id: Optional[int] = None
    part_id: Optional[int] = None
    folder_id: Optional[int] = None
    part_label: str = ""
    earlier_error: bool = False
    days: Optional[int] = 7
    photos: Tuple[object, ...] = ()  # пути к файлам или QImage (вставка из буфера)


def load_options(data_dir):
    """(сроки жизни [(дни|None, подпись)], максимум фото) из data/comments.json; нет файла — встроенное."""
    try:
        with open(str(data_dir / "comments.json"), encoding="utf-8-sig") as stream:
            raw = json.load(stream)
        lifetimes = tuple((item["days"], str(item["label"])) for item in raw["lifetimes"])
        if not lifetimes:
            raise ValueError("пустой список сроков")
        return lifetimes, int(raw.get("max_photos", DEFAULT_MAX_PHOTOS))
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_LIFETIMES, DEFAULT_MAX_PHOTOS


def checked(draft, max_photos=DEFAULT_MAX_PHOTOS):
    """Draft с подчищенным текстом или CommentError."""
    body = draft.body.strip()
    if not body and not draft.photos:
        raise CommentError("Напишите сообщение или приложите фото")
    if len(body) > BODY_LIMIT:
        raise CommentError("Сообщение длиннее {} знаков".format(BODY_LIMIT))
    if len(draft.photos) > max_photos:
        raise CommentError("Фото не больше {}".format(max_photos))
    return Draft(body, draft.to_user_id, draft.part_id, draft.folder_id, draft.part_label, draft.earlier_error,
                 draft.days, tuple(draft.photos))


def expires_at(days, now=None):
    """Когда сообщение исчезнет; None — не удалять."""
    if days is None:
        return None
    return ((now or datetime.now()) + timedelta(days=int(days))).strftime(TIME_FORMAT)


def is_expired(comment, now=None):
    return comment.expires_at is not None and comment.expires_at <= (now or datetime.now()).strftime(TIME_FORMAT)


def visible_to(comment, user_id):
    """Адресату и автору; «всем» — каждому. Закрытое кнопкой «Готово» не показывается."""
    if comment.done:
        return False
    return comment.to_user_id in (None, user_id) or comment.author_id == user_id


def pending_count(comments, user_id, now=None):
    """Счётчик на вкладке: чужие, не закрытые, не истёкшие и адресованные мне (или всем)."""
    return sum(1 for item in comments
               if item.author_id != user_id and visible_to(item, user_id) and not is_expired(item, now))


def _parse(text):
    try:
        return datetime.strptime(text[:19], TIME_FORMAT)
    except (ValueError, TypeError):
        return None


def lifetime_text(comment, now=None):
    """«исчезнет через 5 дн», «исчезнет сегодня»; пусто, если не удаляется."""
    until = _parse(comment.expires_at) if comment.expires_at else None
    if until is None:
        return ""
    now = now or datetime.now()
    days = (until.date() - now.date()).days
    if days <= 0:
        return "исчезнет сегодня"
    return "исчезнет через {} дн".format(days)


def short_date(text, today=None):
    """«сегодня 08:51», «вчера», «12.10», «12.10.2025»."""
    when = _parse(text) if text else None
    if when is None:
        return ""
    today = today or datetime.now()
    days = (today.date() - when.date()).days
    if days == 0:
        return "сегодня " + when.strftime("%H:%M")
    if days == 1:
        return "вчера"
    return when.strftime("%d.%m") if when.year == today.year else when.strftime("%d.%m.%Y")


def initials(name):
    return "".join(ch for ch in (name or "?").strip()[:2]).upper() or "?"


def photo_rel(stamp, unique, number):
    return "comment_{}_{}_{}.jpg".format(_ILLEGAL.sub("", stamp), _ILLEGAL.sub("", unique), number)


def thumb_rel(rel):
    return rel[:-4] + "_t.jpg" if rel.endswith(".jpg") else rel + "_t.jpg"


def part_label(part):
    """Подпись привязки по Part ядра."""
    return "" if part is None else "{} · {}".format(part.project, part.name)
