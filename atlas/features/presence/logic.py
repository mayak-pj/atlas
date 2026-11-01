"""Кто онлайн: чистая логика, без Qt и БД."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from atlas.core.domain.text import TIME_FORMAT


@dataclass(frozen=True)
class PresenceRow:
    user_id: int
    folder_id: Optional[int]
    beat: int
    seen_at: str


class OnlineTracker:
    """Человек онлайн, пока его beat меняется: сравниваем только со своими часами.

    Строку, которую видим впервые, сверяем по seen_at: иначе после сбоя у других вчерашняя запись
    выглядела бы как живая. Если часы ПК разошлись, человек появится со следующим сигналом.
    """

    def __init__(self, offline_after_s):
        self.offline_after_s = offline_after_s
        self._known = {}  # user_id -> (beat, когда видели изменение; None — ещё не подтверждён)

    def update(self, rows, monotonic_now, wall_now=None):
        """Возвращает строки тех, кто онлайн."""
        wall_now = wall_now or datetime.now()
        known, online = {}, []
        for row in rows:
            previous = self._known.get(row.user_id)
            if previous is None:
                changed_at = monotonic_now if self._is_fresh(row.seen_at, wall_now) else None
            elif previous[0] != row.beat:
                changed_at = monotonic_now
            else:
                changed_at = previous[1]
            known[row.user_id] = (row.beat, changed_at)
            if changed_at is not None and monotonic_now - changed_at <= self.offline_after_s:
                online.append(row)
        self._known = known
        return online

    def _is_fresh(self, seen_at, wall_now):
        try:
            moment = datetime.strptime(seen_at, TIME_FORMAT)
        except ValueError:
            return False
        return abs((wall_now - moment).total_seconds()) <= self.offline_after_s


def online_text(names):
    return "Онлайн: {}".format(", ".join(names)) if names else ""


def describe_folder(folder, part):
    """«A · Орион-24 · SSD XS-2280 · 2026-10-31». Деталь могла не найтись — покажем хотя бы дату."""
    if part is None:
        return folder.folder_date
    return " · ".join((part.kind, part.project, part.name, folder.folder_date))


def tooltip_text(entries):
    """entries: [(имя, описание папки или None)]."""
    return "\n".join("{} — {}".format(name, where or "папка не открыта") for name, where in entries)
