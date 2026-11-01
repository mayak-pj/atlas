"""Логика «Ракурсов»: группировка, пропуски, чужие имена, повторы, листание."""
from atlas.features.compare.angles import AnglesModel, build_plan, notes, set_mark
from atlas.features.compare.logic import MAX_WINDOWS, PhotoItem


def items(*names):
    return [PhotoItem(number + 1, "/сеть/{}".format(name)) for number, name in enumerate(names)]


def test_groups_by_article_and_sn_sorted():
    plan = build_plan(items("11_1_B.jpg", "11_2_B.jpg", "11_1_A.jpg", "22_1_A.jpg", "11_2_A.jpg"))
    assert [(item.article, item.sn) for item in plan.sets] == [("11", "A"), ("11", "B"), ("22", "A")]
    assert plan.sets[0].photos == {1: 2, 2: 4}
    assert plan.views == [1, 2]


def test_missing_angle_does_not_skip_sn():
    model = AnglesModel()
    model.set_photos(items("1_1_A.jpg", "1_2_A.jpg", "1_2_B.jpg"))
    assert model.total == 2
    model.go(1)
    assert model.photo_in(0) is None and model.photo_in(1) == 2


def test_more_than_four_angles_are_counted_not_shown():
    plan = build_plan(items(*["1_{}_A.jpg".format(view) for view in (6, 5, 4, 3, 2, 1)]))
    assert plan.views == [1, 2, 3, 4] and len(plan.views) == MAX_WINDOWS
    assert plan.hidden == 2
    assert notes(plan) == ["Ещё ракурсов: 2"]


def test_unparsed_are_counted_and_absent():
    plan = build_plan(items("IMG_1.jpg", "скан.jpg", "1_1_A.jpg"))
    assert plan.unparsed == 2 and len(plan.sets) == 1
    assert "2" in notes(plan)[0]


def test_repeat_shows_first_by_name_and_warns_with_names():
    plan = build_plan(items("1_1_A_z.jpg", "1_1_A.jpg", "1_2_A.jpg"))
    assert plan.sets[0].photos[1] == 1  # «1_1_A.jpg» раньше по имени, хотя в папке второй
    assert plan.repeats == [["1_1_A.jpg", "1_1_A_z.jpg"]]
    assert "1_1_A.jpg, 1_1_A_z.jpg" in notes(plan)[0]


def test_many_repeats_are_cut_in_note():
    names = []
    for sn in "ABCDE":
        names += ["1_1_{}.jpg".format(sn), "1_1_{}_x.jpg".format(sn)]
    text = notes(build_plan(items(*names)))[0]
    assert "1_1_C.jpg" in text and "1_1_D.jpg" not in text and "ещё повторов: 2" in text


def test_go_stops_at_edges_and_remembers_direction():
    model = AnglesModel()
    model.set_photos(items("1_1_A.jpg", "1_1_B.jpg"))
    assert not model.go(-1)
    assert model.go(1) and model.direction == 1
    assert not model.go(5)
    assert model.go(0) and model.direction == -1


def test_show_photo_finds_sn_and_window():
    model = AnglesModel()
    model.set_photos(items("1_1_A.jpg", "1_1_B.jpg", "1_2_B.jpg", "чужое.jpg"))
    model.show_photo(2)
    assert (model.index, model.active) == (1, 1)
    model.show_photo(3)  # имя не разобрано: остаёмся где были
    assert (model.index, model.active) == (1, 1)


def test_neighbor_photos_are_all_shown_angles_of_neighbor_sns():
    names = ["1_{}_{}.jpg".format(view, sn) for sn in "ABCD" for view in (1, 2)]
    model = AnglesModel()
    model.set_photos(items(*names))
    model.go(1)
    # вперёд два SN, назад один; по два ракурса на каждый
    assert model.neighbor_photos() == [4, 5, 6, 7, 0, 1]


def test_neighbor_photos_skip_hidden_angles():
    names = ["1_{}_A.jpg".format(view) for view in range(1, 6)] + ["1_5_B.jpg", "1_1_B.jpg"]
    model = AnglesModel()
    model.set_photos(items(*names))
    assert model.neighbor_photos() == [6]


def test_empty_folder():
    model = AnglesModel()
    model.set_photos([])
    assert model.current is None and model.active_photo() is None and not model.go(1) and notes(model.plan) == []


def test_strip_mark_priority():
    photos = [PhotoItem(1, "1_1_A.jpg", "remark"), PhotoItem(2, "1_2_A.jpg", "type:2"), PhotoItem(3, "1_3_A.jpg", "defect")]
    angle_set = build_plan(photos).sets[0]
    assert set_mark(angle_set, photos) == "defect"
    assert set_mark(angle_set, photos, [1, 2]) == "type:2"
    assert set_mark(angle_set, photos, [1]) == "remark"
    assert set_mark(angle_set, [PhotoItem(1, "a"), PhotoItem(2, "b"), PhotoItem(3, "c")]) is None
