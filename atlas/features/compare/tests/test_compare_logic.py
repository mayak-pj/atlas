from pathlib import Path

import pytest

from atlas.core.domain.photo_names import load_pattern
from atlas.features.compare.logic import (
    DEFAULT_DEFECT_KINDS, CompareModel, PhotoItem, counts_text, default_sn, grid_cells, load_defect_kinds, mark_label,
    mark_token, neighbor_indexes, photo_path, position_text, toggle_mark,
)
from atlas.shared.viewer.filmstrip import visible_range


def _model(total=10, count=1):
    model = CompareModel()
    model.set_photos([PhotoItem(number, "/папка/{}.jpg".format(number)) for number in range(total)])
    model.set_layout(count)
    return model


def test_portrait_windows_stand_in_a_row():
    for count in (1, 2, 3, 4):
        assert grid_cells(count, True) == [(0, column, 1, 1) for column in range(count)]


def test_landscape_grid_has_no_empty_cell():
    assert grid_cells(2, False) == [(0, 0, 1, 1), (0, 1, 1, 1)]
    assert grid_cells(3, False) == [(0, 0, 2, 1), (0, 1, 1, 1), (1, 1, 1, 1)]
    assert grid_cells(4, False) == [(0, 0, 1, 1), (0, 1, 1, 1), (1, 0, 1, 1), (1, 1, 1, 1)]


def test_flip_moves_only_active_window_and_stops_at_edges():
    model = _model(count=3)
    before = model.index(1)
    assert model.flip(1)
    assert model.index(0) == 1
    assert model.index(1) == before
    model.set_active(1)
    assert model.flip(-1)
    assert model.index(1) == before - 1
    assert model.index(0) == 1
    first = _model()
    assert not first.flip(-1)
    assert first.index(0) == 0
    last = _model(total=2)
    assert last.flip(1)
    assert not last.flip(1)


def test_reference_does_not_change_when_flipping():
    model = _model(count=2)
    reference = model.reference
    model.flip(3)
    assert model.reference is reference
    assert model.current(0).id == 3


def test_new_windows_continue_after_active_photo_kept():
    model = _model()
    model.flip(4)
    model.set_layout(4)
    assert [model.index(window) for window in range(4)] == [4, 5, 6, 7]  # без эталона все 4 окна — текущая папка
    model.set_active(3)
    model.set_layout(2)
    assert model.active == 1
    assert model.index(0) == 4


def test_windows_stop_at_last_photo():
    model = _model(total=2, count=4)
    assert [model.index(window) for window in range(4)] == [0, 1, 1, 1]


def test_empty_folder_is_safe():
    model = _model(total=0, count=2)
    assert model.reference is None
    assert model.current(0) is None
    assert not model.flip(1)


@pytest.mark.parametrize("count", [0, 5])
def test_only_one_to_four_windows(count):
    with pytest.raises(ValueError):
        CompareModel().set_layout(count)


def test_reference_takes_a_window_only_when_set():
    model = _model(count=2)
    assert model.currents_count == 2 and not model.reference_window and model.reference is None
    model.set_active(1)
    model.set_reference(PhotoItem(None, "/эталон.jpg"))  # эталон занял окно: текущих одно
    assert model.reference_window and model.currents_count == 1 and model.active == 0
    with pytest.raises(ValueError):
        model.set_active(1)
    model.set_layout(1)
    assert not model.reference_window and model.currents_count == 1  # при одном окне эталон только в «мигалке»


def test_photo_path_and_position():
    assert Path(photo_path("/сеть/Папка", "Тип 1/001.jpg")).parts[-2:] == ("Тип 1", "001.jpg")  # разделитель зависит от ОС
    assert position_text(2, 486) == "3 / 486"


def test_neighbors_follow_direction_and_stay_inside_folder():
    assert neighbor_indexes(5, 10, 1) == [6, 7, 4]
    assert neighbor_indexes(5, 10, -1) == [4, 3, 6]
    assert neighbor_indexes(9, 10, 1) == [8]
    assert neighbor_indexes(0, 1, 1) == []


def test_go_remembers_direction_and_clamps():
    model = _model()
    assert model.go(5)
    assert model.direction == 1
    assert model.go(2)
    assert model.direction == -1
    assert model.go(99)
    assert model.active_index == 9
    assert not model.go(9)


def test_mark_tokens():
    assert mark_token(None) is None
    assert mark_token("type:1") == "ok"
    assert mark_token("type:2") == "type2"
    assert mark_token("type:3") == mark_token("type:7") == "type3"
    assert mark_token("defect") == "defect"
    assert mark_token("remark") == "remark"
    assert mark_token("странное") is None


def test_visible_range_centres_and_stops_at_edges():
    assert visible_range(50, 486, 9) == (46, 55)
    assert visible_range(0, 486, 9) == (0, 9)
    assert visible_range(485, 486, 9) == (477, 486)
    assert visible_range(1, 3, 9) == (0, 3)
    assert visible_range(0, 3, 0) == (0, 1)


# --- отметки (шаг 3.4) -----------------------------------------------------------
DATA = Path(__file__).resolve().parents[4] / "data"


def _item(name, number=1, mark=None, sn=None):
    return PhotoItem(number, "C:/папка/" + name, mark, sn)


def test_toggle_mark():
    assert toggle_mark(None, "defect") == "defect"
    assert toggle_mark("defect", "defect") is None
    assert toggle_mark("type:1", "type:2") == "type:2"


def test_mark_labels():
    assert [mark_label(m) for m in ("type:1", "type:12", "defect", "remark")] == ["Тип 1", "Тип 12", "Дефект", "Замечание"]


def test_default_sn_prefers_saved_then_name_then_empty():
    pattern = load_pattern(DATA)
    assert default_sn(_item("0402290000836_1_XZ79070.jpg"), pattern) == "XZ79070"
    assert default_sn(_item("0402290000836_1_XZ79070.jpg", sn="ИСПРАВЛЕНО"), pattern) == "ИСПРАВЛЕНО"
    assert default_sn(_item("фото 001.jpg"), pattern) == ""


def test_counts_text_lists_only_used_marks_in_key_order():
    photos = [_item("a.jpg", 1, "defect"), _item("b.jpg", 2, "type:1"), _item("c.jpg", 3, "type:1"), _item("d.jpg", 4)]
    keys = ["type:1", "type:2", "defect", "remark"]
    assert counts_text(photos, keys) == "Тип 1: 2 · Дефект: 1 · Без отметки: 1"
    assert counts_text([], keys) == "Без отметки: 0"


def test_model_set_mark_keeps_sn_unless_told():
    model = CompareModel()
    model.set_photos([_item("a.jpg", 1), _item("b.jpg", 2)])
    model.set_mark(0, "defect", "SN1", "Размытое фото")
    model.set_mark(0, "remark", None, None)  # None — SN остаётся, как в сервисе folders
    assert (model.photos[0].mark, model.photos[0].sn, model.photos[0].defect_kind) == ("remark", "SN1", None)
    model.set_mark(0, "defect", "", None)  # пустая строка — стереть
    assert model.photos[0].sn is None
    assert model.photos[1].mark is None


def test_defect_kinds_file_and_fallback(tmp_path):
    assert load_defect_kinds(DATA) and all(isinstance(kind, str) for kind in load_defect_kinds(DATA))
    assert load_defect_kinds(tmp_path) == DEFAULT_DEFECT_KINDS
    (tmp_path / "defect_kinds.json").write_text('{"kinds": [" Один ", "", "Два"]}', encoding="utf-8")
    assert load_defect_kinds(tmp_path) == ["Один", "Два"]


def test_neighbor_since_by_year_days_or_unlimited():
    from datetime import date
    from atlas.features.compare.logic import neighbor_since
    today = date(2026, 11, 1)
    assert neighbor_since(today, True, 30) == "2026-01-01"
    assert neighbor_since(today, False, 30) == "2026-10-02"
    assert neighbor_since(today, False, 0) is None


def test_reference_angles_first_photo_of_each_angle_and_unparsed_skipped():
    from atlas.features.compare.logic import reference_angles
    names = ["0402_1_AA.jpg", "0402_1_BB.jpg", "левый файл.jpg", "0402_3_AA.jpg", "0402_2_AA.jpg"]
    photos = [PhotoItem(number, "/п/" + name) for number, name in enumerate(names)]
    assert reference_angles(photos) == {1: 0, 2: 4, 3: 3}
    assert reference_angles([PhotoItem(1, "/п/а.jpg")]) == {}


def test_reference_folder_is_flipped_only_when_active_and_stops_at_edges():
    model = _model(5, 2)
    refs = [PhotoItem(100 + number, "/чужая/{}.jpg".format(number)) for number in range(3)]
    model.set_reference_folder(refs)
    assert model.reference is refs[0]
    model.set_reference_active(True)
    assert model.flip(1) and model.flip(1) and not model.flip(1)
    assert model.reference is refs[2] and model.ref_index == 2
    assert model.active_index == 0  # текущая папка не двигалась
    assert model.flip(-1) and model.direction == -1 and model.reference is refs[1]
    model.set_active(0)  # клик по текущему окну
    assert not model.reference_active and model.flip(1) and model.active_index == 1 and model.reference is refs[1]


def test_reference_cannot_be_active_without_folder_or_in_layout_1():
    model = _model(5, 2)
    model.set_reference_active(True)
    assert not model.reference_active  # одиночный эталон не листается
    model.set_reference_folder([PhotoItem(1, "/чужая/1.jpg"), PhotoItem(2, "/чужая/2.jpg")])
    model.set_reference_active(True)
    model.set_layout(1)
    assert not model.reference_active
    model.set_reference_active(True)
    assert not model.reference_active
    with pytest.raises(ValueError):
        model.set_reference_folder([])


def test_new_folder_and_single_reference_forget_found_folder():
    model = _model(5, 2)
    model.set_reference_folder([PhotoItem(1, "/чужая/1.jpg"), PhotoItem(2, "/чужая/2.jpg")])
    model.set_reference_active(True)
    model.set_photos([PhotoItem(7, "/новая/7.jpg")])
    assert not model.has_reference_folder and not model.reference_active and model.reference is None
