"""Шаг 12.1: рамка платы на тёмном фоне, «Выровнять» в окне просмотра, рамка в кэше."""
import time

import pytest
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter

from atlas.core.theme import apply_theme
from atlas.shared.viewer.image_cache import CacheSettings, ImageCache
from atlas.shared.viewer.levels import L1
from atlas.shared.viewer.object_frame import (
    find_frame, frame_from_gray, otsu_threshold, padded_frame, rotated_frame,
)
from atlas.shared.viewer.photo_view import PhotoView
from atlas.shared.viewer.view_state import ViewState


def board(width, height, box, background="#141414", color="#3C8C50", extra=None):
    """Тёмный фон и светлая «плата» в box (доли x, y, w, h); на плате тёмные элементы — как настоящие детали."""
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor(background))
    painter = QPainter(image)
    x, y, w, h = box
    painter.fillRect(int(x * width), int(y * height), int(w * width), int(h * height), QColor(color))
    for number in range(4):  # чёрные микросхемы поперёк платы
        painter.fillRect(int((x + w * (0.1 + 0.2 * number)) * width), int((y + h * 0.4) * height),
                         int(w * 0.1 * width), int(h * 0.15 * height), QColor("#101010"))
    if extra is not None:
        ex, ey, ew, eh = extra
        painter.fillRect(int(ex * width), int(ey * height), int(ew * width), int(eh * height), QColor("#E0E0E0"))
    painter.end()
    return image


def near(found, expected, tolerance=0.012):
    assert found is not None
    for got, wanted in zip(found, expected):
        assert got == pytest.approx(wanted, abs=tolerance), (found, expected)


# --- поиск рамки ------------------------------------------------------------------------
def test_otsu_splits_two_peaks():
    histogram = [0] * 256
    histogram[20] = 700
    histogram[180] = 300
    assert 20 <= otsu_threshold(histogram) < 180


@pytest.mark.parametrize("box", [(0.2, 0.3, 0.5, 0.4), (0.05, 0.1, 0.6, 0.7), (0.4, 0.45, 0.35, 0.3)])
def test_finds_board_on_dark_background(qapp, box):
    near(find_frame(board(864, 1296, box)), box)


def test_small_object_aside_does_not_stretch_frame(qapp):
    """Бирка или палец сбоку меньше платы: рамка — по плате."""
    box = (0.25, 0.25, 0.5, 0.5)
    near(find_frame(board(864, 1296, box, extra=(0.85, 0.05, 0.08, 0.05))), box)


@pytest.mark.parametrize("image", [
    board(400, 600, (0.1, 0.1, 0.8, 0.8), background="#E8E8E8", color="#C0C0C0"),  # светлый фон
    board(400, 600, (0.0, 0.0, 1.0, 1.0)),  # плата во весь кадр — нечего выравнивать
])
def test_not_sure_gives_none(qapp, image):
    assert find_frame(image) is None


def test_uniform_dark_picture_gives_none():
    assert frame_from_gray(bytes([10]) * 64 * 64, 64, 64) is None


def test_padded_stride_is_handled(qapp):
    """Ширина 803 — строки Grayscale8 выровнены до 4 байт."""
    box = (0.2, 0.3, 0.5, 0.4)
    near(find_frame(board(803, 1203, box)), box, tolerance=0.015)


def test_speed_is_milliseconds(qapp):
    image = board(864, 1296, (0.2, 0.3, 0.5, 0.4))
    started = time.perf_counter()
    for _ in range(10):
        find_frame(image)
    assert (time.perf_counter() - started) / 10 < 0.1  # 500 фото прогрева — меньше минуты в фоне


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotated_frame_matches_rotated_picture(qapp, rotation):
    from PyQt5.QtGui import QTransform

    box = (0.1, 0.2, 0.5, 0.3)
    image = board(600, 900, box).transformed(QTransform().rotate(rotation))
    near(find_frame(image), rotated_frame(box, rotation))


def test_padding_is_same_in_pixels():
    x, y, w, h = padded_frame((0.25, 0.25, 0.5, 0.5), 1000, 2000, pad=0.1)
    assert (0.25 - x) * 1000 == pytest.approx((0.25 - y) * 2000)


# --- ViewState с рамкой ------------------------------------------------------------------
def view_state(frame=None):
    state = ViewState()
    state.set_view_size(600, 500)
    state.set_photo_size(3456, 5184)
    state.set_frame(frame)
    return state


def screen_box(state, frame):
    left, top, width, height = state.target_rect()
    x, y, w, h = frame
    return left + x * width, top + y * height, w * width, h * height


@pytest.mark.parametrize("frame", [(0.1, 0.1, 0.4, 0.3), (0.5, 0.6, 0.45, 0.3)])
def test_fit_puts_frame_in_middle_of_window(frame):
    state = view_state(frame)
    left, top, width, height = screen_box(state, frame)
    assert left + width / 2 == pytest.approx(300)
    assert top + height / 2 == pytest.approx(250)
    assert max(width / 600, height / 500) == pytest.approx(1.0)


def test_same_numbers_show_same_place_of_board():
    """Плата в разных местах кадра: при одном зуме и центре точка платы оказывается в одной точке окна."""
    first, second = (0.1, 0.1, 0.4, 0.3), (0.45, 0.5, 0.42, 0.315)
    points = []
    for frame in (first, second):
        state = view_state(frame)
        state.set_state(3.0, 0.3, 0.6)
        left, top, width, height = state.target_rect()
        x, y, w, h = frame
        points.append((left + (x + 0.3 * w) * width, top + (y + 0.6 * h) * height))
    assert points[0][0] == pytest.approx(points[1][0])
    assert points[0][1] == pytest.approx(points[1][1])


def test_zoom_at_cursor_keeps_point_with_frame():
    state = view_state((0.2, 0.3, 0.4, 0.3))
    before = state.to_photo(400, 200)
    state.zoom_at(2.0, 400, 200)
    after = state.to_photo(400, 200)
    assert after[0] == pytest.approx(before[0])
    assert after[1] == pytest.approx(before[1])


def test_pan_moves_by_pixels_with_frame():
    state = view_state((0.2, 0.3, 0.4, 0.3))
    state.set_state(4.0, 0.5, 0.5)
    left = state.target_rect()[0]
    state.pan_by(30, 0)
    assert state.target_rect()[0] - left == pytest.approx(30)


def test_without_frame_nothing_changes():
    plain, framed = view_state(), view_state((0.0, 0.0, 1.0, 1.0))
    for state in (plain, framed):
        state.set_state(2.5, 0.4, 0.6)
    assert plain.target_rect() == pytest.approx(framed.target_rect())


# --- PhotoView ---------------------------------------------------------------------------
class FrameCache(QObject):
    ready = pyqtSignal(str, int, QImage)
    failed = pyqtSignal(str, int, str)
    frame_ready = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.frames = {}

    def peek(self, path, level):
        return None

    def get(self, path, level, priority=0, exact=False):
        return None

    def frame(self, path):
        return self.frames.get(path)

    def deliver(self, path):
        self.ready.emit(path, L1, QImage(864, 1296, QImage.Format_RGB32))


@pytest.fixture
def aligned_view(qtbot, qapp):
    apply_theme(qapp)
    cache = FrameCache()
    widget = PhotoView(cache, settle_ms=10)
    widget.resize(600, 500)
    qtbot.addWidget(widget)
    widget.show()
    return widget, cache


def board_on_screen(view, frame):
    left, top, width, height = view._state.target_rect()
    x, y, w, h = frame
    return round(left + (x + w / 2) * width), round(top + (y + h / 2) * height), round(w * width)


def test_align_puts_boards_of_different_photos_in_one_place(aligned_view):
    view, cache = aligned_view
    cache.frames = {"a.jpg": (0.1, 0.1, 0.4, 0.3), "b.jpg": (0.45, 0.5, 0.42, 0.32)}
    view.set_align(True)
    places = []
    for path in ("a.jpg", "b.jpg"):
        view.set_photo(path)
        cache.deliver(path)
        assert view.aligned
        places.append(board_on_screen(view, cache.frames[path]))
    assert abs(places[0][0] - places[1][0]) <= 1 and abs(places[0][1] - places[1][1]) <= 1
    assert abs(places[0][2] - places[1][2]) <= 0.06 * places[0][2]  # масштаб: рамки чуть разных пропорций


def test_old_picture_keeps_its_frame_until_new_arrives(aligned_view):
    view, cache = aligned_view
    cache.frames = {"a.jpg": (0.1, 0.1, 0.4, 0.3), "b.jpg": (0.5, 0.5, 0.4, 0.3)}
    view.set_align(True)
    view.set_photo("a.jpg")
    cache.deliver("a.jpg")
    before = view._state.frame
    view.set_photo("b.jpg")
    cache.frame_ready.emit("b.jpg")
    assert view._state.frame == before


def test_no_board_found_shows_whole_photo(aligned_view):
    view, cache = aligned_view
    view.set_align(True)
    view.set_photo("a.jpg")
    cache.deliver("a.jpg")
    assert not view.aligned
    cache.frames["a.jpg"] = (0.2, 0.2, 0.5, 0.5)
    cache.frame_ready.emit("a.jpg")  # нашлась позже
    assert view.aligned
    view.set_align(False)
    assert not view.aligned


def test_rotation_keeps_board_aligned(aligned_view):
    view, cache = aligned_view
    cache.frames = {"a.jpg": (0.1, 0.1, 0.4, 0.3)}
    view.set_align(True)
    view.set_photo("a.jpg")
    cache.deliver("a.jpg")
    view.set_rotation(90)
    frame = view._state.frame
    left, top, width, height = view._state.target_rect()
    assert left + (frame[0] + frame[2] / 2) * width == pytest.approx(300, abs=1)
    assert top + (frame[1] + frame[3] / 2) * height == pytest.approx(250, abs=1)


# --- ImageCache ----------------------------------------------------------------------------
def test_cache_finds_frame_before_ready_and_on_warmup(qapp, qtbot, tmp_path):
    first, second = tmp_path / "а.jpg", tmp_path / "б.jpg"
    for path, box in ((first, (0.2, 0.3, 0.5, 0.4)), (second, (0.1, 0.1, 0.4, 0.5))):
        assert board(800, 1200, box).save(str(path), "JPEG", 90)
    cache = ImageCache(CacheSettings(disk_dir=tmp_path / "кэш"))
    try:
        seen = []
        cache.ready.connect(lambda path, level, image: seen.append(cache.has_frame(path)))
        with qtbot.waitSignal(cache.ready, timeout=5000):
            cache.get(first, L1)
        assert seen == [True]
        near(cache.frame(first), (0.2, 0.3, 0.5, 0.4))
        cache.prefetch([second])
        qtbot.waitUntil(lambda: cache.has_frame(second), timeout=5000)
        near(cache.frame(second), (0.1, 0.1, 0.4, 0.5))
        cache.forget(first)
        assert not cache.has_frame(first)
    finally:
        cache.stop()


# --- «Сравнение»: кнопки «Выровнять» и «По партиям» ---------------------------------------------
def test_batch_order_groups_cameras_and_keeps_order_inside():
    left, right = (0.1, 0.1, 0.4, 0.3), (0.45, 0.5, 0.42, 0.32)
    frames = [left, right, (0.11, 0.1, 0.4, 0.3), None, right, left]
    from atlas.shared.viewer.object_frame import batch_order, batches

    assert batches(frames) == [[0, 2, 5], [1, 4]]
    assert batch_order(frames) == [0, 2, 5, 1, 4, 3]


def test_reorder_keeps_windows_on_their_photos():
    from atlas.features.compare.logic import CompareModel, PhotoItem

    model = CompareModel()
    model.set_photos([PhotoItem(number, "{}.jpg".format(number)) for number in range(5)])
    model.set_layout(2)
    model.go(3)
    model.sizes = {number: (number, number) for number in range(5)}
    model.reorder([4, 3, 2, 1, 0])
    assert [photo.id for photo in model.photos] == [4, 3, 2, 1, 0]
    assert model.current(0).id == 3
    assert model.sizes[0] == (4, 4)
    with pytest.raises(ValueError):
        model.reorder([0, 0, 1, 2, 3])


def test_compare_buttons_align_and_sort_batches(tmp_path, qtbot):
    from pathlib import Path

    from tests.test_compare_flow import App

    app = App(tmp_path, qtbot, count=0)
    try:
        app.path.mkdir(parents=True, exist_ok=True)
        names = []
        for number in range(6):  # две партии вперемешку: плата слева вверху и справа внизу
            box = (0.1, 0.1, 0.45, 0.35) if number % 2 == 0 else (0.4, 0.5, 0.45, 0.35)
            names.append("фото {:03d}.jpg".format(number + 1))
            assert board(300, 450, box).save(str(app.path / names[-1]), "JPEG", 90)
        app.ctx.services.get("folders").add_photos(app.folder.id, names)
        app.wait_open()
        screen = app.screen
        screen.go(1)  # «фото 002» — вторая партия
        app.wait_shown()
        screen.batches_button.click()
        qtbot.waitUntil(lambda: screen.batches_button.text() == "По партиям", timeout=5000)
        order = [Path(photo.path).name for photo in screen.model.photos]
        assert order == [names[i] for i in (0, 2, 4, 1, 3, 5)]
        assert app.active_name() == names[1]
        assert screen.model.active_index == 3
        screen.align_button.click()
        app.wait_shown()
        assert all(view.aligned for view in screen.group.views)
        screen.batches_button.click()
        assert [Path(photo.path).name for photo in screen.model.photos] == names
        assert app.active_name() == names[1]
    finally:
        app.stop()
