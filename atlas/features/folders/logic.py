"""Панель папок: что показать в карточках. Без Qt и БД."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

from atlas.core.domain.text import TIME_FORMAT

DEFAULT_DONE_DAYS = 7
DEFAULT_LIMIT = 50
PREFIX_TYPE = "type:"


@dataclass(frozen=True)
class Entry:
    folder_id: int
    title: str  # деталь
    subtitle: str  # «A · Орион-24 · 486 фото»
    note: str  # «скопировано 31.10 09:12» или «30.10 · Иванова»
    pill: str = ""  # итог проверки; у новых пусто
    pill_token: str = ""  # токен цвета темы: ok, type2, defect, remark


@dataclass(frozen=True)
class Snapshot:
    new: List[Entry]
    new_total: int
    done: List[Entry]


def plural(number, one, few, many):
    """1 тип, 2 типа, 5 типов."""
    tail = abs(number) % 100
    if 10 < tail < 20:
        return many
    last = tail % 10
    return one if last == 1 else few if 2 <= last <= 4 else many


def summary(counts):
    """(текст, токен цвета) итога по счётчикам папки: дефекты важнее типов, типы важнее замечаний."""
    counts = counts or {}
    defects = counts.get("defect", 0)
    remarks = counts.get("remark", 0)
    types = sum(1 for key, count in counts.items() if key.startswith(PREFIX_TYPE) and count > 0)
    if defects:
        return "{} деф.".format(defects), "defect"
    if types > 1:
        return "{} {}".format(types, plural(types, "тип", "типа", "типов")), "type2"
    if remarks:
        return "{} зам.".format(remarks), "remark"
    return "ОК", "ok"


def parse_time(text):
    try:
        return datetime.strptime(text, TIME_FORMAT)
    except (TypeError, ValueError):
        return None


def short_date(text):
    """«2026-10-31 09:12:05» → «31.10»; непонятное — как есть."""
    moment = parse_time(text)
    return moment.strftime("%d.%m") if moment else (text or "")


def short_time(text):
    moment = parse_time(text)
    return moment.strftime("%d.%m %H:%M") if moment else (text or "")


def is_recent(status_at, now, days):
    """Проверено не раньше чем `days` суток назад. Время не разобрать — не показываем."""
    moment = parse_time(status_at)
    return moment is not None and now - moment <= timedelta(days=days)


def where_text(part):
    return " · ".join((part.kind, part.project)) if part is not None else ""


def part_title(part, folder):
    return part.name if part is not None else folder.path


def new_entry(folder, part, counts):
    total = (counts or {}).get("total", 0)
    subtitle = " · ".join(item for item in (where_text(part), "{} фото".format(total)) if item)
    return Entry(folder.id, part_title(part, folder), subtitle, "скопировано " + short_time(folder.created_at))


def done_entry(folder, part, counts, user_name):
    text, token = summary(counts)
    who = " · ".join(item for item in (short_date(folder.status_at), user_name) if item)
    return Entry(folder.id, part_title(part, folder), where_text(part), who, text, token)


def workers_text(names):
    """«Кузнецова работает», «Кузнецова, Петров работают». Пусто — никто."""
    if not names:
        return ""
    return "{} {}".format(", ".join(names), "работает" if len(names) == 1 else "работают")
