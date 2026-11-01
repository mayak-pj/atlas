from datetime import date
from types import SimpleNamespace

import pytest

from atlas.features.add_folder import logic

TODAY = date(2026, 11, 1)
KINDS = ("A", "B")


def test_clean_path_strips_spaces_and_quotes():
    assert logic.clean_path('  "R:\\Проект\\Деталь"  ') == "R:\\Проект\\Деталь"
    assert logic.clean_path("«\\\\сервер\\ресурс\\папка»") == "\\\\сервер\\ресурс\\папка"


@pytest.mark.parametrize("text, expected", [
    ("2026-10-31", "2026-10-31"), ("31.10.2026", "2026-10-31"), ("31.10.26", "2026-10-31"), ("5.3", "2026-03-05"),
    ("31/10/2026", "2026-10-31"), ("31.13.2026", None), ("32.10", None), ("вчера", None), ("", None), ("31.10.2026 (5 фото)", None),
])
def test_parse_date(text, expected):
    assert logic.parse_date(text, TODAY) == expected


@pytest.mark.parametrize("name, expected", [
    ("31.10.2026 (120 фото)", "2026-10-31"), ("2026-10-31 120", "2026-10-31"), ("120 фото 31.10.26", "2026-10-31"),
    ("31.10", "2026-10-31"), ("Плата MB-15", None), ("SSD XS-2280 512GB", None), ("Тип 1", None), ("", None),
])
def test_find_date_at_start_or_end_of_name(name, expected):
    assert logic.find_date(name, TODAY) == expected


def test_suggest_four_levels_with_device():
    result = logic.suggest("R:\\Однотипность\\Орион-24\\N15\\Плата MB-15\\31.10.2026 (120 фото)", KINDS, today=TODAY)
    assert (result.project, result.device, result.part, result.date) == ("Орион-24", "N15", "Плата MB-15", "2026-10-31")


def test_suggest_three_levels_has_no_device():
    result = logic.suggest("R:\\Однотипность\\Орион-24\\Плата MB-15\\31.10", KINDS, "Без устройства", TODAY)
    assert (result.project, result.device, result.part) == ("Орион-24", "Без устройства", "Плата MB-15")


def test_suggest_unc_path_and_forward_slashes():
    unc = logic.suggest("\\\\сервер\\ресурс\\Однотипность\\Орион-24\\Плата\\2026-10-31", KINDS, today=TODAY)
    assert (unc.project, unc.part, unc.date, unc.kind) == ("Орион-24", "Плата", "2026-10-31", None)
    slashes = logic.suggest("R:/Однотипность/Орион-24/Плата/31.10", KINDS, today=TODAY)
    assert (slashes.project, slashes.part) == ("Орион-24", "Плата")


def test_suggest_kind_from_drive_letter_only_if_it_is_a_kind():
    assert logic.suggest("B:\\Однотипность\\П\\Д\\31.10", KINDS, today=TODAY).kind == "B"
    assert logic.suggest("b:\\Однотипность\\П\\Д\\31.10", KINDS, today=TODAY).kind == "B"
    assert logic.suggest("R:\\Однотипность\\П\\Д\\31.10", KINDS, today=TODAY).kind is None


def test_suggest_without_date_takes_last_folder_as_part():
    result = logic.suggest("R:\\Однотипность\\Орион-24\\Плата MB-15", KINDS, today=TODAY)
    assert (result.project, result.part, result.date) == ("Орион-24", "Плата MB-15", None)


def test_suggest_short_or_empty_path_is_safe():
    assert logic.suggest("", KINDS, today=TODAY) == logic.Suggestion(None, "", "", "", None)
    result = logic.suggest("R:\\Плата", KINDS, today=TODAY)
    assert (result.project, result.part) == ("", "Плата")  # одного уровня мало, чтобы угадать проект


def good(**changes):
    values = dict(path="R:\\x", kind="A", project="П", device="У", part="Д", date_text="31.10.2026", photos=["1.jpg"], kinds=KINDS)
    values.update(changes)
    return logic.check(today=TODAY, **values)


def test_check_returns_data_with_clean_names_and_iso_date():
    data = good(project="  Орион   24 ", part="Плата  MB-15")
    assert (data.project, data.part, data.date, data.photos) == ("Орион 24", "Плата MB-15", "2026-10-31", ("1.jpg",))


@pytest.mark.parametrize("change, text", [
    ({"path": "  "}, "папку"), ({"kind": "Z"}, "вид"), ({"project": "-- "}, "проект"), ({"device": ""}, "устройство"),
    ({"part": "  "}, "детал"), ({"date_text": "31.31"}, "Дата"), ({"photos": []}, ".jpg"),
])
def test_check_explains_what_is_wrong(change, text):
    assert text in good(**change)


def test_known_options_group_devices_by_kind_and_project():
    parts = [SimpleNamespace(kind="A", project="П1", device="Б"), SimpleNamespace(kind="A", project="П1", device="а"),
             SimpleNamespace(kind="A", project="П1", device="Б"), SimpleNamespace(kind="B", project="П2", device="В")]
    assert logic.known_options(parts) == {"A": {"П1": ["а", "Б"]}, "B": {"П2": ["В"]}}


def test_no_device_name_from_data_file_with_fallback(tmp_path):
    assert logic.load_no_device(tmp_path) == logic.DEFAULT_NO_DEVICE
    (tmp_path / "add_folder.json").write_text('{"no_device_name": "Общее"}', encoding="utf-8")
    assert logic.load_no_device(tmp_path) == "Общее"
    (tmp_path / "add_folder.json").write_text("{плохо", encoding="utf-8")
    assert logic.load_no_device(tmp_path) == logic.DEFAULT_NO_DEVICE
