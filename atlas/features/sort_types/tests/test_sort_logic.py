from pathlib import Path

from atlas.core.domain.folders import Photo
from atlas.features.sort_types.logic import DEFAULT_TEMPLATE, confirm_text, folder_name, load_template, plan_moves

DATA = Path(__file__).resolve().parents[4] / "data"


def _photo(number, rel, mark):
    return Photo(number, 1, rel, None, mark, None, None)


def test_folder_name():
    assert folder_name("type:2", "Тип {n}") == "Тип 2"
    assert folder_name("type:12", "Type {n}") == "Type 12"
    assert [folder_name(m, "Тип {n}") for m in ("defect", "remark", None)] == [None] * 3


def test_plan_moves_only_typed_photos_outside_their_folder():
    photos = [
        _photo(1, "a.jpg", "type:1"),
        _photo(2, "b.jpg", "type:2"),
        _photo(3, "c.jpg", "defect"),
        _photo(4, "d.jpg", None),
        _photo(5, "Тип 1/e.jpg", "type:1"),  # уже на месте
        _photo(6, "Тип 1/f.jpg", "type:2"),  # тип поменяли после раскладки
        _photo(7, "другая/g.jpg", "type:1"),  # имя сохраняется, вложенность нет
        _photo(8, "тип 1/h.jpg", "type:1"),  # регистр не важен
    ]
    plan = plan_moves(photos, "Тип {n}")
    assert [(m.photo_id, m.to_rel) for m in plan.moves] == [
        (1, "Тип 1/a.jpg"), (2, "Тип 2/b.jpg"), (6, "Тип 2/f.jpg"), (7, "Тип 1/g.jpg"),
    ]
    assert plan.per_folder == {"Тип 1": 2, "Тип 2": 2}
    assert (plan.in_place, plan.not_typed, plan.conflicts) == (2, 2, [])


def test_same_name_into_one_folder_is_a_conflict():
    plan = plan_moves([_photo(1, "a/x.jpg", "type:1"), _photo(2, "b/X.JPG", "type:1")], "Тип {n}")
    assert [m.photo_id for m in plan.moves] == [1] and plan.conflicts == ["b/X.JPG"]


def test_confirm_text_mentions_counts_and_undo():
    plan = plan_moves([_photo(1, "a.jpg", "type:1"), _photo(2, "b.jpg", None)], "Тип {n}")
    text = confirm_text(plan)
    assert "1 фото" in text and "Тип 1 — 1" in text and "Без отметки типа (1)" in text and "отменить" in text


def test_template_from_file_and_fallbacks(tmp_path):
    assert load_template(DATA) == "Тип {n}"
    assert load_template(tmp_path) == DEFAULT_TEMPLATE
    for bad in ('{"template": "Тип"}', '{"template": "{x}"}', '{"template": 5}', "не json"):
        (tmp_path / "type_folders.json").write_text(bad, encoding="utf-8")
        assert load_template(tmp_path) == DEFAULT_TEMPLATE
