"""Чистая логика входа (без Qt и БД)."""
from __future__ import annotations

from datetime import datetime

from atlas.core.domain.text import TIME_FORMAT, name_key

MIN_LENGTH = 2
MAX_LENGTH = 40
DEFAULT_COLORS = ["#7DB4FF", "#3DD68C", "#F2A93B", "#C59CFF", "#FF8A8A", "#5FD3D3"]


class NameInvalid(ValueError):
    """Фамилия не подходит. Текст показывается пользователю."""


def normalize_name(raw):
    """Лишние пробелы убираем, первая буква заглавная («петров» → «Петров»)."""
    name = " ".join(raw.split())
    return name[:1].upper() + name[1:]


def validate_name(raw, existing=()):
    name = normalize_name(raw)
    if len(name) < MIN_LENGTH:
        raise NameInvalid("Введите фамилию (не короче {} букв)".format(MIN_LENGTH))
    if len(name) > MAX_LENGTH:
        raise NameInvalid("Слишком длинное имя (не больше {} знаков)".format(MAX_LENGTH))
    if not any(ch.isalpha() for ch in name):
        raise NameInvalid("В фамилии должны быть буквы")
    if name_key(name) in {name_key(item) for item in existing}:
        raise NameInvalid("Такая фамилия уже есть в списке")
    return name


def pick_color(colors, used_count):
    """Следующий по кругу цвет из data/user_colors.json."""
    palette = list(colors) or DEFAULT_COLORS
    return palette[used_count % len(palette)]


def describe_last_login(value, now=None):
    """«вчера, 17:42» / «сегодня, 09:10» / «28.10.2026, 12:00» / «первый вход»."""
    if not value:
        return "первый вход"
    try:
        moment = datetime.strptime(value, TIME_FORMAT)
    except ValueError:
        return "время входа неизвестно"
    today = (now or datetime.now()).date()
    days = (today - moment.date()).days
    clock = moment.strftime("%H:%M")
    if days == 0:
        return "сегодня, " + clock
    if days == 1:
        return "вчера, " + clock
    return moment.strftime("%d.%m.%Y, ") + clock
