from datetime import datetime

import pytest

from atlas.features.login import logic


def test_normalize_and_validate():
    assert logic.validate_name("  петров  ") == "Петров"
    assert logic.validate_name("иванова   анна") == "Иванова анна"


@pytest.mark.parametrize("bad", ["", " ", "а", "12", "x" * 41])
def test_invalid_names(bad):
    with pytest.raises(logic.NameInvalid):
        logic.validate_name(bad)


def test_duplicate_ignores_case():
    with pytest.raises(logic.NameInvalid):
        logic.validate_name("ПЕТРОВ", existing=["Петров"])


def test_pick_color_cycles_and_has_fallback():
    assert logic.pick_color(["a", "b"], 3) == "b"
    assert logic.pick_color([], 0) == logic.DEFAULT_COLORS[0]


def test_describe_last_login():
    now = datetime(2026, 10, 31, 12, 0)
    assert logic.describe_last_login(None, now) == "первый вход"
    assert logic.describe_last_login("2026-10-31 09:10:00", now) == "сегодня, 09:10"
    assert logic.describe_last_login("2026-10-30 17:42:00", now) == "вчера, 17:42"
    assert logic.describe_last_login("2026-10-28 12:00:00", now) == "28.10.2026, 12:00"
    assert logic.describe_last_login("мусор", now) == "время входа неизвестно"
