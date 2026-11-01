"""Разметка фото: модель и отмена, слой над PhotoView (мышь, поворот, рисование), функция annotate_tools в приложении."""
import pytest
from PyQt5.QtCore import QEvent, QObject, QPoint, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QKeySequence, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from atlas.shared.annotate import model
from atlas.shared.annotate.model import HISTORY_DEPTH, Crop, Ellipse, History, Label, from_screen, to_screen
from atlas.shared.annotate.overlay import TOOL_CROP, TOOL_ELLIPSE, TOOL_LABEL, AnnotationOverlay
from atlas.shared.annotate.store import AnnotationStore
from atlas.shared.viewer.levels import L1
from atlas.shared.viewer.memory_cache import CachedImage
from atlas.shared.viewer.photo_view import PhotoView

from tests.test_compare_flow import App

GREEN = QColor("#00FF00")
COLORS = {"defect": GREEN, "outline": QColor("#000001"), "crop": QColor("#FFFF00"), "dim": QColor(0, 0, 0, 200)}


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


def gray(width=864, height=1296):
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor("#808080"))
    return image


@pytest.fixture
def setup(qtbot):
    cache = FakeCache()
    cache.memory[("a", L1)] = CachedImage(gray(), L1)
    cache.memory[("b", L1)] = CachedImage(gray(), L1)
    view = PhotoView(cache, settle_ms=0)
    qtbot.addWidget(view)
    view.resize(500, 700)
    view.show()
    view.set_photo("a")
    store = AnnotationStore()
    asked = []
    overlay = AnnotationOverlay(store, COLORS, ask_text=lambda v: asked.append(v) or overlay.answer)
    overlay.answer = "Скол"
    overlay.attach(view)
    return view, store, overlay, asked


def drag(view, start, end, modifier=Qt.NoModifier, button=Qt.LeftButton):
    QTest.mousePress(view, button, modifier, QPoint(*start))
    point = QPoint(*end)  # QTest.mouseMove не передаёт зажатую кнопку, и событие не доходит до виджета
    QApplication.sendEvent(view, QMouseEvent(QEvent.MouseMove, point, point, Qt.NoButton, button, modifier))
    QTest.mouseRelease(view, button, modifier, QPoint(*end))


def count_color(view, color, region=None):
    image = view.grab().toImage()
    x0, y0, x1, y1 = region or (0, 0, image.width(), image.height())
    return sum(
        1 for x in range(x0, x1) for y in range(y0, y1) if image.pixelColor(x, y).rgb() == color.rgb()
    )


# --- модель -------------------------------------------------------------------
def test_history_undo_redo_and_redo_is_dropped_by_new_shape():
    history = History()
    a, b, c = Ellipse(0, 0, 0.5, 0.5), Ellipse(0.1, 0.1, 0.4, 0.4), Label(0.2, 0.2, "x")
    history.add(a)
    history.add(b)
    assert history.shapes == (a, b)
    assert history.undo() and history.shapes == (a,)
    assert history.redo() and history.shapes == (a, b)
    history.undo()
    history.add(c)
    assert history.shapes == (a, c) and not history.can_redo
    while history.undo():
        pass
    assert history.shapes == () and not history.undo()


def test_new_crop_replaces_old_and_undo_brings_it_back():
    history = History()
    first, second = Crop(0.1, 0.1, 0.5, 0.5), Crop(0.2, 0.2, 0.9, 0.9)
    history.add(first)
    history.add(Ellipse(0, 0, 0.3, 0.3))
    history.add(second)
    assert history.crop() == second and sum(isinstance(s, Crop) for s in history.shapes) == 1
    history.undo()
    assert history.crop() == first


def test_history_depth_is_limited():
    history = History()
    for number in range(HISTORY_DEPTH + 30):
        history.add(Label(0.1, 0.1, str(number)))
    steps = 0
    while history.undo():
        steps += 1
    assert steps == HISTORY_DEPTH - 1


def test_rect_is_normalized_and_clamped_and_keeps_its_class():
    shape = Crop(0.9, 1.4, -0.2, 0.3).normalized().clamped()
    assert isinstance(shape, Crop)
    assert (shape.x0, shape.y0, shape.x1, shape.y1) == (0.0, 0.3, 0.9, 1.0)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_screen_conversion_round_trips(rotation):
    assert from_screen(*to_screen(0.2, 0.7, rotation), rotation) == pytest.approx((0.2, 0.7))


def test_store_signals_and_forgets_old_photos(qtbot):
    store = AnnotationStore()
    with qtbot.waitSignal(store.changed) as signal:
        store.add("p", Ellipse(0, 0, 0.5, 0.5))
    assert signal.args == ["p"] and store.can_undo("p") and not store.can_redo("p")
    assert store.undo("p") and store.shapes("p") == () and store.can_redo("p")
    assert not store.undo("нет такого") and store.shapes("нет такого") == ()
    from atlas.shared.annotate import store as store_module
    for number in range(store_module.MAX_PHOTOS + 5):
        store.add(str(number), Label(0, 0, "x"))
    assert store.shapes("0") == () and store.shapes(str(store_module.MAX_PHOTOS + 4)) != ()


# --- слой над окном -------------------------------------------------------------
def test_without_tool_mouse_still_pans_and_nothing_is_drawn(setup):
    view, store, overlay, _ = setup
    view.zoom_by(3)
    before = view.state()
    drag(view, (250, 350), (200, 300))
    assert view.state() != before and store.shapes("a") == ()


def test_ellipse_is_stored_in_photo_fractions(setup):
    view, store, overlay, _ = setup
    overlay.set_tool(TOOL_ELLIPSE)
    start, end = QPoint(150, 250), QPoint(300, 400)
    drag(view, (start.x(), start.y()), (end.x(), end.y()))
    (shape,) = store.shapes("a")
    x0, y0 = view.widget_to_photo(start)
    x1, y1 = view.widget_to_photo(end)
    assert isinstance(shape, Ellipse)
    assert (shape.x0, shape.y0, shape.x1, shape.y1) == pytest.approx((x0, y0, x1, y1))
    assert 0 <= shape.x0 < shape.x1 <= 1 and 0 <= shape.y0 < shape.y1 <= 1


def test_ellipse_is_drawn_and_follows_the_photo_when_rotated(setup):
    view, store, overlay, _ = setup
    store.add("a", Ellipse(0.1, 0.1, 0.4, 0.3))  # в левом верхнем углу неповёрнутого фото
    overlay.set_tool(None)
    right_middle = (0.4, 0.2)
    for rotation in (0, 90, 180, 270):
        view.set_rotation(rotation)
        point = view.photo_to_widget(*right_middle)
        region = (int(point.x()) - 4, int(point.y()) - 4, int(point.x()) + 5, int(point.y()) + 5)
        assert count_color(view, GREEN, region) > 0, "обводка не там, где фото: поворот {}".format(rotation)
    # а на прежнем месте экрана после поворота её уже нет
    view.set_rotation(0)
    point0 = view.photo_to_widget(*right_middle)
    view.set_rotation(180)
    region = (int(point0.x()) - 3, int(point0.y()) - 3, int(point0.x()) + 4, int(point0.y()) + 4)
    assert count_color(view, GREEN, region) == 0


def test_drawing_on_a_rotated_photo_lands_in_unrotated_coordinates(setup):
    view, store, overlay, _ = setup
    view.set_rotation(90)  # левый верхний угол фото теперь справа вверху
    overlay.set_tool(TOOL_ELLIPSE)
    width, height = view.width(), view.height()
    drag(view, (int(width * 0.7), int(height * 0.3)), (int(width * 0.95), int(height * 0.4)))
    (shape,) = store.shapes("a")
    assert shape.x1 < 0.5 and shape.y1 < 0.5


def test_tiny_click_and_outside_photo_draw_nothing(setup):
    view, store, overlay, _ = setup
    overlay.set_tool(TOOL_ELLIPSE)
    drag(view, (200, 300), (201, 301))
    drag(view, (2, 2), (3, 3))  # серое поле вне фото: окно 500×700, фото уже
    assert store.shapes("a") == ()


def test_drag_beyond_the_photo_is_clamped_to_it(setup):
    view, store, overlay, _ = setup
    overlay.set_tool(TOOL_CROP)
    left, top, width, height = view._state.target_rect()
    drag(view, (int(left + width * 0.5), int(top + height * 0.5)), (int(left + width + 80), int(top + height + 80)))
    shape = store.crop("a")
    assert shape is not None and shape.x1 == 1.0 and shape.y1 == 1.0


def test_shift_drag_pans_instead_of_drawing(setup):
    view, store, overlay, _ = setup
    view.zoom_by(3)
    before = view.state()
    overlay.set_tool(TOOL_ELLIPSE)
    drag(view, (250, 350), (200, 300), modifier=Qt.ShiftModifier)
    assert view.state() != before and store.shapes("a") == ()


def test_double_click_with_tool_does_not_reset_zoom(setup):
    view, store, overlay, _ = setup
    view.zoom_by(3)
    zoom = view.state()[0]
    overlay.set_tool(TOOL_ELLIPSE)
    QTest.mouseDClick(view, Qt.LeftButton, Qt.NoModifier, QPoint(250, 350))
    assert view.state()[0] == zoom
    overlay.set_tool(None)
    QTest.mouseDClick(view, Qt.LeftButton, Qt.NoModifier, QPoint(250, 350))
    assert view.state()[0] == 1.0


def test_label_asks_text_and_is_drawn(setup):
    view, store, overlay, asked = setup
    overlay.set_tool(TOOL_LABEL)
    point = view.photo_to_widget(0.3, 0.4)
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, QPoint(int(point.x()), int(point.y())))
    (shape,) = store.shapes("a")
    assert shape == Label(pytest.approx(0.3, abs=0.01), pytest.approx(0.4, abs=0.01), "Скол") and len(asked) == 1
    assert count_color(view, GREEN) > 50
    overlay.answer = "   "
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, QPoint(int(point.x()), int(point.y()) + 100))
    overlay.answer = None  # отмена диалога
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, QPoint(int(point.x()), int(point.y()) + 100))
    assert len(store.shapes("a")) == 1


def test_label_keeps_upright_and_anchored_when_photo_is_rotated(setup):
    view, store, overlay, _ = setup
    store.add("a", Label(0.1, 0.1, "Скол"))
    view.set_rotation(90)
    anchor = view.photo_to_widget(0.1, 0.1)
    region = (int(anchor.x()) - 2, int(anchor.y()) - 2, int(anchor.x()) + 120, int(anchor.y()) + 60)
    assert count_color(view, GREEN, region) > 20


def test_crop_dims_everything_outside_and_is_replaced(setup):
    view, store, overlay, _ = setup
    before = view.grab().toImage()
    store.add("a", Crop(0.4, 0.4, 0.6, 0.6))
    after = view.grab().toImage()
    inside = view.photo_to_widget(0.5, 0.5)
    outside = view.photo_to_widget(0.1, 0.1)
    assert after.pixelColor(int(inside.x()), int(inside.y())) == before.pixelColor(int(inside.x()), int(inside.y()))
    assert after.pixelColor(int(outside.x()), int(outside.y())).red() < before.pixelColor(int(outside.x()), int(outside.y())).red()
    store.add("a", Crop(0.1, 0.1, 0.3, 0.3))
    assert store.crop("a") == Crop(0.1, 0.1, 0.3, 0.3)


def test_shapes_belong_to_the_photo_not_to_the_window(setup):
    view, store, overlay, _ = setup
    store.add("a", Ellipse(0.1, 0.1, 0.9, 0.9))
    assert count_color(view, GREEN) > 100
    view.set_photo("b")
    assert count_color(view, GREEN) == 0
    view.set_photo("a")
    assert count_color(view, GREEN) > 100


def test_undo_hides_the_shape_on_screen(setup):
    view, store, overlay, _ = setup
    store.add("a", Ellipse(0.1, 0.1, 0.9, 0.9))
    store.undo("a")
    assert count_color(view, GREEN) == 0
    store.redo("a")
    assert count_color(view, GREEN) > 100


def test_cursor_follows_tool(setup):
    view, store, overlay, _ = setup
    assert view.cursor().shape() == Qt.OpenHandCursor
    overlay.set_tool(TOOL_ELLIPSE)
    assert view.cursor().shape() == Qt.CrossCursor
    overlay.set_tool(TOOL_LABEL)
    assert view.cursor().shape() == Qt.IBeamCursor
    overlay.set_tool("нет такого")
    assert overlay.tool is None and view.cursor().shape() == Qt.OpenHandCursor


# --- функция в приложении -------------------------------------------------------
@pytest.fixture
def app(tmp_path, qtbot):
    instance = App(tmp_path, qtbot, count=3, features=("compare", "annotate_tools"))
    instance.tools = next(f.instance for f in instance.registry.loaded if f.spec.id == "annotate_tools")
    instance.wait_open()
    yield instance
    instance.stop()


def _drag_in_active(app, fractions=(0.3, 0.3, 0.6, 0.5)):
    view = app.screen.active_view()
    a = view.photo_to_widget(fractions[0], fractions[1])
    b = view.photo_to_widget(fractions[2], fractions[3])
    drag(view, (int(a.x()), int(a.y())), (int(b.x()), int(b.y())))
    return view


def test_tool_buttons_draw_undo_and_redo(app):
    tools = app.tools
    assert not tools.undo_button.isEnabled() and not tools.redo_button.isEnabled()
    tools.tool_buttons[TOOL_ELLIPSE].click()
    assert tools.overlay.tool == TOOL_ELLIPSE and tools.tool_buttons[TOOL_ELLIPSE].isChecked()
    view = _drag_in_active(app)
    assert len(tools.shapes(view.path)) == 1 and tools.undo_button.isEnabled()
    tools.undo_button.click()
    assert tools.shapes(view.path) == () and tools.redo_button.isEnabled() and not tools.undo_button.isEnabled()
    tools.redo_button.click()
    assert len(tools.shapes(view.path)) == 1


def test_clicking_the_checked_tool_turns_it_off_and_tools_exclude_each_other(app):
    tools = app.tools
    tools.tool_buttons[TOOL_CROP].click()
    tools.tool_buttons[TOOL_LABEL].click()
    assert tools.overlay.tool == TOOL_LABEL and not tools.tool_buttons[TOOL_CROP].isChecked()
    tools.tool_buttons[TOOL_LABEL].click()
    assert tools.overlay.tool is None and not tools.tool_buttons[TOOL_LABEL].isChecked()


def test_keyboard_shortcuts_undo_and_redo(app):
    tools = app.tools
    tools.tool_buttons[TOOL_ELLIPSE].click()
    view = _drag_in_active(app)
    QTest.keyClick(app.screen, Qt.Key_Z, Qt.ControlModifier)
    assert tools.shapes(view.path) == ()
    QTest.keyClick(app.screen, Qt.Key_Y, Qt.ControlModifier)
    assert len(tools.shapes(view.path)) == 1
    assert QKeySequence("Ctrl+Z").toString()  # клавиши берутся из data/hotkeys.json


def test_arrows_still_flip_photos_with_a_tool_selected(app):
    app.tools.tool_buttons[TOOL_ELLIPSE].click()
    first = app.active_name()
    app.press(Qt.Key_Right)
    app.qtbot.waitUntil(lambda: app.active_name() != first, timeout=3000)


def test_shapes_stay_with_their_photo_when_flipping(app):
    tools = app.tools
    tools.tool_buttons[TOOL_ELLIPSE].click()
    view = _drag_in_active(app)
    first_path = view.path
    app.press(Qt.Key_Right)
    app.qtbot.waitUntil(lambda: view.path != first_path and view.is_current_shown, timeout=3000)
    assert tools.shapes(view.path) == ()
    app.press(Qt.Key_Left)
    app.qtbot.waitUntil(lambda: view.path == first_path and view.is_current_shown, timeout=3000)
    assert len(tools.shapes(first_path)) == 1


def test_service_gives_shapes_and_crop_to_other_features(app):
    service = app.ctx.services.get("annotations")
    app.tools.tool_buttons[TOOL_CROP].click()
    view = _drag_in_active(app)
    assert isinstance(service.crop(view.path), Crop) and service.shapes(view.path) == (service.crop(view.path),)


def test_works_without_compare(tmp_path, qtbot):
    import json
    import shutil
    from tests.test_compare_flow import REPO
    from atlas.app import build_core, start_features
    from atlas.core.config import AppPaths

    root = tmp_path / "Атлас тест"
    (root / "config").mkdir(parents=True)
    shutil.copy(str(REPO / "config" / "app.json"), str(root / "config" / "app.json"))
    shutil.copytree(str(REPO / "data"), str(root / "data"))
    (root / "config" / "features.json").write_text(json.dumps({"features": [{"id": "annotate_tools"}]}), encoding="utf-8")
    ctx = build_core(AppPaths(root))
    registry = start_features(ctx)
    assert registry.failures == []
    tools = ctx.services.get("annotations")
    tools.tool_buttons[TOOL_ELLIPSE].click()  # окон нет: инструмент не включается, ничего не падает
    assert tools.overlay.tool is None and not tools.tool_buttons[TOOL_ELLIPSE].isChecked()
    tools.undo()
    registry.stop_all()
    assert ctx.services.get_optional("annotations") is None
