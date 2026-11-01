"""Разбор имён фото: настоящие примеры из docs/OPEN_ITEMS.md и шаблон из data/photo_names.json."""
from pathlib import Path

import pytest

from atlas.core.domain.photo_names import PhotoName, compile_pattern, load_pattern, parse_photo_name

DATA = Path(__file__).resolve().parent.parent / "data"

REAL = [
    ("0402290000836_1_XZ79070", PhotoName("0402290000836", 1, "XZ79070")),
    ("0211040001792_1_WFL8GKHR_2", PhotoName("0211040001792", 1, "WFL8GKHR")),
    ("0224010000852_1_YZ62718", PhotoName("0224010000852", 1, "YZ62718")),
    ("0211260000555_1_2512054247_4", PhotoName("0211260000555", 1, "2512054247")),
    ("0211110001572_1_406HDWE178622_2", PhotoName("0211110001572", 1, "406HDWE178622")),
]


@pytest.fixture(scope="module")
def pattern():
    return load_pattern(DATA)


@pytest.mark.parametrize("stem, expected", REAL)
def test_real_names(pattern, stem, expected):
    assert parse_photo_name(stem + ".jpg", pattern) == expected
    assert parse_photo_name(stem, pattern) == expected  # без расширения


def test_view_is_a_number_of_any_length(pattern):
    assert parse_photo_name("1_12_A.JPG", pattern) == PhotoName("1", 12, "A")


def test_ending_does_not_change_the_pair(pattern):
    assert parse_photo_name("1_2_AB_7.jpg", pattern) == parse_photo_name("1_2_AB.jpg", pattern)


@pytest.mark.parametrize("name", ["IMG_0001.jpg", "фото 001.jpg", "123_1.jpg", "abc_1_SN.jpg", "123_x_SN.jpg", "1_1_a_b_c.jpg", ""])
def test_foreign_names_are_not_parsed(pattern, name):
    assert parse_photo_name(name, pattern) is None


def test_default_pattern_matches_the_file(pattern):
    for stem, expected in REAL:
        assert parse_photo_name(stem) == expected


def test_broken_data_file_falls_back(tmp_path, caplog):
    (tmp_path / "photo_names.json").write_text('{"pattern": "(("}', encoding="utf-8")
    assert parse_photo_name("1_1_A.jpg", load_pattern(tmp_path)) == PhotoName("1", 1, "A")
    assert parse_photo_name("1_1_A.jpg", load_pattern(tmp_path / "нет")) == PhotoName("1", 1, "A")


def test_pattern_without_groups_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        compile_pattern(r"^(?P<article>\d+)$")
    (tmp_path / "photo_names.json").write_text('{"pattern": "^(?P<article>\\\\d+)$"}', encoding="utf-8")
    assert parse_photo_name("1_1_A.jpg", load_pattern(tmp_path)) == PhotoName("1", 1, "A")


def test_cyrillic_folder_and_unc_paths_are_fine(pattern):
    assert parse_photo_name(r"\\сервер\общая\папка\0402290000836_1_XZ79070.jpg", pattern).sn == "XZ79070"
