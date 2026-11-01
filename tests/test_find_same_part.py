"""«Найти такую же деталь»: поиск в своём и соседних проектах, эталон из чужой папки, листание и ракурсы."""
from datetime import date
from pathlib import Path

import pytest
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtTest import QTest

from tests.test_compare_flow import App, _photos

TODAY = date.today()
THIS_YEAR = "{}-01-02".format(TODAY.year)
LAST_YEAR = "{}-12-30".format(TODAY.year - 1)
PART = "ssd xs-2280"  # то же имя, что у детали в приложении, но другой регистр и разделитель
ANGLES = ["0402290000836_1_AA11.jpg", "0402290000836_1_BB22.jpg", "0402290000836_2_AA11.jpg"]


@pytest.fixture
def app(tmp_path, qtbot):
    instance = App(tmp_path, qtbot, count=4)
    instance.wait_open()
    yield instance
    instance.stop()


def _add_folder(app, kind, project, device, date_text, names, part=PART):
    services = app.ctx.services
    found = services.get("parts").ensure(kind, project, device, part)
    path = app.path.parent / "{}_{}_{}".format(project, device, date_text)
    _photos(path, len(names), names=names)
    folder = services.get("folders").add(found.id, str(path), date_text)
    services.get("folders").add_photos(folder.id, names)
    return folder


def _message(app):
    return app.window.statusBar().currentMessage()


def _find(app):
    app.screen.find_button.click()
    assert not app.screen.find_button.isEnabled()  # пока ищем, второй запрос не нужен
    app.qtbot.waitUntil(lambda: app.screen.find_button.isEnabled(), timeout=5000)


def _wait_shown(app):
    app.qtbot.waitUntil(lambda: all(view.is_current_shown for view in app.screen.group.views), timeout=5000)


def _windows(app):
    """Имена фото по окнам: первое — эталон."""
    return [Path(view.path).name for view in app.screen.views[:app.screen.model.count]]


def _ref_name(app):
    return Path(app.screen.model.reference.path).name


def _click(view):
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, QPoint(view.width() // 2, view.height() // 2))


def test_button_works_only_with_open_folder(tmp_path, qtbot):
    instance = App(tmp_path, qtbot, count=2)
    try:
        assert not instance.screen.find_button.isEnabled()
        instance.wait_open()
        assert instance.screen.find_button.isEnabled()
    finally:
        instance.stop()


def test_own_project_found_and_shown_as_reference_in_layout_2(app):
    _add_folder(app, "A", "Орион-24", "N16", LAST_YEAR, ["x1.jpg", "x2.jpg", "x3.jpg"])
    _add_folder(app, "A", "Орион-24", "N17", "2026-10-30", ["y1.jpg", "y2.jpg"])
    _add_folder(app, "A", "Лира", "L1", THIS_YEAR, ["z1.jpg"])  # другой проект: пока есть свой, не нужен
    assert app.screen.model.count == 1
    _find(app)
    model = app.screen.model
    assert model.count == 2 and [p.name for p in model.ref_photos] == ["y1.jpg", "y2.jpg"]
    assert _ref_name(app) == "y1.jpg"
    _wait_shown(app)
    assert _windows(app) == ["y1.jpg", "фото 001.jpg"]
    assert app.feature.current_folder().id == app.folder.id  # текущая папка осталась открытой
    assert "Эталон: Орион-24, 2026-10-30" in app.screen.reference_label.text()
    assert "нет такой детали" not in _message(app)


def test_current_folder_is_not_its_own_reference(app):
    _find(app)
    assert not app.screen.model.has_reference_folder
    assert "ни в этом проекте, ни в соседних" in _message(app)
    assert app.screen.model.count == 1  # вид не изменился


def test_neighbor_project_of_same_kind_with_warning(app):
    _add_folder(app, "B", "Вега", "V1", THIS_YEAR, ["b1.jpg"])  # другой вид проектов
    _add_folder(app, "A", "Сириус", "S1", THIS_YEAR, ["near.jpg"])
    _find(app)
    assert _ref_name(app) == "near.jpg"
    assert "В проекте нет такой детали, взята из проекта Сириус, " in _message(app)
    assert app.screen.reference_label.text().startswith("Эталон: в проекте нет такой детали")
    assert app.screen._reference_tag == "ЭТАЛОН · ДРУГОЙ ПРОЕКТ"


def test_other_kind_only_means_not_found(app):
    _add_folder(app, "B", "Вега", "V1", THIS_YEAR, ["b1.jpg"])
    _find(app)
    assert not app.screen.model.has_reference_folder


def test_neighbor_search_takes_latest_of_current_year(app):
    _add_folder(app, "A", "Лира", "L1", "{}-01-03".format(TODAY.year), ["early.jpg"])
    _add_folder(app, "A", "Сириус", "S1", "{}-01-05".format(TODAY.year), ["late.jpg"])
    _find(app)
    assert _ref_name(app) == "late.jpg"


def test_neighbors_of_last_year_are_not_searched(app):
    _add_folder(app, "A", "Лира", "L1", LAST_YEAR, ["old.jpg"])
    _find(app)
    assert not app.screen.model.has_reference_folder
    assert "ни в этом проекте, ни в соседних" in _message(app)


def test_year_limit_is_a_setting(app):
    _add_folder(app, "A", "Лира", "L1", LAST_YEAR, ["old.jpg"])
    app.ctx.config.app.setdefault("compare", {})["neighbor_search_year_only"] = False
    _find(app)
    assert _ref_name(app) == "old.jpg"


def test_days_limit_is_a_setting(app):
    _add_folder(app, "A", "Лира", "L1", LAST_YEAR, ["old.jpg"])
    app.ctx.config.app.setdefault("compare", {}).update(neighbor_search_year_only=False, neighbor_search_days=5)
    _find(app)
    assert not app.screen.model.has_reference_folder


def test_folder_without_photos_is_skipped(app):
    services = app.ctx.services
    found = services.get("parts").ensure("A", "Орион-24", "N16", PART)
    services.get("folders").add(found.id, str(app.path.parent / "пустая"), "2026-10-30")
    _add_folder(app, "A", "Орион-24", "N17", "2026-10-01", ["ok.jpg"])
    _find(app)
    assert _ref_name(app) == "ok.jpg"


def test_active_reference_flips_found_folder_and_blocks_marks(app):
    _add_folder(app, "A", "Орион-24", "N16", "2026-10-30", ["r1.jpg", "r2.jpg", "r3.jpg"])
    _find(app)
    _wait_shown(app)
    screen, model = app.screen, app.screen.model
    app.events.clear()
    assert model.active_index == 0 and not model.reference_active
    _click(screen.views[0])
    assert model.reference_active and screen.active_view() is screen.views[0]
    app.press(Qt.Key_Right)
    app.press(Qt.Key_Right)
    app.press(Qt.Key_Right)  # на краю останавливается
    assert _ref_name(app) == "r3.jpg" and model.ref_index == 2
    assert model.active_index == 0 and model.current(0).name == "фото 001.jpg"
    assert not [item for item in app.events if item[0] == "photo.changed"]
    _wait_shown(app)  # фото дошло: отметке мешает только то, что активен эталон
    assert screen.active_view().is_current_shown
    assert not screen.can_mark and not any(button.isEnabled() for button in screen.mark_buttons.values())
    screen.request_mark("type:1")
    folders = app.ctx.services.get("folders")
    assert all(photo.mark is None for photo in folders.photos(app.folder.id))
    app.press(Qt.Key_Left)
    assert _ref_name(app) == "r2.jpg"
    _click(screen.views[1])  # назад к текущему окну: стрелки листают текущую папку
    assert not model.reference_active
    app.press(Qt.Key_Right)
    assert app.active_name() == "фото 002.jpg" and _ref_name(app) == "r2.jpg"
    assert [item[1]["index"] for item in app.events if item[0] == "photo.changed"] == [1]


def test_strip_follows_the_active_window(app):
    _add_folder(app, "A", "Орион-24", "N16", "2026-10-30", ["r1.jpg", "r2.jpg"])
    _find(app)
    strip = app.screen.strip
    assert len(app.screen.model.photos) == 4
    _click(app.screen.views[0])
    assert app.screen._strip_source == "reference" and not app.screen.prev_button.isEnabled()
    assert app.screen.next_button.isEnabled()
    app.press(Qt.Key_Right)
    assert not app.screen.next_button.isEnabled() and app.screen.prev_button.isEnabled()
    _click(app.screen.views[1])
    assert app.screen._strip_source == "folder" and strip is app.screen.strip


def test_single_reference_still_cannot_be_flipped(app):
    app.screen.set_layout(2)
    _wait_shown(app)
    _click(app.screen.views[0])
    assert not app.screen.model.reference_active


def test_angle_buttons_pick_the_first_photo_of_angle(app):
    _add_folder(app, "A", "Орион-24", "N16", "2026-10-30", ANGLES)
    _find(app)
    screen = app.screen
    assert sorted(screen._angle_buttons) == [1, 2]
    assert _ref_name(app) == ANGLES[0] and screen._angle_buttons[1].isChecked()
    screen._angle_buttons[2].click()
    _wait_shown(app)
    assert _ref_name(app) == ANGLES[2] and screen._angle_buttons[2].isChecked() and not screen._angle_buttons[1].isChecked()
    assert _windows(app)[0] == ANGLES[2]
    assert not screen.model.reference_active  # выбор ракурса не меняет активное окно


def test_no_angle_buttons_for_unparsed_names(app):
    _add_folder(app, "A", "Орион-24", "N16", "2026-10-30", ["a.jpg", "b.jpg"])
    _find(app)
    assert not app.screen._angle_buttons


def test_flipping_reference_updates_checked_angle(app):
    _add_folder(app, "A", "Орион-24", "N16", "2026-10-30", ANGLES)
    _find(app)
    _click(app.screen.views[0])
    app.screen._angle_buttons[2].click()
    assert app.screen.model.ref_index == 2
    app.press(Qt.Key_Left)
    assert _ref_name(app) == ANGLES[1] and app.screen._angle_buttons[1].isChecked()


def test_opening_another_folder_drops_found_reference(app):
    _add_folder(app, "A", "Орион-24", "N16", "2026-10-30", ["r1.jpg", "r2.jpg"])
    _find(app)
    assert app.screen.model.has_reference_folder
    app.feature.open_folder(app.folder.id)
    app.qtbot.waitUntil(lambda: not app.screen.model.has_reference_folder, timeout=5000)
    assert not app.screen.reference_bar.isVisible()
    assert _ref_name(app) == "фото 001.jpg"


def test_layout_1_hides_reference_and_it_returns(app):
    _add_folder(app, "A", "Орион-24", "N16", "2026-10-30", ["r1.jpg", "r2.jpg"])
    _find(app)
    _click(app.screen.views[0])
    app.screen.set_layout(1)
    assert not app.screen.model.reference_active and not app.screen.reference_bar.isVisible()
    app.screen.set_layout(3)
    _wait_shown(app)
    assert _windows(app)[0] == "r1.jpg" and app.screen.reference_bar.isVisible()


def test_flicker_shows_found_reference_in_active_window(app):
    _add_folder(app, "A", "Орион-24", "N16", "2026-10-30", ["r1.jpg", "r2.jpg"])
    _find(app)
    _wait_shown(app)
    app.screen._begin_flicker()
    assert Path(app.screen.active_view().path).name == "r1.jpg"
    app.screen._end_flicker()
    assert app.active_name() == "фото 001.jpg"


def test_service_set_reference_folder(app):
    other = _add_folder(app, "A", "Орион-24", "N16", "2026-10-30", ["r1.jpg", "r2.jpg"], part="Другая")
    app.feature.set_reference_folder(other.id)
    app.qtbot.waitUntil(lambda: app.screen.model.has_reference_folder, timeout=5000)
    assert _ref_name(app) == "r1.jpg" and app.screen.model.count == 2


def test_late_answer_for_previous_folder_is_ignored(app):
    _add_folder(app, "A", "Орион-24", "N16", "2026-10-30", ["r1.jpg"])
    app.screen.find_button.click()
    app.feature.open_folder(app.folder.id)  # новая папка: ответ поиска прежней папки не нужен
    app.qtbot.wait(500)
    assert not app.screen.model.has_reference_folder
