"""Режим «Ракурсы» в настоящем приложении: настоящие JPEG, база, клавиши и мышь."""
from pathlib import Path

import pytest
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QPushButton

from atlas.core.theme import apply_theme

from tests.test_compare_flow import App

NAMES = [
    "1_1_A.jpg", "1_2_A.jpg",
    "1_1_B.jpg",              # нет ракурса 2
    "1_2_C.jpg",              # нет ракурса 1
    "чужое имя.jpg",
    "1_1_D.jpg", "1_1_D_x.jpg", "1_2_D.jpg",  # повтор
]


@pytest.fixture
def app(tmp_path, qtbot):
    instance = App(tmp_path, qtbot, count=len(NAMES), names=NAMES)
    instance.wait_open()
    instance.screen.set_angles_mode(True)
    instance.wait_shown()
    yield instance
    instance.stop()


def shown(app):
    return [Path(view.path).name if view.path else None for view in app.screen.views[:2]]


def click(app, view):
    QTest.mouseClick(view, Qt.LeftButton, pos=QPoint(20, 20))


def test_windows_match_angles_and_listing_moves_all(app):
    assert [view.isVisible() for view in app.screen.views] == [True, True, False, False]
    assert shown(app) == ["1_1_A.jpg", "1_2_A.jpg"]
    app.press(Qt.Key_Right)
    assert shown(app) == ["1_1_B.jpg", None]
    assert app.screen.views[1]._message.text() == "Нет ракурса 2"
    app.press(Qt.Key_Right)
    assert shown(app) == [None, "1_2_C.jpg"]
    assert app.screen.views[0]._message.text() == "Нет ракурса 1"
    app.press(Qt.Key_Right)
    assert shown(app) == ["1_1_D.jpg", "1_2_D.jpg"]
    assert app.screen.views[0]._message.text() == ""
    app.press(Qt.Key_Right)  # конец папки, SN всего 4
    assert shown(app) == ["1_1_D.jpg", "1_2_D.jpg"]


def test_one_cancel_for_all_windows(app):
    cache = app.ctx.services.get("image_cache")
    calls = []
    original = cache.cancel_pending
    cache.cancel_pending = lambda: (calls.append(1), original())
    app.press(Qt.Key_Right)
    app.press(Qt.Key_Right)
    assert len(calls) == 2
    cache.cancel_pending = original


def test_zoom_is_per_window_and_survives_listing(app):
    screen = app.screen
    first, second = screen.views[:2]
    assert screen.sync_button.isHidden()
    click(app, first)
    plus_state = second.state()
    screen.group.zoom_by(2.0)
    zoomed = first.state()
    assert zoomed[0] > 1 and second.state() == plus_state
    click(app, second)
    assert screen.zoom_label.text() == "100%"
    app.press(Qt.Key_Right)
    app.press(Qt.Key_Right)
    app.press(Qt.Key_Right)
    app.wait_shown()
    assert first.state()[0] == zoomed[0] and second.state() == plus_state


def test_mode_states_are_kept_apart(app):
    screen = app.screen
    click(app, screen.views[0])
    screen.group.zoom_by(2.0)
    angle_zoom = screen.views[0].state()[0]
    screen.set_angles_mode(False)
    assert not screen.sync_button.isHidden() and screen.group.enabled
    assert screen.active_view().state()[0] == 1.0
    screen.set_angles_mode(True)
    assert not screen.group.enabled
    assert screen.views[0].state()[0] == angle_zoom


def test_switch_keeps_the_same_photo(app):
    screen = app.screen
    app.press(Qt.Key_Right)
    app.press(Qt.Key_Right)
    click(app, screen.views[1])
    screen.set_angles_mode(False)
    assert app.active_name() == "1_2_C.jpg"
    screen.go(1)  # 1_1_B.jpg: в папке фото идут по имени
    assert app.active_name() == "1_1_B.jpg"
    screen.set_angles_mode(True)
    assert shown(app) == ["1_1_B.jpg", None]
    assert screen.angles.active == 0


def test_strip_goes_by_sn(app):
    screen = app.screen
    assert len(screen.strip._items) == 4
    screen.strip.clicked.emit(3)
    assert shown(app) == ["1_1_D.jpg", "1_2_D.jpg"]
    screen.set_angles_mode(False)
    assert len(screen.strip._items) == len(NAMES)


def test_notes_show_unparsed_and_repeat(app):
    text = app.screen.angles_label.text()
    assert not app.screen.angles_bar.isHidden()
    assert "1_1_D.jpg, 1_1_D_x.jpg" in text and "не разобрано у фото: 1" in text
    app.screen.set_angles_mode(False)
    assert app.screen.angles_bar.isHidden()


def test_mark_goes_to_active_window_photo(app):
    screen = app.screen
    click(app, screen.views[1])
    app.wait_shown()
    app.press(Qt.Key_D)
    app.qtbot.waitUntil(lambda: screen.mark_buttons["defect"].isChecked(), timeout=5000)
    folders = app.ctx.services.get("folders")
    marked = {photo.rel_path: photo for photo in folders.photos(app.folder.id) if photo.mark}
    assert list(marked) == ["1_2_A.jpg"] and marked["1_2_A.jpg"].sn == "A"
    assert "ракурс 2" in screen.marks_title.text()


def test_no_mark_on_missing_angle(app):
    screen = app.screen
    app.press(Qt.Key_Right)
    click(app, screen.views[1])
    assert not screen.can_mark
    assert not screen.mark_buttons["defect"].isEnabled()
    events = len(app.events)
    app.press(Qt.Key_D)
    QTest.qWait(50)
    assert len(app.events) == events


def test_listing_publishes_active_photo(app):
    app.press(Qt.Key_Right)
    name, payload = app.events[-1]
    assert name == "photo.changed" and payload["index"] == 1  # 1_1_B.jpg, номер в папке


def test_space_does_nothing(app):
    app.press(Qt.Key_Space)
    assert not app.screen.flickering


def test_reference_request_returns_to_compare(app, tmp_path):
    screen = app.screen
    screen.set_reference_folder(screen.model.photos[:2], "тест")
    assert not screen.angles_mode and not screen.reference_bar.isHidden()
    assert screen.compare_mode_button.isChecked() and not screen.angles_mode_button.isChecked()


def test_new_folder_keeps_mode(app):
    app.press(Qt.Key_Right)
    app.feature.open_folder(app.folder.id)
    app.qtbot.waitUntil(lambda: app.screen.angles.index == 0, timeout=5000)
    assert app.screen.angles_mode and shown(app) == ["1_1_A.jpg", "1_2_A.jpg"]


@pytest.mark.parametrize("names, windows", [(["1_1_A.jpg", "1_1_B.jpg"], 1), (["1_{}_A.jpg".format(n) for n in range(1, 7)], 4)])
def test_window_count(tmp_path, qtbot, names, windows):
    app = App(tmp_path, qtbot, count=len(names), names=names)
    try:
        app.wait_open()
        app.screen.set_angles_mode(True)
        app.wait_shown()
        assert sum(view.isVisible() for view in app.screen.views) == windows
        if windows == 4:
            assert "Ещё ракурсов: 2" in app.screen.angles_label.text()
    finally:
        app.stop()


def test_no_parsed_names(tmp_path, qtbot):
    app = App(tmp_path, qtbot, count=2, names=["a.jpg", "b.jpg"])
    try:
        app.wait_open()
        app.screen.set_angles_mode(True)
        assert not app.screen.message.isHidden() and "разобрано" in app.screen.message.text()
        assert app.screen.strip_panel.isHidden()
        app.press(Qt.Key_Right)  # ничего не падает
        app.screen.set_angles_mode(False)
        app.wait_shown()
        assert app.screen.message.isHidden() and not app.screen.strip_panel.isHidden()
    finally:
        app.stop()


def test_toolbar_buttons_are_not_cut_with_all_features_at_1024(tmp_path, qtbot, qapp):
    """Панель папок плюс кнопки раскладки: каждая кнопка панели помещается целиком."""
    apply_theme(qapp)
    app = App(tmp_path, qtbot, features=("compare", "folders", "sort_types"))
    try:
        app.wait_open()
        app.window.resize(1024, 700)
        QApplication.processEvents()
        bar = app.screen.compare_mode_button.parent()
        buttons = [button for button in bar.findChildren(QPushButton) if button.isVisible()]
        assert len(buttons) >= 12
        for button in buttons:
            assert button.width() >= button.sizeHint().width(), button.text()
    finally:
        app.stop()
