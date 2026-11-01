"""Тестовые данные: база по макету и настоящие JPEG."""
from datetime import date
from pathlib import Path

from PyQt5.QtGui import QImageReader

from atlas.core.domain.folders import FoldersService
from atlas.core.domain.parts import PartsService
from atlas.core.domain.users import UsersService
from atlas.features.compare.angles import build_plan
from atlas.features.compare.logic import PhotoItem
from samples import photos
from samples.seed import _pick_marks, seed

TODAY = date(2026, 10, 31)


def _seed(out):
    return seed(out, limit=4, width=120, height=180, today=TODAY, log=lambda text: None)


def test_seed_matches_mockup_and_is_repeatable(qapp, tmp_path):
    out = tmp_path / "Тест данные"
    db = _seed(out)
    _seed(out)
    folders = FoldersService(db)
    assert len(UsersService(db).all()) == 5
    assert {part.kind for part in PartsService(db).all()} == {"A", "B"}
    recent = folders.recent()
    assert len(recent) == 12
    assert len(folders.recent(status="new")) == 8
    assert len(folders.recent(status="done")) == 3
    assert sorted(len(folders.photos(f.id)) for f in recent) == [3, 4, 4, 4, 4, 4, 4, 4, 4, 6, 7, 8]  # 3, 6, 7, 8 — «Ракурсы»
    assert all((out / "photos") in Path(f.path).parents for f in recent)
    for folder in recent:
        for photo in folders.photos(folder.id):
            reader = QImageReader(str(Path(folder.path) / photo.rel_path))
            assert reader.size().width() == 120
    done = folders.recent(status="done")
    assert all(f.status_at.startswith("2026-10-") for f in done)  # дата из прошлого, а не «сейчас»
    counts = folders.counts([f.id for f in done])
    assert sorted(item.get("defect", 0) for item in counts.values()) == [0, 0, 1]
    assert sorted(item.get("type:2", 0) for item in counts.values()) == [0, 0, 2]


def test_seed_has_angle_folders(qapp, tmp_path):
    """Набор для «Ракурсов»: 1, 2, 3 и больше 4 ракурсов, пропуски, чужие имена, повтор."""
    db = _seed(tmp_path / "out")
    folders = FoldersService(db)
    plans = {}
    for folder in folders.recent():
        items = [PhotoItem(photo.id, photo.rel_path) for photo in folders.photos(folder.id)]
        plans[PartsService(db).get(folder.part_id).name] = build_plan(items)
    assert plans["Плата один ракурс"].views == [1]
    two = plans["Плата две стороны"]
    assert two.views == [1, 2] and [sorted(item.photos) for item in two.sets] == [[1, 2], [1], [2], [1, 2]]  # по SN, с пропусками
    three = plans["Плата три стороны и чужие имена"]
    assert three.views == [1, 2, 3] and three.unparsed == 2 and three.repeats == [["300300_1_EF0002.jpg", "300300_1_EF0002_x.jpg"]]
    many = plans["Плата пять ракурсов"]
    assert many.views == [1, 2, 3, 4] and many.hidden == 1


def test_pick_marks_stops_at_folder_size():
    assert _pick_marks({"type:1": 2, "defect": 2}, 3) == [("type:1", 0), ("type:1", 1), ("defect", 2)]
    assert _pick_marks(None, 3) == []


def test_type_two_differs_from_type_one(qapp):
    one = photos.draw_photo("ssd", 1, "А", "x", 120, 180)
    two = photos.draw_photo("ssd", 2, "А", "x", 120, 180)
    assert one.size() == two.size()
    # Шум случайный, поэтому сравниваем с заметным порогом центр платы, где лежит лишний чип
    assert sum(abs(one.pixelColor(60 + d, 90).lightness() - two.pixelColor(60 + d, 90).lightness()) for d in range(-5, 5)) > 50


def test_full_size_photo(qapp, tmp_path):
    path = tmp_path / "фото.jpg"
    assert photos.save_photo(path, "board", 2, "Деталь · SN1", "a")
    reader = QImageReader(str(path))
    assert (reader.size().width(), reader.size().height()) == (3456, 5184)
    size_mb = path.stat().st_size / 1024 / 1024
    assert 5 <= size_mb <= 15, size_mb
