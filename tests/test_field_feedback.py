"""Правки по отчёту с целевой машины: поворот папки со снимками разной ориентации, замечание вместо дефекта, цвет типа 3, большое фото в базе типов."""
import sqlite3
from pathlib import Path

import pytest
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtTest import QTest

from atlas.core import theme
from atlas.features.compare.logic import PhotoItem, shown_portrait, turn_angle
from atlas.features.compare.screen import UpwardComboBox
from atlas.features.type_db.photo_window import PhotoWindow
from atlas.shared.viewer.decode import read_size

from tests.test_compare_flow import App
from tests.test_rotation import FakeCache

MIGRATION = Path("atlas/core/domain/migrations/004_defect_to_remark.sql")
PORTRAIT, LANDSCAPE = (300, 450), (450, 300)


def photos(*rotations):
    return [PhotoItem(number, "{}_1_S{}.jpg".format(1, number), rotation=rotation) for number, rotation in enumerate(rotations)]


def test_shown_portrait_counts_our_rotation():
    assert shown_portrait(PORTRAIT, 0) and shown_portrait(PORTRAIT, 180)
    assert not shown_portrait(PORTRAIT, 90) and shown_portrait(LANDSCAPE, 270)


def test_turn_touches_only_photos_standing_like_the_current_one():
    items = photos(0, 0, 0)
    sizes = {0: PORTRAIT, 1: LANDSCAPE, 2: PORTRAIT}
    assert turn_angle(items, 0, 90, None, sizes) == {0: 90, 2: 90}
    assert [item.rotation for item in items] == [90, 0, 90]


def test_after_the_first_turn_the_whole_folder_stands_the_same_and_turns_together():
    items = photos(0, 0)
    sizes = {0: PORTRAIT, 1: LANDSCAPE}
    turn_angle(items, 0, 90, None, sizes)
    assert not shown_portrait(sizes[0], items[0].rotation) and not shown_portrait(sizes[1], items[1].rotation)
    assert turn_angle(items, 1, 90, None, sizes) == {0: 180, 1: 90}


def test_turn_keeps_each_photo_own_rotation_and_survives_unknown_sizes():
    items = photos(180, 0, 0)
    assert turn_angle(items, 0, 90, None, {0: PORTRAIT, 1: PORTRAIT}) == {0: 270, 1: 90}  # файл 2 не прочитан: не трогаем
    items = photos(0, 0)
    assert turn_angle(items, 0, 90, None, {}) == {0: 90}


def test_read_size_takes_only_the_header(tmp_path):
    path = tmp_path / "фото.jpg"
    image = QImage(40, 60, QImage.Format_RGB32)
    image.fill(QColor("#808080"))
    assert image.save(str(path), "JPEG")
    assert read_size(path) == (40, 60)
    assert read_size(tmp_path / "нет.jpg") is None


@pytest.fixture
def mixed(tmp_path, qtbot):
    app = App(tmp_path, qtbot, count=2, size=PORTRAIT, names=["1_1_A.jpg", "1_1_B.jpg", "1_1_C.jpg"], features=("compare",))
    wide = QImage(LANDSCAPE[0], LANDSCAPE[1], QImage.Format_RGB32)
    wide.fill(QColor("#808080"))
    folders = app.ctx.services.get("folders")
    assert wide.save(str(app.path / "1_1_C.jpg"), "JPEG")
    folders.add_photos(app.folder.id, ["1_1_C.jpg"])
    yield app
    app.stop()


def _rotations(app):
    return {photo.rel_path: photo.rotation for photo in app.ctx.services.get("folders").photos(app.folder.id)}


def test_page_key_leaves_differently_shot_photos_alone_and_shift_turns_one(mixed):
    app = mixed
    app.wait_open()
    app.press(Qt.Key_PageDown)
    app.qtbot.waitUntil(lambda: _rotations(app)["1_1_A.jpg"] == 90, timeout=5000)
    app.qtbot.waitUntil(lambda: _rotations(app)["1_1_B.jpg"] == 90, timeout=5000)
    assert _rotations(app)["1_1_C.jpg"] == 0
    QTest.keyClick(app.screen, Qt.Key_PageDown, Qt.ShiftModifier)
    app.qtbot.waitUntil(lambda: _rotations(app)["1_1_A.jpg"] == 180, timeout=5000)
    assert _rotations(app)["1_1_B.jpg"] == 90 and _rotations(app)["1_1_C.jpg"] == 0


def test_turn_pressed_before_sizes_arrive_is_applied_afterwards(mixed):
    app = mixed
    app.wait_open()
    screen = app.screen
    screen.expect_sizes()
    app.press(Qt.Key_PageDown)
    assert screen.model.photos[0].rotation == 0 and screen.marks_status.text()
    screen.set_sizes({photo.path: PORTRAIT for photo in screen.model.photos})
    assert screen.model.photos[0].rotation == 90 and not screen.marks_status.text()


def test_no_defect_button_and_kind_is_saved_with_remark(tmp_path, qtbot):
    app = App(tmp_path, qtbot, names=["1_1_A.jpg", "1_1_B.jpg", "1_1_C.jpg", "1_1_D.jpg", "1_1_E.jpg", "1_1_F.jpg"])
    try:
        app.wait_open()
        screen = app.screen
        assert "defect" not in screen.mark_buttons
        app.press(Qt.Key_D)
        QTest.qWait(50)
        assert not screen.mark_buttons["remark"].isChecked()
        app.press(Qt.Key_R)
        qtbot.waitUntil(lambda: screen.defect_box.isVisibleTo(screen), timeout=5000)
        screen.kind_box.setCurrentIndex(1)
        screen.kind_box.activated.emit(1)
        folders = app.ctx.services.get("folders")
        qtbot.waitUntil(lambda: folders.photos(app.folder.id)[0].defect_kind == screen.kind_box.itemData(1), timeout=5000)
        assert folders.photos(app.folder.id)[0].sn == "A"
    finally:
        app.stop()


def test_kind_list_opens_upwards(qtbot):
    box = UpwardComboBox()
    box.addItems(["один", "два", "три"])
    qtbot.addWidget(box)
    box.move(300, 500)
    box.show()
    box.showPopup()
    popup = box.view().window()
    assert popup.y() + popup.height() <= box.mapToGlobal(QPoint(0, 0)).y()
    box.hidePopup()


def test_migration_turns_defects_into_remarks_and_keeps_kind():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE photos (id INTEGER, mark TEXT, defect_kind TEXT)")
    conn.execute("INSERT INTO photos VALUES (1, 'defect', 'Размытое фото'), (2, 'type:2', NULL)")
    conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    assert conn.execute("SELECT mark, defect_kind FROM photos ORDER BY id").fetchall() == [("remark", "Размытое фото"), ("type:2", None)]


def test_each_type_has_its_own_color_in_both_themes():
    for name in ("tokens.json", "tokens_light.json"):
        text = (Path("atlas/core/theme") / name).read_text(encoding="utf-8")
        assert '"type3":' in text and '"type3_soft":' in text
    assert theme.current().color("type2") != theme.current().color("type3")


def test_photo_window_zooms_and_shows_the_file(qtbot, tmp_path):
    cache = FakeCache()
    window = PhotoWindow(cache, str(tmp_path / "Тип 1_photo.jpg"))
    qtbot.addWidget(window)
    window.show()
    assert window.windowTitle() == "Тип 1_photo.jpg" and window.view.path == str(tmp_path / "Тип 1_photo.jpg")
    window.view.zoom_by(2.0)
    assert window.view.state()[0] == pytest.approx(2.0)
