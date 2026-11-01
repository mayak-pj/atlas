"""PhotoView и ViewState: зум к курсору, сдвиг, вписать, подмена уровня без прыжка, выбор уровня."""
import pytest
from PyQt5.QtCore import QEvent, QObject, QPoint, QPointF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QMouseEvent, QPainter, QWheelEvent
from PyQt5.QtWidgets import QApplication

from atlas.core.theme import apply_theme
from atlas.shared.viewer.image_cache import CacheSettings, ImageCache
from atlas.shared.viewer.levels import L0, L1, L2, L3, level_for_scale
from atlas.shared.viewer.memory_cache import CachedImage
from atlas.shared.viewer.photo_view import PhotoView, TEXT_FAILED, TEXT_LOADING
from atlas.shared.viewer.view_state import MAX_ZOOM, ViewState

FULL_W, FULL_H = 3456, 5184


def picture(level, width=FULL_W, height=FULL_H):
    """Серое фото с красным квадратом в известном месте: (0,6–0,7; 0,2–0,3) долей."""
    divisor = {L0: 32, L1: 4, L2: 2, L3: 1}[level]
    w, h = width // divisor, height // divisor
    image = QImage(w, h, QImage.Format_RGB32)
    image.fill(QColor("#404040"))
    painter = QPainter(image)
    painter.fillRect(int(w * 0.6), int(h * 0.2), int(w * 0.1), int(h * 0.1), QColor("#FF0000"))
    painter.end()
    return image


class FakeCache(QObject):
    ready = pyqtSignal(str, int, QImage)
    failed = pyqtSignal(str, int, str)

    def __init__(self):
        super().__init__()
        self.memory = {}
        self.calls = []

    def peek(self, path, level):
        return self.memory.get((path, level))

    def get(self, path, level, priority=0, exact=False):
        self.calls.append((path, level, exact))
        return self.memory.get((path, level))

    def deliver(self, path, level, image=None):
        self.ready.emit(path, level, image if image is not None else picture(level))


@pytest.fixture
def cache(qapp):
    return FakeCache()


@pytest.fixture
def view(qtbot, qapp, cache):
    apply_theme(qapp)
    widget = PhotoView(cache, settle_ms=10)
    widget.resize(600, 500)
    qtbot.addWidget(widget)
    widget.show()
    return widget


def red_box(widget):
    """Границы красного квадрата на снимке окна."""
    shot = widget.grab().toImage()
    xs, ys = [], []
    for y in range(shot.height()):
        for x in range(shot.width()):
            color = shot.pixelColor(x, y)
            if color.red() > 150 and color.green() < 90:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def wheel(widget, x, y, delta):
    point = QPointF(x, y)
    event = QWheelEvent(point, QPointF(widget.mapToGlobal(QPoint(x, y))), QPoint(0, 0), QPoint(0, delta),
                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)


def move_mouse(widget, x, y, buttons):
    """QTest.mouseMove не передаёт зажатую кнопку, и событие не доходит до виджета."""
    point = QPointF(x, y)
    QApplication.sendEvent(widget, QMouseEvent(QEvent.MouseMove, point, point, Qt.NoButton, buttons, Qt.NoModifier))


def shown(view, cache, path="a.jpg", level=L1):
    view.set_photo(path)
    cache.deliver(path, level)


# --- ViewState ----------------------------------------------------------------------------
def state(view=(600, 500), photo=(3456, 5184)):
    result = ViewState()
    result.set_view_size(*view)
    result.set_photo_size(*photo)
    return result


def test_fit_centers_whole_photo():
    item = state()
    x, y, w, h = item.target_rect()
    assert h == pytest.approx(500) and w == pytest.approx(500 * 3456 / 5184)
    assert x == pytest.approx((600 - w) / 2) and y == pytest.approx(0)


@pytest.mark.parametrize("x,y", [(300, 250), (250, 200), (390, 330)])
def test_zoom_keeps_point_under_cursor(x, y):
    item = state()
    item.zoom_at(1.2, 300, 250)
    item.zoom_at(1.2, 300, 250)
    item.zoom_at(1.2, 300, 250)  # достаточно, чтобы фото заняло всё окно по обеим осям
    item.zoom_at(1.5, 300, 250)
    before = item.to_photo(x, y)
    item.zoom_at(1.5, x, y)
    assert item.to_photo(x, y) == pytest.approx(before)
    item.zoom_at(1 / 1.3, x, y)
    assert item.to_photo(x, y) == pytest.approx(before)


def test_zoom_limits_and_return_to_center():
    item = state()
    for _ in range(40):
        item.zoom_at(1.2, 10, 10)
    assert item.zoom == MAX_ZOOM
    for _ in range(40):
        item.zoom_at(1 / 1.2, 10, 10)
    assert item.state() == (1.0, 0.5, 0.5)


def test_pan_moves_with_mouse_and_stops_at_edges():
    item = state()
    item.zoom_at(4, 300, 250)
    x, y, _, _ = item.target_rect()
    item.pan_by(20, -30)
    assert item.target_rect()[:2] == pytest.approx((x + 20, y - 30))
    item.pan_by(100000, 100000)
    left, top, width, height = item.target_rect()
    assert left == pytest.approx(0) and top == pytest.approx(0)
    item.pan_by(-100000, -100000)
    left, top, width, height = item.target_rect()
    assert left + width == pytest.approx(600) and top + height == pytest.approx(500)


def test_no_pan_on_axis_where_photo_fits():
    item = state()
    item.pan_by(50, 50)
    assert item.state() == (1.0, 0.5, 0.5)


def test_resize_and_other_proportions_keep_center_valid():
    item = state()
    item.zoom_at(6, 100, 100)
    item.set_view_size(5000, 5000)
    assert item.cx == pytest.approx(0.5) or 0 <= item.cx <= 1
    item.set_photo_size(5184, 3456)
    width, height = item.displayed_size()
    assert width / height == pytest.approx(5184 / 3456)


@pytest.mark.parametrize("scale,level", [(0.1, L1), (0.25, L1), (0.26, L2), (0.5, L2), (0.51, L3), (8, L3)])
def test_level_for_scale(scale, level):
    assert level_for_scale(scale) == level


# --- мышь ---------------------------------------------------------------------------------
def test_wheel_zooms_to_cursor(view, cache, qtbot):
    shown(view, cache)
    view.set_state(4, 0.5, 0.5)
    before = view._state.to_photo(200, 150)
    changes = []
    view.view_changed.connect(lambda *args: changes.append(args))
    wheel(view, 200, 150, 120)
    assert view.state()[0] == pytest.approx(4.8)
    assert view._state.to_photo(200, 150) == pytest.approx(before)
    assert changes == [view.state()]


def test_wheel_fractions_from_touchpad_are_smooth(view, cache):
    shown(view, cache)
    wheel(view, 300, 250, 60)
    assert view.state()[0] == pytest.approx(1.2 ** 0.5)


def test_wheel_without_photo_is_ignored(view):
    wheel(view, 300, 250, 120)
    assert view.state()[0] == 1.0


def test_drag_pans_and_double_click_fits(view, cache, qtbot):
    shown(view, cache)
    view.set_state(4, 0.5, 0.5)
    x, y, _, _ = view._state.target_rect()
    changes = []
    view.view_changed.connect(lambda *args: changes.append(args))
    assert view.cursor().shape() == Qt.OpenHandCursor
    qtbot.mousePress(view, Qt.LeftButton, pos=QPoint(100, 100))
    assert view.cursor().shape() == Qt.ClosedHandCursor
    move_mouse(view, 130, 90, Qt.LeftButton)
    qtbot.mouseRelease(view, Qt.LeftButton, pos=QPoint(130, 90))
    assert view.cursor().shape() == Qt.OpenHandCursor
    assert view._state.target_rect()[:2] == pytest.approx((x + 30, y - 10))
    assert changes
    move_mouse(view, 200, 200, Qt.NoButton)  # кнопка отпущена — сдвига нет
    assert view._state.target_rect()[:2] == pytest.approx((x + 30, y - 10))
    qtbot.mouseDClick(view, Qt.LeftButton, pos=QPoint(200, 200))
    assert view.state() == (1.0, 0.5, 0.5)


def test_set_state_does_not_echo_signal(view, cache):
    shown(view, cache)
    changes = []
    view.view_changed.connect(lambda *args: changes.append(args))
    view.set_state(3, 0.4, 0.4)
    assert not changes and view.state()[0] == 3


# --- уровни -------------------------------------------------------------------------------
def test_level_swap_does_not_move_picture(view, cache, qtbot):
    shown(view, cache)
    view.set_state(3, 0.65, 0.25)
    qtbot.waitUntil(lambda: ("a.jpg", L3, True) in cache.calls or ("a.jpg", L2, True) in cache.calls)
    before = red_box(view)
    state_before = view.state()
    cache.deliver("a.jpg", L3)
    assert view.shown_level == L3
    assert view.state() == state_before
    after = red_box(view)
    assert before and all(abs(a - b) <= 2 for a, b in zip(before, after))


def test_rounding_of_higher_level_does_not_change_shape(view, cache, qtbot):
    """У L1 и L3 пропорции чуть различаются из-за округления: прямоугольник на экране остаётся прежним."""
    shown(view, cache)
    view.set_state(12, 0.5, 0.5)
    qtbot.waitUntil(lambda: ("a.jpg", L3, True) in cache.calls)
    before = view._state.target_rect()
    cache.deliver("a.jpg", L3, picture(L3, FULL_W + 3, FULL_H))
    assert view.shown_level == L3 and view._state.target_rect() == before


def test_rough_thumbnail_proportions_are_replaced_by_preview(view, cache):
    view.set_photo("a.jpg")
    cache.deliver("a.jpg", L0, picture(L0, 3456 + 100, 5184))
    cache.deliver("a.jpg", L1)
    width, height = view._state.displayed_size()
    assert width / height == pytest.approx(3456 / 5184)


def test_fit_asks_only_for_what_screen_needs_and_zoom_asks_for_more(view, cache, qtbot):
    shown(view, cache)
    qtbot.wait(40)
    assert not [call for call in cache.calls if call[1] > L1]  # 500 из 5184 по высоте: L1 хватает
    view.set_state(3, 0.5, 0.5)  # 1500 из 5184 > 1/4
    qtbot.waitUntil(lambda: ("a.jpg", L2, True) in cache.calls)
    view.set_state(12, 0.5, 0.5)
    qtbot.waitUntil(lambda: ("a.jpg", L3, True) in cache.calls)


def test_sharp_level_waits_until_movement_stops(qtbot, cache, qapp):
    widget = PhotoView(cache, settle_ms=60)
    widget.resize(600, 500)
    qtbot.addWidget(widget)
    widget.show()
    shown(widget, cache)
    widget.set_state(12, 0.5, 0.5)
    for _ in range(4):
        qtbot.wait(20)
        widget.set_state(12, 0.5, 0.5)
        assert not [call for call in cache.calls if call[1] == L3]
    qtbot.waitUntil(lambda: ("a.jpg", L3, True) in cache.calls)


def test_zoom_out_returns_to_lower_level(view, cache, qtbot):
    shown(view, cache)
    view.set_state(12, 0.5, 0.5)
    qtbot.waitUntil(lambda: ("a.jpg", L3, True) in cache.calls)
    cache.deliver("a.jpg", L3)
    assert view.shown_level == L3
    cache.memory[("a.jpg", L1)] = CachedImage(picture(L1), L1)
    view.fit()
    qtbot.waitUntil(lambda: view.shown_level == L1)
    assert view.state() == (1.0, 0.5, 0.5)


def test_late_sharp_level_after_zoom_out_is_not_shown(view, cache, qtbot):
    shown(view, cache)
    qtbot.wait(30)
    cache.deliver("a.jpg", L3)  # ответ на прежний запрос, а экрану нужен L1
    assert view.shown_level == L1


def test_lower_level_never_replaces_sharper_one(view, cache, qtbot):
    shown(view, cache)
    view.set_state(12, 0.5, 0.5)
    qtbot.waitUntil(lambda: ("a.jpg", L3, True) in cache.calls)
    cache.deliver("a.jpg", L3)
    cache.deliver("a.jpg", L1)
    assert view.shown_level == L3


def test_thin_lines_survive_strong_downscale(qtbot, qapp, cache):
    """Окно в 4 раза ниже L1: линия в 1 пиксель (царапина) не должна пропадать с экрана."""
    apply_theme(qapp)
    image = QImage(864, 1296, QImage.Format_RGB32)
    image.fill(QColor("#000000"))
    painter = QPainter(image)
    painter.setPen(QColor("#FFFFFF"))
    rows = list(range(45, 1250, 37))
    for row in rows:
        painter.drawLine(0, row, 863, row)
    painter.end()
    widget = PhotoView(cache, settle_ms=10)
    widget.resize(400, 300)
    qtbot.addWidget(widget)
    widget.show()
    widget.set_photo("a.jpg")
    cache.deliver("a.jpg", L1, image)
    shot = widget.grab().toImage()
    top = widget._state.target_rect()[1]
    scale = widget._state.target_rect()[3] / 1296
    x = shot.width() // 2
    for row in rows:
        y = int(top + row * scale)
        brightest = max(shot.pixelColor(x, yy).red() for yy in (y - 1, y, y + 1))
        assert brightest > 25, "линия {} пропала".format(row)


# --- листание -----------------------------------------------------------------------------
def test_flip_keeps_zoom_and_place(view, cache, qtbot):
    shown(view, cache)
    view.set_state(5, 0.3, 0.7)
    before = view.state()
    shown(view, cache, "b.jpg")
    assert view.path == "b.jpg" and view.state() == pytest.approx(before)


def test_flip_shows_prepared_sharp_level_at_once(view, cache):
    shown(view, cache, level=L3)
    view.set_state(8, 0.5, 0.5)
    assert view.needed_level == L3
    cache.memory[("b.jpg", L3)] = CachedImage(picture(L3), L3)
    view.set_photo("b.jpg")
    assert view.shown_level == L3  # без размытого L1 на время ожидания


def test_flip_without_prepared_sharp_level_starts_from_l1(view, cache):
    shown(view, cache, level=L3)
    view.set_state(8, 0.5, 0.5)
    cache.memory[("b.jpg", L1)] = CachedImage(picture(L1), L1)
    view.set_photo("b.jpg")
    assert view.shown_level == L1


def test_previous_photo_stays_until_new_one_arrives(view, cache):
    shown(view, cache)
    view.set_photo("b.jpg")
    assert not view.is_current_shown and view.shown_level is None
    assert red_box(view) is not None  # экран не мигает пустотой
    got = []
    view.photo_shown.connect(got.append)
    cache.deliver("b.jpg", L1)
    assert got == ["b.jpg"] and view.is_current_shown


def test_old_photo_answers_are_ignored(view, cache):
    shown(view, cache)
    view.set_photo("b.jpg")
    cache.deliver("a.jpg", L3)
    assert not view.is_current_shown and view._level == L1


def test_memory_hit_shows_at_once(view, cache):
    cache.memory[("b.jpg", L1)] = CachedImage(picture(L3), L3)
    view.set_photo("b.jpg")
    assert view.shown_level == L3


def test_flip_to_other_proportions_updates_shape(view, cache):
    shown(view, cache)
    view.set_photo("wide.jpg")
    cache.deliver("wide.jpg", L1, picture(L1, 5184, 3456))
    width, height = view._state.displayed_size()
    assert width / height == pytest.approx(1.5)


def test_loading_message_after_delay_then_hidden(view, cache, qtbot):
    view.set_photo("a.jpg")
    assert view._message.isHidden()
    qtbot.waitUntil(lambda: not view._message.isHidden())
    assert view._message.text() == TEXT_LOADING
    cache.deliver("a.jpg", L1)
    assert view._message.isHidden()


def test_first_image_after_timer_requests_needed_level(view, cache, qtbot):
    view.set_state(12, 0.5, 0.5)
    view.set_photo("a.jpg")
    qtbot.waitUntil(lambda: not view._message.isHidden())
    cache.deliver("a.jpg", L1)
    assert ("a.jpg", L3, True) in cache.calls


def test_failure_of_first_level_shows_message(view, cache):
    shown(view, cache)
    view.set_photo("bad.jpg")
    errors = []
    view.photo_failed.connect(lambda path, text: errors.append(path))
    cache.failed.emit("bad.jpg", L1, "нет файла")
    assert view._message.text() == TEXT_FAILED and errors == ["bad.jpg"]
    assert red_box(view) is None  # старое фото под именем нового показывать нельзя


def test_failure_of_sharp_level_keeps_preview(view, cache):
    shown(view, cache)
    cache.failed.emit("a.jpg", L3, "обрыв")
    assert view.shown_level == L1 and view._message.isHidden()


def test_clear(view, cache):
    shown(view, cache)
    view.clear()
    assert view.path is None and not view.is_current_shown and red_box(view) is None
    cache.deliver("a.jpg", L3)
    assert view.path is None


# --- с настоящим кэшем --------------------------------------------------------------------
def test_with_real_cache_goes_up_to_full_level(qtbot, qapp, tmp_path):
    photo = tmp_path / "Фото платы" / "1.jpg"
    photo.parent.mkdir()
    assert picture(L1).save(str(photo), "JPEG", 90)  # 864×1296
    real = ImageCache(CacheSettings(disk_dir=tmp_path / "кэш"))
    widget = PhotoView(real, settle_ms=10)
    widget.resize(600, 500)
    qtbot.addWidget(widget)
    widget.show()
    try:
        widget.set_photo(photo)
        qtbot.waitUntil(lambda: widget.is_current_shown, timeout=10000)
        widget.set_state(12, 0.5, 0.5)
        qtbot.waitUntil(lambda: widget.shown_level == L3, timeout=10000)
        widget.fit()  # L1 остался в памяти
        qtbot.waitUntil(lambda: widget.shown_level != L3, timeout=10000)
    finally:
        real.stop()


def test_exact_request_asks_for_lower_level_when_higher_is_in_memory(qtbot, qapp, tmp_path):
    photo = tmp_path / "1.jpg"
    assert picture(L1).save(str(photo), "JPEG", 90)
    real = ImageCache(CacheSettings(disk_dir=tmp_path / "кэш"))
    try:
        with qtbot.waitSignal(real.ready, timeout=10000):
            real.get(photo, L3)
        assert real.get(photo, L2).level == L3
        assert real.wait_idle(5)
        with qtbot.waitSignal(real.ready, timeout=10000) as blocker:
            assert real.get(photo, L2, exact=True).level == L3
        assert blocker.args[1] == L2
        assert real.get(photo, L2, exact=True).level == L2
    finally:
        real.stop()
