"""compare в настоящем приложении: настоящие JPEG, база, шина, клавиши и мышь."""
import json
import shutil
from pathlib import Path

import pytest
from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QColor, QImage, QKeyEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QLabel

from atlas.app import build_core, build_window, start_features
from atlas.core.config import AppPaths
from atlas.shared.viewer.filmstrip import GAP
from atlas.shared.viewer.levels import L1

REPO = Path(__file__).resolve().parent.parent
COLORS = ["#CC2020", "#20CC20", "#2020CC", "#CCCC20", "#20CCCC", "#CC20CC"]


def _photos(folder, count, size=(300, 450), names=None):
    folder.mkdir(parents=True)
    result = []
    for number in range(count):
        image = QImage(size[0], size[1], QImage.Format_RGB32)
        image.fill(QColor(COLORS[number % len(COLORS)]))
        name = names[number] if names else "фото {:03d}.jpg".format(number + 1)
        assert image.save(str(folder / name), "JPEG", 90)
        result.append(name)
    return result


class App:
    def __init__(self, tmp_path, qtbot, count=6, size=(300, 450), data=True, names=None, features=("compare",)):
        self.qtbot = qtbot
        root = tmp_path / "Атлас тест"
        (root / "config").mkdir(parents=True)
        shutil.copy(str(REPO / "config" / "app.json"), str(root / "config" / "app.json"))
        if data:
            shutil.copytree(str(REPO / "data"), str(root / "data"))
        features = {"features": [{"id": name} for name in features]}
        (root / "config" / "features.json").write_text(json.dumps(features), encoding="utf-8")
        local = {"image_cache": {"disk_dir": str(tmp_path / "кэш")}}
        (root / "config" / "local.json").write_text(json.dumps(local), encoding="utf-8")
        self.ctx = build_core(AppPaths(root))
        self.path = tmp_path / "Сеть" / "SSD"
        services = self.ctx.services
        self.part = services.get("parts").ensure("A", "Орион-24", "N15", "SSD XS-2280")
        self.folder = services.get("folders").add(self.part.id, str(self.path), "2026-10-31")
        services.get("folders").add_photos(self.folder.id, _photos(self.path, count, size, names) if count else [])
        self.registry = start_features(self.ctx)
        assert self.registry.failures == []
        self.events = []
        for name in ("folder.opened", "photo.changed", "photo.marked"):
            self.ctx.bus.subscribe(name, lambda payload, name=name: self.events.append((name, payload)))
        self.window = build_window(self.registry)
        qtbot.addWidget(self.window)
        self.feature = services.get("compare")
        self.screen = self.feature.screen
        self.window.show()

    def wait_open(self):
        self.feature.open_folder(self.folder.id)
        self.qtbot.waitUntil(lambda: self.feature.folder is not None, timeout=5000)
        self.wait_shown()

    def wait_shown(self):
        views = self.screen.group.views
        self.qtbot.waitUntil(lambda: bool(views) and all(view.is_current_shown for view in views), timeout=5000)

    def names(self):
        return [Path(view.path).name for view in self.screen.group.views]

    def active_name(self):
        return Path(self.screen.active_view().path).name

    def press(self, key):
        QTest.keyClick(self.screen, key)

    def stop(self):
        self.registry.stop_all()
        self.ctx.services.get("image_cache").stop()


@pytest.fixture
def app(tmp_path, qtbot):
    instance = App(tmp_path, qtbot)
    yield instance
    instance.stop()


def _key(widget, kind, key, auto=False):
    QApplication.sendEvent(widget, QKeyEvent(kind, key, Qt.NoModifier, "", auto))


def _color_at_center(view):
    image = view.grab().toImage()
    return image.pixelColor(image.width() // 2, image.height() // 2)


def test_opens_latest_folder_sets_context_and_publishes(app):
    app.wait_open()
    assert app.window.context_bar.chain_text == "Орион-24 › N15 › SSD XS-2280"
    assert ("folder.opened", {"folder_id": app.folder.id, "part_id": app.part.id}) in app.events
    assert app.feature.current_folder().id == app.folder.id
    assert app.names() == ["фото 001.jpg"]


def test_one_window_flips_and_keeps_zoom_and_place(app):
    app.wait_open()
    view = app.screen.active_view()
    app.screen.group.set_state(8.0, 0.3, 0.6)
    app.press(Qt.Key_Right)
    app.press(Qt.Key_Right)
    app.wait_shown()
    assert app.active_name() == "фото 003.jpg"
    assert view.state() == pytest.approx((8.0, 0.3, 0.6))
    app.press(Qt.Key_Left)
    assert app.active_name() == "фото 002.jpg"
    changes = [payload for name, payload in app.events if name == "photo.changed"]
    assert [item["index"] for item in changes] == [1, 2, 1]
    assert changes[-1]["folder_id"] == app.folder.id
    assert changes[-1]["photo_id"] == app.ctx.services.get("folders").photos(app.folder.id)[1].id


def test_flipping_stops_at_edges_without_events(app):
    app.wait_open()
    app.press(Qt.Key_Left)
    assert app.active_name() == "фото 001.jpg"
    assert not [item for item in app.events if item[0] == "photo.changed"]


def test_auto_repeat_flips_every_time(app):
    app.wait_open()
    for _ in range(3):
        _key(app.screen, QEvent.KeyPress, Qt.Key_Right, auto=True)
    assert app.active_name() == "фото 004.jpg"


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_layouts_show_requested_number_of_windows(app, count):
    app.wait_open()
    app.screen.set_layout(count)
    app.wait_shown()
    assert len(app.screen.group.views) == count
    assert sum(view.isVisible() for view in app.screen.views) == count
    assert (app.screen.group.reference is not None) == (count > 1)
    assert app.screen.sync_button.isEnabled() == (count > 1)


def test_click_selects_active_window_and_only_it_flips(app):
    app.wait_open()
    app.screen.set_layout(3)
    app.wait_shown()
    first, second = app.screen.views[1], app.screen.views[2]
    assert first.property("active") and not second.property("active")
    QTest.mouseClick(second, Qt.LeftButton)
    assert second.property("active") and not first.property("active")
    reference_before, first_before, second_before = app.screen.views[0].path, first.path, second.path
    app.press(Qt.Key_Right)
    assert second.path != second_before
    assert first.path == first_before
    assert app.screen.views[0].path == reference_before


def test_click_on_reference_keeps_active_window(app):
    app.wait_open()
    app.screen.set_layout(2)
    app.wait_shown()
    current = app.screen.views[1]
    QTest.mouseClick(app.screen.views[0], Qt.LeftButton)
    assert current.property("active")
    before = app.screen.views[0].path
    app.press(Qt.Key_Right)
    assert app.screen.views[0].path == before
    assert app.active_name() == "фото 002.jpg"


def test_zoom_is_synchronous_and_can_be_turned_off(app):
    app.wait_open()
    app.screen.set_layout(2)
    app.wait_shown()
    reference, current = app.screen.views[0], app.screen.views[1]
    current.zoom_by(2.0)
    assert reference.state() == pytest.approx(current.state())
    assert app.screen.zoom_label.text() == "200%"
    app.screen.sync_button.click()
    current.zoom_by(2.0)
    assert reference.state()[0] == pytest.approx(2.0)
    assert current.state()[0] == pytest.approx(4.0)


def test_minus_plus_follow_clicked_window_when_sync_off(app):
    app.wait_open()
    app.screen.set_layout(2)
    app.wait_shown()
    app.screen.sync_button.click()
    reference, current = app.screen.views[0], app.screen.views[1]
    current.zoom_by(2.0)
    QTest.mouseClick(reference, Qt.LeftButton)
    app.screen.group.zoom_by(3.0)
    assert reference.state()[0] == pytest.approx(3.0)
    assert current.state()[0] == pytest.approx(2.0)


def _space(screen, kind, auto=False):
    _key(screen, QEvent.KeyPress if kind == QTest.Press else QEvent.KeyRelease, Qt.Key_Space, auto)


def test_flicker_ignores_auto_repeat_of_space(app):
    app.wait_open()
    app.press(Qt.Key_Right)
    _space(app.screen, QTest.Press)
    _space(app.screen, QTest.Release, auto=True)  # так выглядит удержание: отпускание-нажатие с автоповтором
    assert app.screen.flickering
    _space(app.screen, QTest.Press, auto=True)
    assert app.screen.flickering
    _space(app.screen, QTest.Release)
    assert not app.screen.flickering


def test_flicker_shows_reference_on_same_place_until_release(app):
    app.wait_open()
    app.press(Qt.Key_Right)
    app.wait_shown()
    view = app.screen.active_view()
    app.screen.group.set_state(8.0, 0.4, 0.4)
    _space(app.screen, QTest.Press)
    assert app.screen.flickering
    assert app.active_name() == "фото 001.jpg"
    app.wait_shown()
    assert view.state() == pytest.approx((8.0, 0.4, 0.4))
    app.press(Qt.Key_Right)  # листать во время «мигалки» нельзя: непонятно, что на экране
    assert app.screen.model.index(0) == 1
    _space(app.screen, QTest.Release)
    assert not app.screen.flickering
    assert app.active_name() == "фото 002.jpg"
    app.wait_shown()
    assert view.state() == pytest.approx((8.0, 0.4, 0.4))
    assert len([item for item in app.events if item[0] == "photo.changed"]) == 1


def test_flicker_really_changes_picture(app):
    app.wait_open()
    app.press(Qt.Key_Right)
    view = app.screen.active_view()
    app.qtbot.waitUntil(lambda: view.is_sharp, timeout=5000)
    second = _color_at_center(view)
    _space(app.screen, QTest.Press)
    app.qtbot.waitUntil(lambda: view.is_current_shown and _color_at_center(view) != second, timeout=5000)
    assert _color_at_center(view).red() > 150  # первое фото красное
    _space(app.screen, QTest.Release)


def test_flicker_ends_when_tab_is_hidden(app):
    app.wait_open()
    app.press(Qt.Key_Right)
    _space(app.screen, QTest.Press)
    app.screen.hide()
    assert not app.screen.flickering
    assert app.active_name() == "фото 002.jpg"


def test_flicker_ends_when_layout_changes(app):
    app.wait_open()
    app.press(Qt.Key_Right)
    _space(app.screen, QTest.Press)
    app.screen.set_layout(2)
    assert not app.screen.flickering
    assert Path(app.screen.views[1].path).name == "фото 002.jpg"
    assert Path(app.screen.views[0].path).name == "фото 001.jpg"


def test_flicker_restores_own_place_without_sync(app):
    app.wait_open()
    app.screen.set_layout(2)
    app.wait_shown()
    app.screen.sync_button.click()
    view = app.screen.views[1]
    view.set_state(5.0, 0.3, 0.7)
    _space(app.screen, QTest.Press)
    _space(app.screen, QTest.Release)
    app.wait_shown()
    assert view.state() == pytest.approx((5.0, 0.3, 0.7))


def test_flicker_restores_place_after_reference_of_other_shape(app, tmp_path):
    """Широкий эталон упирает окно в край. Без синхронности место некому вернуть, кроме самого экрана."""
    app.wait_open()
    app.screen.set_layout(2)
    other = tmp_path / "широкий"
    app.feature.set_reference(other / _photos(other, 1, size=(900, 300))[0])
    app.wait_shown()
    app.screen.sync_button.click()
    view = app.screen.views[1]
    view.set_state(3.0, 0.5, 0.8)
    _space(app.screen, QTest.Press)
    app.wait_shown()
    assert view.state() != pytest.approx((3.0, 0.5, 0.8))  # проверка настоящая: окно действительно уперлось
    _space(app.screen, QTest.Release)
    app.wait_shown()
    assert view.state() == pytest.approx((3.0, 0.5, 0.8))


def test_long_path_does_not_widen_window(app):
    app.wait_open()
    long_path = "\\\\nas\\" + "\\".join(["очень длинная папка"] * 30)
    app.window.resize(1024, 640)
    app.window.set_context("A", "Орион-24", "N15", "SSD", long_path)
    QApplication.processEvents()
    assert app.window.minimumSizeHint().width() < 1024
    label = app.window.context_bar._path
    assert label.toolTip() == long_path
    assert label.text() != long_path and "…" in label.text()


def test_reference_can_be_replaced_through_service(app, tmp_path):
    app.wait_open()
    app.screen.set_layout(2)
    other = tmp_path / "эталон"
    name = _photos(other, 1)[0]
    app.feature.set_reference(other / name)
    app.wait_shown()
    assert app.screen.views[0].path == str(other / name)
    assert app.active_name() == "фото 001.jpg"


def test_slots_appear_only_with_panels(app):
    app.wait_open()
    screen = app.screen
    assert not screen.left.isVisible() and not screen.right.isVisible()
    panel = QLabel("панель")
    app.ctx.shell.add_panel("compare.left", panel, key="test")
    assert screen.left.isVisible() and panel.isVisible()
    app.ctx.shell.remove_panel("compare.left", "test")
    assert not screen.left.isVisible()
    app.ctx.shell.add_panel("compare.right", QLabel("справа"), key="test")
    assert screen.right.isVisible()
    tool = QLabel("кнопка")
    app.ctx.shell.add_panel("compare.toolbar", tool, key="test")
    assert tool.isVisible()


def test_wide_photos_get_a_two_by_two_grid(tmp_path, qtbot):
    app = App(tmp_path, qtbot, size=(450, 300))
    try:
        app.wait_open()
        app.screen.set_layout(4)
        app.wait_shown()
        rows = {app.screen.grid.getItemPosition(app.screen.grid.indexOf(view))[0] for view in app.screen.views}
        assert rows == {0, 1}
    finally:
        app.stop()


def test_portrait_photos_stand_in_a_row(app):
    app.wait_open()
    app.screen.set_layout(4)
    app.wait_shown()
    rows = {app.screen.grid.getItemPosition(app.screen.grid.indexOf(view))[0] for view in app.screen.views}
    assert rows == {0}


def test_empty_folder_shows_message(tmp_path, qtbot):
    app = App(tmp_path, qtbot, count=0)
    try:
        app.feature.open_folder(app.folder.id)
        app.qtbot.waitUntil(lambda: app.feature.folder is not None, timeout=5000)
        assert app.screen.message.isVisible()
        assert app.screen.message.text() == "В папке нет фото"
        app.press(Qt.Key_Right)
        _space(app.screen, QTest.Press)
        assert not app.screen.flickering
        app.screen.set_layout(3)
    finally:
        app.stop()


def test_works_without_hotkeys_file(tmp_path, qtbot):
    app = App(tmp_path, qtbot, data=False)
    try:
        app.wait_open()
        app.press(Qt.Key_Right)
        assert app.active_name() == "фото 002.jpg"
    finally:
        app.stop()


def test_failed_read_shows_message_and_keeps_running(app, monkeypatch):
    app.wait_open()
    monkeypatch.setattr(app.feature, "_load", lambda folder_id: 1 / 0)
    app.feature.open_folder(app.folder.id)
    app.qtbot.waitUntil(lambda: app.screen.message.isVisible(), timeout=5000)
    assert app.screen.message.text() == "Не удалось открыть папку"
    app.press(Qt.Key_Right)


def test_stale_answer_is_ignored(app, tmp_path):
    app.wait_open()
    second = app.ctx.services.get("folders").add(app.part.id, str(tmp_path / "вторая"), "2026-10-30")
    result = app.feature._read(second)
    app.feature._on_loaded(app.feature._request - 1, result)
    assert app.feature.folder.id == app.folder.id


# --- лента и предзагрузка ---------------------------------------------------
def _click_cell(strip, index):
    first, _ = strip.visible()
    x = (index - first) * (strip._cell_width + GAP) + 5
    QTest.mouseClick(strip, Qt.LeftButton, pos=QPoint(x, 10))


def test_click_on_strip_goes_to_photo_and_publishes(app):
    app.wait_open()
    _click_cell(app.screen.strip, 3)
    assert app.active_name() == "фото 004.jpg"
    assert app.screen.strip.current == 3
    assert [p["index"] for n, p in app.events if n == "photo.changed"] == [3]
    assert app.screen.hasFocus() or not app.window.isActiveWindow()  # стрелки продолжают работать после клика
    app.press(Qt.Key_Right)
    assert app.active_name() == "фото 005.jpg"


def test_click_in_gap_between_cells_does_nothing(app):
    app.wait_open()
    strip = app.screen.strip
    QTest.mouseClick(strip, Qt.LeftButton, pos=QPoint(strip._cell_width + GAP // 2, 10))
    assert app.active_name() == "фото 001.jpg"


def test_strip_follows_active_window_not_reference(app):
    app.wait_open()
    app.screen.set_layout(3)
    app.wait_shown()
    assert app.screen.strip.current == 0
    QTest.mouseClick(app.screen.views[2], Qt.LeftButton)
    assert app.screen.strip.current == 1
    _click_cell(app.screen.strip, 4)
    assert Path(app.screen.views[2].path).name == "фото 005.jpg"
    assert Path(app.screen.views[1].path).name == "фото 001.jpg"
    assert Path(app.screen.views[0].path).name == "фото 001.jpg"


def test_strip_click_ignored_during_flicker(app):
    app.wait_open()
    _space(app.screen, QTest.Press)
    _click_cell(app.screen.strip, 3)
    _space(app.screen, QTest.Release)
    assert app.active_name() == "фото 001.jpg"


def test_arrow_buttons_flip_and_disable_at_edges(app):
    app.wait_open()
    screen = app.screen
    assert not screen.prev_button.isEnabled() and screen.next_button.isEnabled()
    screen.next_button.click()
    assert app.active_name() == "фото 002.jpg"
    assert screen.prev_button.isEnabled()
    screen.go(5)
    assert not screen.next_button.isEnabled()
    assert screen.prev_button.focusPolicy() == Qt.NoFocus


def test_thumbnails_appear_and_only_visible_are_kept(app):
    app.wait_open()
    strip = app.screen.strip
    first, last = strip.visible()
    app.qtbot.waitUntil(lambda: len(strip._thumbs) == last - first, timeout=5000)
    assert last - first == 6


def test_marks_come_from_database(app):
    app.wait_open()  # первое чтение папки идёт в фоне: отметки ставим после него и открываем заново
    folders = app.ctx.services.get("folders")
    stored = folders.photos(app.folder.id)
    folders.mark_photo(stored[1].id, "type:2")
    folders.mark_photo(stored[2].id, "defect", "S1")
    app.feature.open_folder(app.folder.id)
    strip = app.screen.strip
    app.qtbot.waitUntil(lambda: strip._items[1].mark_color is not None, timeout=5000)
    assert strip._items[0].mark_color is None
    assert strip._items[1].mark_color.name() == "#f2a93b"
    assert strip._items[2].mark_color.name() == "#ff5a5f"


def test_neighbors_reach_memory_ahead_of_flipping(app):
    app.wait_open()
    cache = app.ctx.services.get("image_cache")
    app.screen.go(2)
    in_memory = lambda number: cache._memory.best(str(app.path / "фото {:03d}.jpg".format(number)), L1)
    app.qtbot.waitUntil(lambda: all(in_memory(n) and in_memory(n).level >= L1 for n in (4, 5, 2)), timeout=5000)


def test_folder_is_warmed_on_disk_on_open(app):
    app.wait_open()
    cache = app.ctx.services.get("image_cache")
    app.qtbot.waitUntil(lambda: cache.wait_idle(0.01), timeout=5000)
    assert len(list((app.path.parent.parent / "кэш").rglob("*.*"))) >= 2 * 6  # L0 и L1 всех фото


def test_held_arrow_requests_no_thumbnails_until_stop(app, monkeypatch):
    app.wait_open()
    calls = []
    monkeypatch.setattr(app.screen.strip, "request_visible", lambda: calls.append(1))
    for _ in range(4):
        _key(app.screen, QEvent.KeyPress, Qt.Key_Right, auto=True)
    assert not calls
    app.qtbot.waitUntil(lambda: bool(calls), timeout=2000)
    assert len(calls) == 1


def test_strip_hidden_for_empty_folder(tmp_path, qtbot):
    app = App(tmp_path, qtbot, count=0)
    try:
        app.feature.open_folder(app.folder.id)
        app.qtbot.waitUntil(lambda: app.feature.folder is not None, timeout=5000)
        assert not app.screen.strip_panel.isVisible()
    finally:
        app.stop()


# --- отметки (шаг 3.4) -----------------------------------------------------------
# в порядке показа: фото сортируются по имени
REAL_NAMES = ["0211040001792_1_WFL8GKHR_2.jpg", "0402290000836_1_XZ79070.jpg", "IMG_0003.jpg"]


def _db_photos(app):
    return app.ctx.services.get("folders").photos(app.folder.id)


def _wait_db(app, check):
    app.qtbot.waitUntil(lambda: check(_db_photos(app)), timeout=5000)


def _marked_events(app):
    return [payload for name, payload in app.events if name == "photo.marked"]


@pytest.fixture
def named(tmp_path, qtbot):
    app = App(tmp_path, qtbot, count=3, names=REAL_NAMES)
    yield app
    app.stop()


def test_mark_key_saves_and_updates_everything(app):
    app.wait_open()
    app.press(Qt.Key_Right)
    app.press(Qt.Key_2)
    _wait_db(app, lambda photos: photos[1].mark == "type:2")
    screen = app.screen
    app.qtbot.waitUntil(lambda: screen.strip._items[1].mark_color is not None, timeout=5000)
    assert screen.strip._items[1].mark_color.name() == "#f2a93b"
    assert screen.mark_buttons["type:2"].isChecked() and not screen.mark_buttons["type:1"].isChecked()
    assert "Тип 2: 1" in screen.counts_label.text() and "Без отметки: 5" in screen.counts_label.text()
    assert _marked_events(app) == [{"photo_id": _db_photos(app)[1].id, "mark": "type:2", "sn": None}]
    assert _db_photos(app)[1].marked_at


def test_same_mark_again_removes_it(app):
    app.wait_open()
    app.press(Qt.Key_1)
    _wait_db(app, lambda photos: photos[0].mark == "type:1")
    app.qtbot.waitUntil(lambda: app.screen.mark_buttons["type:1"].isChecked(), timeout=5000)
    app.press(Qt.Key_1)
    _wait_db(app, lambda photos: photos[0].mark is None)
    app.qtbot.waitUntil(lambda: app.screen.strip._items[0].mark_color is None, timeout=5000)
    assert "Без отметки: 6" in app.screen.counts_label.text()


def test_button_marks_like_the_key(app):
    app.wait_open()
    app.screen.mark_buttons["remark"].click()
    _wait_db(app, lambda photos: photos[0].mark == "remark")


def test_first_mark_puts_folder_in_work_and_tells_folders_panel(app):
    app.wait_open()
    folders = app.ctx.services.get("folders")
    assert folders.get(app.folder.id).status == "new"
    app.press(Qt.Key_1)
    app.qtbot.waitUntil(lambda: folders.get(app.folder.id).status == "in_work", timeout=5000)
    app.qtbot.waitUntil(lambda: app.feature.folder.status == "in_work", timeout=5000)


def test_defect_takes_sn_from_file_name(named):
    named.wait_open()
    named.press(Qt.Key_D)
    _wait_db(named, lambda photos: photos[0].mark == "defect")
    assert _db_photos(named)[0].sn == "WFL8GKHR"  # окончание `_2` в SN не входит
    named.qtbot.waitUntil(lambda: named.screen.defect_box.isVisibleTo(named.screen), timeout=5000)
    assert named.screen.sn_edit.text() == "WFL8GKHR"
    assert _marked_events(named)[-1]["sn"] == "WFL8GKHR"
    named.press(Qt.Key_Right)
    named.press(Qt.Key_D)
    _wait_db(named, lambda photos: photos[1].mark == "defect")
    assert _db_photos(named)[1].sn == "XZ79070"


def test_defect_with_unknown_name_has_empty_sn(named):
    named.wait_open()
    named.screen.go(2)
    named.wait_shown()
    named.press(Qt.Key_D)
    _wait_db(named, lambda photos: photos[2].mark == "defect")
    assert _db_photos(named)[2].sn is None
    named.qtbot.waitUntil(lambda: named.screen.defect_box.isVisibleTo(named.screen), timeout=5000)
    assert named.screen.sn_edit.text() == ""


def test_sn_and_kind_can_be_corrected(named):
    named.wait_open()
    named.press(Qt.Key_D)
    _wait_db(named, lambda photos: photos[0].mark == "defect")
    screen = named.screen
    named.qtbot.waitUntil(lambda: screen.defect_box.isVisibleTo(screen), timeout=5000)
    screen.sn_edit.setFocus()
    screen.sn_edit.setText("ZZ1")
    screen.sn_edit.returnPressed.emit()
    screen.sn_edit.editingFinished.emit()
    _wait_db(named, lambda photos: photos[0].sn == "ZZ1")
    screen.kind_box.setCurrentIndex(2)
    screen.kind_box.activated.emit(2)
    expected = screen.kind_box.itemData(2)
    _wait_db(named, lambda photos: photos[0].defect_kind == expected)
    assert expected and _db_photos(named)[0].sn == "ZZ1"


def test_changing_mark_keeps_hand_typed_sn(named):
    named.wait_open()
    named.screen.go(2)  # имя не разобрано: SN вводят руками
    named.wait_shown()
    named.press(Qt.Key_D)
    screen = named.screen
    named.qtbot.waitUntil(lambda: screen.defect_box.isVisibleTo(screen), timeout=5000)
    screen.sn_edit.setText("ZZ1")
    screen.sn_edit.editingFinished.emit()
    _wait_db(named, lambda photos: photos[2].sn == "ZZ1")
    named.press(Qt.Key_2)
    _wait_db(named, lambda photos: photos[2].mark == "type:2")
    named.qtbot.waitUntil(lambda: screen.mark_buttons["type:2"].isChecked(), timeout=5000)
    assert _db_photos(named)[2].sn == "ZZ1" and screen.model.photos[2].sn == "ZZ1"


def test_typing_in_sn_field_does_not_mark_or_flip(named):
    named.wait_open()
    named.press(Qt.Key_D)
    screen = named.screen
    named.qtbot.waitUntil(lambda: screen.defect_box.isVisibleTo(screen), timeout=5000)
    screen.sn_edit.setFocus()
    QTest.keyClicks(screen.sn_edit, "d1")  # буквы и цифры уходят в поле, а не в отметки
    assert screen.sn_edit.text().endswith("d1")
    assert named.active_name() == REAL_NAMES[0]
    assert _db_photos(named)[0].mark == "defect"


def test_mark_is_refused_during_flicker_and_while_photo_not_shown(app, monkeypatch):
    app.wait_open()
    _space(app.screen, QTest.Press)
    assert not app.screen.can_mark
    app.press(Qt.Key_1)
    _space(app.screen, QTest.Release)
    app.wait_shown()
    assert app.screen.can_mark
    monkeypatch.setattr(type(app.screen.active_view()), "is_current_shown", property(lambda self: False))
    assert not app.screen.can_mark
    app.press(Qt.Key_1)
    app.screen.mark_buttons["defect"].setEnabled(True)  # даже если кнопку включили силой, отметка не пройдёт
    app.screen.mark_buttons["defect"].click()
    app.qtbot.wait(150)
    assert [photo.mark for photo in _db_photos(app)] == [None] * 6
    assert _marked_events(app) == []


def test_buttons_are_disabled_while_flickering(app):
    app.wait_open()
    _space(app.screen, QTest.Press)
    assert not any(button.isEnabled() for button in app.screen.mark_buttons.values())
    _space(app.screen, QTest.Release)
    app.qtbot.waitUntil(lambda: all(button.isEnabled() for button in app.screen.mark_buttons.values()), timeout=5000)


def test_failed_write_leaves_mark_unchanged_and_says_so(app, monkeypatch):
    app.wait_open()
    folders = app.ctx.services.get("folders")

    def broken(*args, **kwargs):
        raise OSError("сеть пропала")

    monkeypatch.setattr(folders, "mark_photo", broken)
    app.press(Qt.Key_1)
    app.qtbot.waitUntil(lambda: bool(app.screen.marks_status.text()), timeout=5000)
    assert not app.screen.mark_buttons["type:1"].isChecked()
    assert app.screen.strip._items[0].mark_color is None
    assert _marked_events(app) == []
    monkeypatch.undo()
    app.press(Qt.Key_1)
    app.qtbot.waitUntil(lambda: app.screen.mark_buttons["type:1"].isChecked(), timeout=5000)
    assert app.screen.marks_status.text() == ""


def test_two_quick_marks_land_in_order(app):
    app.wait_open()
    app.press(Qt.Key_1)
    app.press(Qt.Key_2)
    app.press(Qt.Key_3)
    _wait_db(app, lambda photos: photos[0].mark == "type:3")
    app.qtbot.waitUntil(lambda: app.screen.mark_buttons["type:3"].isChecked(), timeout=5000)


def test_mark_applies_to_active_window_photo(app):
    app.wait_open()
    app.screen.set_layout(3)
    app.wait_shown()
    app.screen._on_view_clicked(app.screen.views[2])
    app.press(Qt.Key_2)
    _wait_db(app, lambda photos: photos[1].mark == "type:2")
    assert _db_photos(app)[0].mark is None  # эталон и первое окно не затронуты


def test_marks_panel_hidden_without_photos(tmp_path, qtbot):
    app = App(tmp_path, qtbot, count=0)
    try:
        app.feature.open_folder(app.folder.id)
        app.qtbot.waitUntil(lambda: app.feature.folder is not None, timeout=5000)
        assert app.screen.marks_panel.isHidden()
        app.press(Qt.Key_1)  # нет фото: ничего не падает
    finally:
        app.stop()


def test_mark_keys_come_from_hotkeys_file(tmp_path, qtbot):
    app = App(tmp_path, qtbot)
    try:
        assert app.screen.mark_buttons["defect"].toolTip().endswith("D")
        assert set(app.screen.mark_buttons) == {"type:1", "type:2", "type:3", "defect", "remark"}
    finally:
        app.stop()
