from datetime import datetime
from types import SimpleNamespace

import pytest

from atlas.features.folders import logic

PART = SimpleNamespace(kind="КК", project="Орион-24", name="SSD XS-2280")


def _folder(**kwargs):
    base = dict(id=1, path=r"\\nas\SSD", created_at="2026-10-31 09:12:05", status_at="2026-10-30 18:40:00")
    base.update(kwargs)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("number,word", [(1, "тип"), (2, "типа"), (4, "типа"), (5, "типов"), (11, "типов"), (21, "тип"), (112, "типов")])
def test_plural(number, word):
    assert logic.plural(number, "тип", "типа", "типов") == word


@pytest.mark.parametrize("counts,expected", [
    ({"total": 10, "unmarked": 0, "type:1": 10}, ("ОК", "ok")),
    ({"total": 10, "type:1": 8, "type:2": 2}, ("2 типа", "type2")),
    ({"total": 10, "type:1": 5, "type:2": 3, "type:3": 2}, ("3 типа", "type2")),
    ({"total": 10, "type:1": 8, "defect": 1, "type:2": 1}, ("1 деф.", "defect")),
    ({"total": 10, "type:1": 9, "remark": 1}, ("1 зам.", "remark")),
    ({"total": 10, "type:1": 7, "type:2": 1, "remark": 2}, ("2 типа", "type2")),
    ({"total": 4, "unmarked": 4}, ("ОК", "ok")),
    (None, ("ОК", "ok")),
])
def test_summary(counts, expected):
    assert logic.summary(counts) == expected


def test_new_entry_shows_where_count_and_copy_time():
    entry = logic.new_entry(_folder(), PART, {"total": 486})
    assert (entry.title, entry.subtitle, entry.note) == ("SSD XS-2280", "КК · Орион-24 · 486 фото", "скопировано 31.10 09:12")
    assert entry.pill == ""


def test_new_entry_without_part_falls_back_to_path():
    entry = logic.new_entry(_folder(), None, None)
    assert entry.title == r"\\nas\SSD"
    assert entry.subtitle == "0 фото"


def test_done_entry_has_summary_date_and_who():
    entry = logic.done_entry(_folder(), PART, {"defect": 1}, "Петров")
    assert (entry.pill, entry.pill_token, entry.note) == ("1 деф.", "defect", "30.10 · Петров")


def test_done_entry_without_user_shows_only_date():
    assert logic.done_entry(_folder(), PART, {}, "").note == "30.10"


def test_is_recent_borders():
    now = datetime(2026, 11, 1, 12, 0, 0)
    assert logic.is_recent("2026-10-25 12:00:00", now, 7)
    assert not logic.is_recent("2026-10-25 11:59:59", now, 7)
    assert not logic.is_recent(None, now, 7)
    assert not logic.is_recent("мусор", now, 7)


def test_workers_text():
    assert logic.workers_text([]) == ""
    assert logic.workers_text(["Кузнецова"]) == "Кузнецова работает"
    assert logic.workers_text(["Кузнецова", "Петров"]) == "Кузнецова, Петров работают"
