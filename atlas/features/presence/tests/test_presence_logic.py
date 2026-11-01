from datetime import datetime

from atlas.features.presence import logic
from atlas.features.presence.logic import OnlineTracker, PresenceRow

NOW = datetime(2026, 11, 1, 12, 0, 0)
FRESH = "2026-11-01 11:59:50"
YESTERDAY = "2026-10-31 18:00:00"


def _row(beat, seen_at=FRESH, user_id=1):
    return PresenceRow(user_id, None, beat, seen_at)


def _ids(rows):
    return [row.user_id for row in rows]


def test_online_while_beat_changes_then_offline():
    tracker = OnlineTracker(90)
    assert _ids(tracker.update([_row(1)], 0, NOW)) == [1]
    assert _ids(tracker.update([_row(2)], 60, NOW)) == [1]
    assert _ids(tracker.update([_row(2)], 150, NOW)) == [1]
    assert _ids(tracker.update([_row(2)], 151, NOW)) == []
    assert _ids(tracker.update([_row(3)], 180, NOW)) == [1]


def test_stale_row_after_crash_is_not_online_until_it_beats():
    tracker = OnlineTracker(90)
    assert tracker.update([_row(5, YESTERDAY)], 0, NOW) == []
    assert tracker.update([_row(5, YESTERDAY)], 30, NOW) == []
    assert _ids(tracker.update([_row(6, YESTERDAY)], 60, NOW)) == [1]


def test_clock_far_ahead_does_not_hide_a_live_person_for_long():
    tracker = OnlineTracker(90)
    assert tracker.update([_row(1, "2026-11-01 15:00:00")], 0, NOW) == []
    assert _ids(tracker.update([_row(2, "2026-11-01 15:00:30")], 30, NOW)) == [1]


def test_bad_time_is_not_fresh():
    assert OnlineTracker(90).update([_row(1, "вчера")], 0, NOW) == []


def test_removed_row_is_forgotten():
    tracker = OnlineTracker(90)
    tracker.update([_row(1)], 0, NOW)
    assert tracker.update([], 10, NOW) == []
    assert _ids(tracker.update([_row(1)], 20, NOW)) == [1]


def test_texts():
    assert logic.online_text([]) == ""
    assert logic.online_text(["Петров", "Кузнецова"]) == "Онлайн: Петров, Кузнецова"
    assert logic.tooltip_text([("Петров", "КК · А"), ("Иванова", None)]) == "Петров — КК · А\nИванова — папка не открыта"
