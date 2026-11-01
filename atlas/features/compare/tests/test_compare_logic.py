import pytest

from atlas.features.compare.logic import (
    CompareModel, PhotoItem, grid_cells, mark_token, neighbor_indexes, photo_path, position_text,
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
    assert [model.index(window) for window in range(3)] == [4, 5, 6]
    model.set_active(2)
    model.set_layout(2)
    assert model.active == 0
    assert model.index(0) == 4


def test_windows_stop_at_last_photo():
    model = _model(total=2, count=4)
    assert [model.index(window) for window in range(3)] == [0, 1, 1]


def test_empty_folder_is_safe():
    model = _model(total=0, count=2)
    assert model.reference is None
    assert model.current(0) is None
    assert not model.flip(1)


@pytest.mark.parametrize("count", [0, 5])
def test_only_one_to_four_windows(count):
    with pytest.raises(ValueError):
        CompareModel().set_layout(count)


def test_reference_window_cannot_be_active():
    with pytest.raises(ValueError):
        _model(count=2).set_active(1)


def test_photo_path_and_position():
    assert photo_path("/сеть/Папка", "Тип 1/001.jpg").endswith("Тип 1/001.jpg")
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
    assert mark_token("type:2") == mark_token("type:7") == "type2"
    assert mark_token("defect") == "defect"
    assert mark_token("remark") == "remark"
    assert mark_token("странное") is None


def test_visible_range_centres_and_stops_at_edges():
    assert visible_range(50, 486, 9) == (46, 55)
    assert visible_range(0, 486, 9) == (0, 9)
    assert visible_range(485, 486, 9) == (477, 486)
    assert visible_range(1, 3, 9) == (0, 3)
    assert visible_range(0, 3, 0) == (0, 1)
