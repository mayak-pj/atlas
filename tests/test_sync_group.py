"""SyncGroup и демо-окно: синхронизация, отключение, эталон, листание."""
import pytest
from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QImage

from atlas.core.theme import apply_theme
from atlas.shared.viewer.image_cache import CacheSettings, ImageCache
from atlas.shared.viewer.levels import L1, L3
from atlas.shared.viewer.photo_view import PhotoView, TEXT_LOADING
from atlas.shared.viewer.sync_group import SyncGroup


def picture(width=864, height=1296):
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor("#404040"))
    return image


class FakeCache(QObject):
    ready = pyqtSignal(str, int, QImage)
    failed = pyqtSignal(str, int, str)

    def __init__(self):
        super().__init__()
        self.cancelled = 0
        self.pending = set()

    def get(self, path, level, priority=0, exact=False):
        self.pending.add((path, level))
        return None

    def cancel_pending(self):
        self.cancelled += 1
        self.pending.clear()

    def deliver(self, path, image=None):
        self.ready.emit(path, L1, image if image is not None else picture())


@pytest.fixture
def cache(qapp):
    return FakeCache()


@pytest.fixture
def make_view(qtbot, qapp, cache):
    apply_theme(qapp)

    def make(path="p.jpg", size=(600, 500), image=None):
        view = PhotoView(cache, settle_ms=10)
        view.resize(*size)
        qtbot.addWidget(view)
        view.show()
        if path:
            view.set_photo(path)
            cache.deliver(path, image)
        return view

    return make


@pytest.fixture
def pair(cache, make_view):
    group = SyncGroup(cache)
    first, second = make_view("a.jpg"), make_view("b.jpg")
    group.add(first, reference=True)
    group.add(second)
    return group, first, second


def test_any_window_leads_and_others_follow(pair):
    group, first, second = pair
    first.zoom_by(3)
    assert second.state() == pytest.approx(first.state())
    second.zoom_by(1.5)
    assert first.state() == pytest.approx(second.state())
    assert first.state()[0] == pytest.approx(4.5)


def test_follower_shows_same_point_under_cursor(pair):
    group, first, second = pair
    first.set_state(4, 0.5, 0.5)
    second.set_state(4, 0.5, 0.5)
    first._user_change(first._state.zoom_at, 1.5, 200, 150)
    assert second._state.to_photo(200, 150) == pytest.approx(first._state.to_photo(200, 150))


def test_changed_signal_for_toolbar(pair, qtbot):
    group, first, second = pair
    got = []
    group.changed.connect(lambda *args: got.append(args))
    first.zoom_by(2)
    assert len(got) == 1 and got[0][0] == pytest.approx(2)


def test_no_feedback_loop(pair):
    group, first, second = pair
    echoes = []
    second.view_changed.connect(lambda *args: echoes.append(args))
    first.zoom_by(2)
    assert not echoes


def test_other_proportions_look_at_same_place_and_clamp_alone(cache, make_view):
    group = SyncGroup(cache)
    tall = make_view("tall.jpg")
    wide = make_view("wide.jpg", image=picture(1296, 864))
    group.add(tall)
    group.add(wide)
    tall.set_state(6, 0.5, 0.5)
    tall.zoom_by(1)
    tall._user_change(tall._state.pan_by, 500, 0)
    zoom, cx, cy = tall.state()
    assert wide.state()[0] == pytest.approx(zoom)
    assert wide.state()[1] == pytest.approx(cx, abs=0.2)
    assert group.state == pytest.approx(tall.state())  # край чужого фото не меняет общее место


def test_off_means_independent_and_on_aligns_to_last_touched(pair):
    group, first, second = pair
    group.set_enabled(False)
    first.set_state(1, 0.5, 0.5)
    second.zoom_by(5)
    assert first.state()[0] == 1.0
    group.set_enabled(True)
    assert first.state() == pytest.approx(second.state())
    first.zoom_by(1.2)
    assert second.state()[0] == pytest.approx(6.0)


def test_fit_applies_to_all_even_without_sync(pair):
    group, first, second = pair
    first.zoom_by(3)
    group.set_enabled(False)
    second.zoom_by(2)
    group.fit()
    assert first.state() == (1.0, 0.5, 0.5) and second.state() == (1.0, 0.5, 0.5)


def test_zoom_buttons_with_no_touched_window_use_first(pair):
    group, first, second = pair
    group.zoom_by(2)
    assert first.state()[0] == pytest.approx(2) and second.state()[0] == pytest.approx(2)


def test_group_state_survives_new_photo(pair, cache):
    group, first, second = pair
    group.set_state(5, 0.4, 0.6)
    assert first.state() == pytest.approx((5, 0.4, 0.6)) and second.state() == pytest.approx((5, 0.4, 0.6))
    group.show_photo(second, "new.jpg")
    cache.deliver("new.jpg")
    assert second.state() == pytest.approx((5, 0.4, 0.6))


def test_new_window_takes_group_state(pair, make_view):
    group, first, second = pair
    first.zoom_by(3)
    third = make_view("c.jpg")
    group.add(third)
    assert third.state() == pytest.approx(first.state())


def test_removed_window_is_free(pair):
    group, first, second = pair
    group.remove(second)
    first.zoom_by(3)
    assert second.state()[0] == 1.0
    second.zoom_by(2)
    assert first.state()[0] == pytest.approx(3)
    assert group.views == [first]


def test_removing_reference_and_leader_is_safe(pair):
    group, first, second = pair
    first.zoom_by(2)
    group.remove(first)
    assert group.reference is None
    group.zoom_by(2)
    assert second.state()[0] == pytest.approx(4)


def test_flip_changes_one_window_and_cancels_once(pair, cache):
    group, first, second = pair
    assert group.reference is first and group.currents == [second]
    group.show_photo(second, "c.jpg")
    assert first.path == "a.jpg" and second.path == "c.jpg"
    assert cache.cancelled == 1


def test_active_window_is_last_touched_current_and_never_reference(cache, make_view):
    group = SyncGroup(cache)
    reference, one, two = make_view("r.jpg"), make_view("a.jpg"), make_view("b.jpg")
    group.add(reference, reference=True)
    group.add(one)
    group.add(two)
    assert group.active_current() is two
    one.zoom_by(2)
    assert group.active_current() is one
    reference.zoom_by(2)
    assert group.active_current() is two


def test_flip_keeps_place_across_other_proportions(cache, make_view):
    """Широкое фото упирает окно в край. Следующее фото должно вернуться на то же место."""
    group = SyncGroup(cache)
    view, other = make_view("a.jpg"), make_view("r.jpg")
    group.add(other, reference=True)
    group.add(view)
    other.set_state(2, 0.5, 0.1)
    other._user_change(other._state.pan_by, 0, 0.0001)
    place = group.state
    group.show_photo(view, "wide.jpg")
    cache.deliver("wide.jpg", picture(1296, 864))
    group.show_photo(view, "tall.jpg")
    cache.deliver("tall.jpg")
    assert view.state() == pytest.approx(place)


def test_cancel_does_not_leave_unchanged_window_loading_forever(cache, make_view, qtbot):
    """Отмена снимает запрос эталона, который ещё грузится: он обязан запросить снова."""
    group = SyncGroup(cache)
    reference, current = make_view(None), make_view("a.jpg")
    group.add(reference, reference=True)
    group.add(current)
    reference.set_photo("ref.jpg")
    assert ("ref.jpg", L1) in cache.pending
    group.show_photo(current, "b.jpg")
    assert ("ref.jpg", L1) in cache.pending and ("b.jpg", L1) in cache.pending
    qtbot.waitUntil(lambda: reference._message.text() == TEXT_LOADING)
    cache.deliver("ref.jpg")
    assert reference.is_current_shown and reference._message.isHidden()


def test_caption(make_view):
    view = make_view("a.jpg")
    assert view._caption.isHidden()
    view.set_caption("ЭТАЛОН", "плата.jpg", reference=True)
    assert not view._caption.isHidden() and view._caption.width() > 0
    assert view._caption.testAttribute(Qt.WA_TransparentForMouseEvents)
    view.set_caption("")
    assert view._caption.isHidden()


# --- демо с настоящим кэшем ---------------------------------------------------------------
@pytest.fixture
def demo(qtbot, qapp, tmp_path):
    from tools.viewer_demo import ViewerDemo

    apply_theme(qapp)
    photos = []
    for number in range(6):
        path = tmp_path / "Фото" / "плата {}.jpg".format(number)
        path.parent.mkdir(exist_ok=True)
        assert picture(800, 1200).save(str(path), "JPEG", 80)
        photos.append(path)
    cache = ImageCache(CacheSettings(disk_dir=tmp_path / "кэш"))
    widget = ViewerDemo(photos, cache)
    widget.resize(1000, 700)
    qtbot.addWidget(widget)
    widget.show()
    yield widget
    cache.stop()


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_demo_layouts_show_all_photos(demo, qtbot, count):
    demo.set_layout(count)
    assert len(demo.group.views) == count
    assert (demo.group.reference is not None) == (count > 1)
    qtbot.waitUntil(lambda: all(view.is_current_shown for view in demo.group.views), timeout=10000)
    assert all(view.isVisible() for view in demo.group.views)
    assert not any(view.isVisible() for view in demo.views[count:])


def test_demo_sync_flip_and_sharp_levels_in_four_windows(demo, qtbot):
    demo.set_layout(4)
    qtbot.waitUntil(lambda: all(view.is_current_shown for view in demo.group.views), timeout=10000)
    demo.views[1].set_state(1, 0.5, 0.5)
    demo.views[1].zoom_by(12)
    qtbot.waitUntil(lambda: all(view.shown_level == L3 for view in demo.group.views), timeout=15000)
    state = demo.views[0].state()
    others = [demo.views[0].path, demo.views[2].path, demo.views[3].path]
    before = demo.views[1].path  # окна касались последним: зум выше
    qtbot.keyClick(demo, Qt.Key_Right)
    assert demo.views[1].path != before
    assert [demo.views[0].path, demo.views[2].path, demo.views[3].path] == others  # листается только одно окно
    qtbot.waitUntil(lambda: all(view.shown_level == L3 for view in demo.group.views), timeout=15000)
    assert demo.views[3].state() == pytest.approx(state)


def test_demo_sync_button_toggles(demo, qtbot):
    demo.set_layout(2)
    qtbot.mouseClick(demo.sync_button, Qt.LeftButton)
    assert not demo.group.enabled
    demo.views[1].zoom_by(2)
    assert demo.views[0].state()[0] == 1.0
    qtbot.mouseClick(demo.sync_button, Qt.LeftButton)
    assert demo.views[0].state()[0] == pytest.approx(2)


def test_show_photos_one_cancel_many_views(make_view, cache):
    first, second = make_view("a.jpg"), make_view("b.jpg")
    group = SyncGroup(cache)
    group.add(first)
    group.add(second)
    before = cache.cancelled
    group.show_photos([(first, "c.jpg"), (second, "d.jpg")])
    assert cache.cancelled == before + 1
    assert first.path == "c.jpg" and second.path == "d.jpg"
    assert ("c.jpg", L1) in cache.pending and ("d.jpg", L1) in cache.pending


def test_show_missing_clears_and_keeps_zoom(make_view, cache):
    view = make_view("a.jpg")
    cache.deliver("a.jpg")
    view.zoom_by(2.0)
    state = view.state()
    view.show_missing("Нет ракурса 2")
    assert view.path is None and not view.is_current_shown
    assert view._message.text() == "Нет ракурса 2" and view.state() == state
    view.set_photo("b.jpg")
    assert view._message.text() == ""
