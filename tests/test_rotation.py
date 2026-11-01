"""Поворот фото: математика, окно просмотра, лента, база, «Сравнение» и «Ракурсы» в настоящем приложении."""
import sqlite3

import pytest
from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter

from atlas.features.compare.logic import CompareModel, PhotoItem, next_rotation, same_angle
from atlas.shared.viewer.filmstrip import FilmItem, Filmstrip
from atlas.shared.viewer.levels import L0, L1, level_for_scale
from atlas.shared.viewer.memory_cache import CachedImage
from atlas.shared.viewer.photo_view import PhotoView
from atlas.shared.viewer.sync_group import SyncGroup
from atlas.shared.viewer.view_state import rotated_center, rotated_size

from tests.test_compare_flow import App

RED = QColor("#FF0000")


def picture(width=864, height=1296):
    """Серое фото с красным квадратом в левом верхнем углу: по нему видно, куда повернулось."""
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor("#404040"))
    painter = QPainter(image)
    painter.fillRect(0, 0, width // 4, height // 4, RED)
    painter.end()
    return image


class FakeCache(QObject):
    ready = pyqtSignal(str, int, QImage)
    failed = pyqtSignal(str, int, str)

    def __init__(self):
        super().__init__()
        self.memory = {}

    def peek(self, path, level):
        return self.memory.get((path, level))

    def get(self, path, level, priority=0, exact=False):
        return self.memory.get((path, level))

    def cancel_pending(self):
        pass


@pytest.fixture
def cache():
    instance = FakeCache()
    instance.memory[("a", L1)] = CachedImage(picture(), L1)
    instance.memory[("b", L1)] = CachedImage(picture(1296, 864), L1)
    return instance


def make_view(qtbot, cache, width=600, height=600):
    view = PhotoView(cache, settle_ms=0)
    qtbot.addWidget(view)
    view.resize(width, height)
    view.show()
    return view


def red_corner(view):
    """В какой четверти окна красный квадрат: (право?, низ?)."""
    image = view.grab().toImage()
    xs, ys = [], []
    for x in range(0, image.width(), 6):
        for y in range(0, image.height(), 6):
            color = image.pixelColor(x, y)
            if color.red() > 200 and color.green() < 60:
                xs.append(x)
                ys.append(y)
    assert xs, "красного квадрата нет на экране"
    return sum(xs) / len(xs) > image.width() / 2, sum(ys) / len(ys) > image.height() / 2


# --- математика ---------------------------------------------------------------
def test_four_turns_return_to_start():
    rotation = 0
    seen = []
    for _ in range(4):
        rotation = next_rotation(rotation, 90)
        seen.append(rotation)
    assert seen == [90, 180, 270, 0]
    assert next_rotation(0, -90) == 270


def test_center_follows_the_photo():
    assert rotated_center(0.2, 0.3, 90) == pytest.approx((0.7, 0.2))
    assert rotated_center(0.2, 0.3, 180) == pytest.approx((0.8, 0.7))
    assert rotated_center(0.2, 0.3, 270) == pytest.approx((0.3, 0.8))
    assert rotated_center(*rotated_center(0.2, 0.3, 90), -90) == pytest.approx((0.2, 0.3))
    assert rotated_size(3, 5, 90) == (5, 3)
    assert rotated_size(3, 5, 180) == (3, 5)


# --- окно ---------------------------------------------------------------------
def test_corner_goes_clockwise_and_four_turns_give_same_pixels(qtbot, cache):
    view = make_view(qtbot, cache)
    view.set_photo("a")
    before = view.grab().toImage()
    assert red_corner(view) == (False, False)
    corners = []
    for rotation in (90, 180, 270):
        view.set_rotation(rotation)
        corners.append(red_corner(view))
    assert corners == [(True, False), (True, True), (False, True)]
    view.set_rotation(0)
    assert view.grab().toImage() == before


def test_rotation_keeps_the_point_in_center_and_zoom(qtbot, cache):
    view = make_view(qtbot, cache)
    view.set_photo("a")
    view.set_state(6.0, 0.3, 0.4)
    signals = []
    view.view_changed.connect(lambda *args: signals.append(args))
    view.set_rotation(90)
    assert view.state() == pytest.approx((6.0, 0.6, 0.3))
    assert view.shown_image_size == (1296, 864)
    assert signals == []  # это не движение мышью
    for rotation in (180, 270, 0):
        view.set_rotation(rotation)
    assert view.state() == pytest.approx((6.0, 0.3, 0.4))


def test_photo_keeps_own_rotation_and_place_on_screen_when_listing(qtbot, cache):
    view = make_view(qtbot, cache)
    view.set_photo("a", 90)
    view.set_state(6.0, 0.3, 0.4)
    view.set_photo("b", 0)
    assert view.rotation == 0
    assert view.shown_image_size == (1296, 864)
    assert view.state() == pytest.approx((6.0, 0.3, 0.4))


def test_old_picture_keeps_its_rotation_until_new_one_arrives(qtbot, cache):
    view = make_view(qtbot, cache)
    view.set_photo("a", 90)
    assert red_corner(view) == (True, False)
    view.set_photo("not loaded yet", 0)
    assert red_corner(view) == (True, False)
    assert view.shown_image_size is None
    cache.ready.emit("not loaded yet", L1, picture())
    assert red_corner(view) == (False, False)


def test_needed_level_uses_rotated_size(qtbot, cache):
    """Чёткий уровень — по длинной стороне к длинной: иначе повёрнутому фото достался бы уровень больше нужного."""
    view = make_view(qtbot, cache, 900, 600)
    view.set_photo("a")
    view.set_rotation(90)
    for zoom in (1.0, 1.5, 2.0, 3.0, 5.0, 8.0):
        view.set_state(zoom, 0.5, 0.5)
        width, _height = view._state.displayed_size()
        assert view._needed_level() == level_for_scale(width * view.devicePixelRatioF() / (1296 * 4))


def test_group_rotates_together_and_returns_after_hitting_edge(qtbot, cache):
    group = SyncGroup(cache)
    first, second = make_view(qtbot, cache), make_view(qtbot, cache)
    group.add(first)
    group.add(second)
    first.set_photo("a")
    second.set_photo("a")
    group.set_state(1.3, 0.5, 0.45)  # при повороте окно упрётся в край
    expected = first.state()
    for rotation in (90, 180, 270, 0):
        group.rotate(90, [(first, rotation), (second, rotation)])
        assert first.state() == pytest.approx(second.state())
    assert first.state() == pytest.approx(expected)
    assert group.state == pytest.approx((1.3, 0.5, 0.45))
    group.set_state(6.0, 0.3, 0.4)
    group.rotate(90, [(first, 90), (second, 90)])
    assert group.state == pytest.approx((6.0, 0.6, 0.3))
    assert first.state() == pytest.approx((6.0, 0.6, 0.3))


# --- лента --------------------------------------------------------------------
def test_filmstrip_thumb_turns(qtbot):
    cache = FakeCache()
    cache.memory[("a", L0)] = CachedImage(picture(108, 162), L0)
    colors = {name: QColor("#000000") for name in ("border", "active", "empty", "text", "text_bg")}
    strip = Filmstrip(cache, colors)
    qtbot.addWidget(strip)
    strip.resize(400, 72)
    strip.set_items([FilmItem("a")])
    strip.request_visible()
    upright = strip._thumbs["a"]
    assert upright.height() > upright.width()
    strip.set_mark(0, QColor("#FF0000"))
    assert strip._items[0].rotation == 0
    strip.set_rotations([90])
    turned = strip._thumbs["a"]
    assert turned.width() > turned.height()
    strip.set_mark(0, None)
    assert strip._items[0].rotation == 90  # отметка не сбрасывает поворот


# --- модель -------------------------------------------------------------------
def photos(count=4):
    return [PhotoItem(number + 1, "{}.jpg".format(number)) for number in range(count)]


def angle_photos():
    names = ["1_1_A.jpg", "1_1_B.jpg", "1_2_A.jpg", "1_2_B.jpg", "чужое.jpg", "другое.jpg"]
    return [PhotoItem(number + 1, name) for number, name in enumerate(names)]


def test_same_angle_uses_view_from_name():
    photos = angle_photos()
    assert same_angle(photos, 0) == [0, 1]
    assert same_angle(photos, 3) == [2, 3]
    assert same_angle(photos, 4) == [4]  # имя не разобрано: только само фото


def test_model_turns_whole_angle_and_aligns_it():
    model = CompareModel()
    photos = angle_photos()
    photos[1] = PhotoItem(2, "1_1_B.jpg", rotation=180)  # старый поворот отдельного фото
    model.set_photos(photos)
    assert model.rotate_angle(0, 90) == {0: 90, 1: 90}
    assert [photo.rotation for photo in model.photos] == [90, 90, 0, 0, 0, 0]


def test_model_windows_turn_their_angles_and_reference_in_memory():
    model = CompareModel()
    model.set_photos(angle_photos())
    model.set_reference_folder([
        PhotoItem(100, "2_1_X.jpg", rotation=90), PhotoItem(101, "2_1_Y.jpg", rotation=90), PhotoItem(102, "2_2_X.jpg"),
    ])
    model.set_layout(3)  # в текущих окнах ракурс 1 — два фото одного ракурса
    assert model.rotate_windows(90) == {0: 90, 1: 90}
    assert model.reference.rotation == 180
    assert [photo.rotation for photo in model.ref_photos] == [180, 180, 0]  # весь ракурс эталона, другой — нет
    model.go(2)
    assert model.rotate_windows(90) == {2: 90, 3: 90, 0: 180, 1: 180}


def test_model_single_reference_turns_alone():
    model = CompareModel()
    model.set_photos(photos(1))
    model.set_layout(3)
    assert model.rotate_windows(90) == {0: 90}
    assert model.reference.rotation == 90


def test_mark_keeps_rotation():
    model = CompareModel()
    model.set_photos(photos())
    model.rotate_angle(0, 90)
    model.set_mark(0, "defect", "S", None)
    assert model.photos[0].rotation == 90


# --- база ---------------------------------------------------------------------
@pytest.fixture
def app(tmp_path, qtbot):
    names = ["1_1_A.jpg", "1_2_A.jpg", "1_1_B.jpg", "1_2_B.jpg"]
    instance = App(tmp_path, qtbot, count=len(names), names=names)
    instance.wait_open()
    instance.wait_shown()
    yield instance
    instance.stop()


def saved(app, qtbot, wanted):
    """Дождаться записи: {номер фото в папке: поворот}, остальные нули."""
    folders = app.ctx.services.get("folders")
    folder_id = app.feature.folder.id

    def check():
        rotations = [photo.rotation for photo in folders.photos(folder_id)]
        assert rotations == [wanted.get(number, 0) for number in range(len(rotations))]

    qtbot.waitUntil(check, timeout=3000)


def test_service_validates_and_stores(app):
    folders = app.ctx.services.get("folders")
    photo = folders.photos(app.feature.folder.id)[0]
    folders.mark_photo(photo.id, "remark")
    folders.set_rotation([photo.id], 270)
    again = folders.photos(app.feature.folder.id)[0]
    assert (again.rotation, again.mark) == (270, "remark")
    with pytest.raises(ValueError):
        folders.set_rotation([photo.id], 45)
    with pytest.raises(LookupError):
        folders.set_rotation([photo.id, 10 ** 6], 90)
    assert folders.photos(app.feature.folder.id)[0].rotation == 270  # не вышло — не меняется ни одно
    with pytest.raises(sqlite3.IntegrityError):
        app.ctx.db.write(lambda conn: conn.execute("UPDATE photos SET rotation = 45"))


def test_key_turns_whole_angle_saves_and_survives_reopening(app, qtbot):
    screen = app.screen
    assert [photo.name for photo in screen.model.photos] == ["1_1_A.jpg", "1_1_B.jpg", "1_2_A.jpg", "1_2_B.jpg"]
    app.press(Qt.Key_PageDown)
    assert screen.active_view().rotation == 90
    saved(app, qtbot, {0: 90, 1: 90})
    app.press(Qt.Key_Right)
    app.wait_shown()
    assert screen.active_view().rotation == 90  # следующее фото того же ракурса
    app.press(Qt.Key_Right)
    app.wait_shown()
    assert screen.active_view().rotation == 0  # другой ракурс
    assert [item.rotation for item in screen.strip._items] == [90, 90, 0, 0]
    app.feature.open_folder(app.feature.folder.id)
    qtbot.waitUntil(lambda: screen.model.active_index == 0 and screen.active_view().rotation == 90, timeout=3000)
    assert [photo.rotation for photo in screen.model.photos] == [90, 90, 0, 0]


def test_opposite_key_and_buttons(app, qtbot):
    app.press(Qt.Key_PageUp)
    assert app.screen.active_view().rotation == 270
    saved(app, qtbot, {0: 270, 1: 270})
    app.screen.rotate_right_button.click()
    assert app.screen.active_view().rotation == 0
    saved(app, qtbot, {})


def test_reference_turns_with_windows_but_is_not_saved(app, qtbot):
    screen = app.screen
    screen.set_layout(2)
    app.wait_shown()
    app.press(Qt.Key_Right)
    app.press(Qt.Key_Right)  # в текущем окне ракурс 2, эталон — первое фото, ракурс 1
    app.wait_shown()
    app.press(Qt.Key_PageDown)
    assert [view.rotation for view in screen.views[:2]] == [90, 90]
    saved(app, qtbot, {2: 90, 3: 90})  # ракурс эталона в базе не изменился


def test_flicker_shows_reference_with_its_rotation(app, qtbot):
    screen = app.screen
    app.press(Qt.Key_Right)
    app.wait_shown()
    app.press(Qt.Key_PageDown)
    view = screen.active_view()
    zoom, cx, cy = view.state()
    screen._begin_flicker()
    assert view.path == screen.model.reference.path
    assert view.rotation == 90
    assert view.state() == pytest.approx((zoom, cx, cy))
    screen.rotate(90)  # во время «мигалки» поворот не делает ничего
    assert view.rotation == 90
    screen._end_flicker()
    assert view.rotation == 90
    assert view.path == screen.model.photos[1].path


def test_grid_and_strip_follow_rotated_orientation(app, qtbot):
    screen = app.screen
    size = screen.active_view().shown_image_size
    before = size[1] >= size[0]
    assert screen._portrait == before
    app.press(Qt.Key_PageDown)
    assert screen._portrait == (not before)
    app.press(Qt.Key_PageUp)
    assert screen._portrait == before


def test_angles_turn_only_active_window(app, qtbot):
    screen = app.screen
    screen.set_angles_mode(True)
    app.wait_shown()
    first, second = screen.views[:2]
    before = second.state()
    app.press(Qt.Key_PageDown)
    assert (first.rotation, second.rotation) == (90, 0)
    assert second.state() == before
    saved(app, qtbot, {0: 90, 1: 90})
    app.press(Qt.Key_Right)  # следующий SN: тот же ракурс повёрнут, другой — нет
    assert (first.rotation, second.rotation) == (90, 0)


def test_rotation_failure_is_shown(app, qtbot, monkeypatch):
    folders = app.ctx.services.get("folders")

    def broken(photo_ids, rotation):
        raise OSError("нет сети")

    monkeypatch.setattr(folders, "set_rotation", broken)
    app.press(Qt.Key_PageDown)
    qtbot.waitUntil(lambda: "Поворот не сохранён" in app.screen.marks_status.text(), timeout=3000)
    assert app.screen.active_view().rotation == 90


def test_sync_zoom_and_pan_work_with_rotated_window(app, qtbot):
    screen = app.screen
    screen.set_layout(2)
    app.wait_shown()
    app.press(Qt.Key_PageDown)
    reference, current = screen.views[:2]
    current.zoom_by(3.0)
    assert reference.state() == pytest.approx(current.state())
    current._user_change(current._state.pan_by, -40, 25)
    assert reference.state() == pytest.approx(current.state())
    assert current.state()[1:] != pytest.approx((0.5, 0.5))


def _found_reference(app):
    screen = app.screen
    screen.set_reference_folder([PhotoItem(100, app.screen.model.photos[0].path), PhotoItem(101, app.screen.model.photos[1].path)])
    screen.set_layout(2)
    app.wait_shown()
    return screen


def test_sync_off_turns_only_active_current(app, qtbot):
    screen = _found_reference(app)
    screen.sync_button.click()
    assert not screen.sync_button.isChecked()
    app.press(Qt.Key_PageDown)
    assert [view.rotation for view in screen.views[:2]] == [0, 90]
    saved(app, qtbot, {0: 90, 1: 90})


def test_sync_off_aligns_reference_in_memory_then_they_turn_together(app, qtbot):
    screen = _found_reference(app)
    app.press(Qt.Key_PageDown)  # всё вместе: текущая папка в базе 90
    saved(app, qtbot, {0: 90, 1: 90})
    screen.sync_button.click()
    screen._on_view_clicked(screen.views[0])
    assert screen.model.reference_active
    app.press(Qt.Key_PageUp)  # эталон обратно, текущее окно не трогаем
    assert [view.rotation for view in screen.views[:2]] == [0, 90]
    assert [item.rotation for item in screen.strip._items] == [0, 0]  # на ленте сейчас эталон: весь его ракурс
    saved(app, qtbot, {0: 90, 1: 90})  # в базу эталон не попал
    screen.sync_button.click()
    app.press(Qt.Key_PageDown)  # снова вместе, разница сохраняется
    assert [view.rotation for view in screen.views[:2]] == [90, 180]


def test_sync_off_keeps_other_window_place_and_group_state(app):
    screen = _found_reference(app)
    screen.group.set_state(6.0, 0.3, 0.4)
    screen.sync_button.click()
    other = screen.views[0].state()
    group_state = screen.group.state
    app.press(Qt.Key_PageDown)
    assert screen.views[0].state() == other
    assert screen.group.state == group_state
    assert screen.views[1].state() == pytest.approx((6.0, 0.6, 0.3))


def test_single_window_always_turns_with_reference(app):
    screen = _found_reference(app)
    screen.sync_button.click()
    screen.set_layout(1)
    app.wait_shown()
    app.press(Qt.Key_PageDown)
    assert screen.model.reference.rotation == 90
