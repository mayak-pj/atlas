"""Улучшение фото при приближении (шаг 12.5): резкость в рабочем потоке, файл и кэш не меняются."""
import pytest
from PyQt5.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QMouseEvent, QColor, QImage, QPainter

from atlas.core.theme import apply_theme
from atlas.shared.viewer import enhance
from atlas.shared.viewer.levels import L1, L3
from atlas.shared.viewer.photo_view import PhotoView
from tests.test_photo_view import FakeCache


def board(width=400, height=300):
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor(90, 90, 90))
    painter = QPainter(image)
    painter.fillRect(150, 100, 100, 80, QColor(160, 160, 160))  # светлый предмет
    painter.fillRect(300, 100, 2, 80, QColor(130, 130, 130))  # тонкая дорожка
    painter.end()
    return image


def soft_board(width=400, height=300):
    """Плата с размытием: резкие края «Снять размытие» не трогает, а на размытом разница видна."""
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    image = board(width, height)
    ptr = image.constBits()
    ptr.setsize(image.byteCount())
    rows = np.frombuffer(ptr, np.uint8).reshape(height, image.bytesPerLine())[:, : width * 4].reshape(height, width, 4)
    blurred = cv2.GaussianBlur(np.ascontiguousarray(rows[:, :, :3]), (0, 0), 2.0)
    return QImage(blurred.data, width, height, blurred.strides[0], QImage.Format_RGB888).rgbSwapped().copy()


def gray(image, x, y):
    return image.pixel(x, y) & 255


def test_wants_enhance_only_when_magnified():
    assert enhance.wants_enhance(0.1, "deblur")  # любой масштаб: кнопка включена — работает и без зума
    assert enhance.wants_enhance(2.0, "deblur")
    assert not enhance.wants_enhance(4.0, None)


def blurred_text(sigma=1.6):
    import cv2
    import numpy as np
    base = np.full((120, 300, 3), (40, 70, 40), np.uint8)
    cv2.putText(base, "U12 SN74HC595", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (210, 210, 210), 1, cv2.LINE_AA)
    soft = cv2.GaussianBlur(base, (0, 0), sigma)
    return base, soft


@pytest.mark.parametrize("mode", ["deblur", "max"])
def test_deblur_modes_return_edges_without_inventing(qapp, mode):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    sharp, soft = blurred_text()
    image = QImage(soft.data, 300, 120, soft.strides[0], QImage.Format_RGB888).rgbSwapped().copy()
    out = enhance.enhanced_crop(image, QRectF(0, 0, 300, 120), 900, 360, mode)
    assert (out.width(), out.height()) == (900, 360)
    ptr = out.constBits()
    ptr.setsize(out.byteCount())
    got = np.frombuffer(ptr, np.uint8).reshape(360, out.bytesPerLine())[:, : 900 * 4].reshape(360, 900, 4)[:, :, :3]
    gray = lambda a: cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)
    reference = cv2.resize(gray(sharp), (900, 360), interpolation=cv2.INTER_CUBIC)
    plain = cv2.resize(gray(soft), (900, 360), interpolation=cv2.INTER_CUBIC)
    error = lambda a: float(np.mean(np.abs(cv2.GaussianBlur(a, (0, 0), 1.5) - cv2.GaussianBlur(reference, (0, 0), 1.5))))
    if mode == "deblur":
        assert error(gray(got)) < error(plain)  # ближе к настоящему резкому кадру, чем простое растяжение
    else:  # «Максимум» ещё и выравнивает контраст — яркость фона уже не сверяется, зато границы резче
        assert enhance._edge_energy(gray(got)) > enhance._edge_energy(plain) * 2


def test_sharp_photo_is_left_alone(qapp):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    sharp, _soft = blurred_text(0.01)
    image = QImage(sharp.data, 300, 120, sharp.strides[0], QImage.Format_RGB888).rgbSwapped().copy()
    assert enhance.estimate_sigma(cv2.cvtColor(sharp, cv2.COLOR_BGR2GRAY).astype(np.float32)) is None


def test_modes_file_and_fallback(tmp_path):
    from pathlib import Path
    modes = enhance.load_modes(Path(__file__).resolve().parent.parent / "data" / "enhance_modes.json")
    assert [m["id"] for m in modes] == ["deblur", "max", "pro"] and all(m["weight"] for m in modes)
    assert all("platforms" not in m for m in modes)  # «Pro» доступен и на Windows
    assert enhance.load_modes(tmp_path / "нет.json") == enhance.load_modes(None)
    assert enhance.usable_mode("nonsense") is None


def test_does_not_change_source_and_refuses_huge(qapp):
    source = board()
    before = source.copy()
    assert enhance.enhanced_crop(source, QRectF(0, 0, 100, 100), 5000, 5000) is None
    assert enhance.enhanced_crop(source, QRectF(0, 0, 100, 100), 400, 400, None) is None
    enhance.enhanced_crop(source, QRectF(0, 0, 100, 100), 400, 400)
    assert source == before


def test_photo_view_enhances_without_zoom(qtbot, qapp):
    apply_theme(qapp)
    cache = FakeCache()
    view = PhotoView(cache, settle_ms=10)
    view.resize(600, 500)
    qtbot.addWidget(view)
    view.show()
    assert view.enhance_mode is None  # по умолчанию выключено: включает кнопка «Качество»
    cache.memory[("a.jpg", L1)] = type("H", (), {"image": soft_board(1000, 750), "level": L1})()
    view.set_photo("a.jpg")
    qtbot.wait(50)
    assert view._enh_image is None
    view.set_enhance("deblur")  # зум 1 — «вписать»
    qtbot.waitUntil(lambda: view._enh_image is not None, timeout=3000)
    assert not view.grab().toImage().isNull()
    view.set_enhance(None)
    assert view._enh_image is None
    view.zoom_by(1.1)
    qtbot.wait(100)
    assert view._enh_image is None


def test_compare_screen_has_quality_button(qtbot, qapp):
    from atlas.features.compare import logic
    from atlas.features.compare.screen import CompareScreen
    apply_theme(qapp)
    screen = CompareScreen(FakeCache(), logic.DEFAULT_HOTKEYS)
    qtbot.addWidget(screen)
    control = screen.enhance_control
    assert control.text() == "Качество" and control.active_mode() is None and control.mode == "deblur"
    assert [row.text() for row in control.drum.rows] == ["OpenCV", "OpenCV NLM", "OpenCV Pro"]
    control.drum.chosen.emit(1)  # выбрали в списке «OpenCV NLM»
    assert control.active_mode() == "max" and control.isChecked()
    assert control.text() == "Качество: OpenCV NLM"
    assert all(view.enhance_mode == "max" for view in screen.views)
    control.drum.cleared.emit()  # «Выключить»
    assert control.active_mode() is None and control.text() == "Качество"
    assert all(view.enhance_mode is None for view in screen.views)


def test_quality_button_keeps_state_when_clicked_and_offers_off(qtbot, qapp):
    """Клик по включённой кнопке не сбрасывает её, а барабан предлагает «Выключить»."""
    from atlas.features.compare import logic
    from atlas.features.compare.screen import CompareScreen
    apply_theme(qapp)
    screen = CompareScreen(FakeCache(), logic.DEFAULT_HOTKEYS)
    qtbot.addWidget(screen)
    screen.show()
    control = screen.enhance_control
    control.drum.chosen.emit(0)
    assert control.active_mode() == "deblur"
    control.click()  # открывает барабан; кнопка остаётся включённой
    assert control.isChecked() and control.active_mode() == "deblur"
    assert control.drum.isVisible() and not control.drum.off_row.isHidden()
    control.drum.hide()
    control.click()
    assert control.isChecked() and control.active_mode() == "deblur"
    control.drum.cleared.emit()
    assert not control.isChecked() and control.active_mode() is None
    control.click()  # выключено: барабан без «Выключить»
    assert control.drum.off_row.isHidden()
    control.drum.hide()


def test_big_window_is_enhanced_too(qtbot, qapp, monkeypatch):
    """Окно больше MAX_PIXELS (Retina, полный экран) раньше молча оставалось без улучшения: теперь считается помельче."""
    monkeypatch.setattr(enhance, "MAX_PIXELS", 60_000)
    apply_theme(qapp)
    cache = FakeCache()
    view = PhotoView(cache, settle_ms=10)
    view.resize(600, 500)  # видимая часть заметно больше лимита
    qtbot.addWidget(view)
    view.show()
    view.set_enhance("deblur")
    cache.memory[("a.jpg", L1)] = type("H", (), {"image": soft_board(1000, 750), "level": L1})()
    view.set_photo("a.jpg")
    qtbot.waitUntil(lambda: view._enh_image is not None, timeout=5000)
    assert view._enh_image.width() * view._enh_image.height() <= 60_000 * 1.01


def test_pro_is_clean_and_sharper_than_plain(qapp):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    sharp, soft = blurred_text()
    rng = np.random.default_rng(1)
    noisy = np.clip(soft.astype(np.float32) + rng.normal(0, 3, soft.shape), 0, 255).astype(np.uint8)
    image = QImage(noisy.data, 300, 120, noisy.strides[0], QImage.Format_RGB888).rgbSwapped().copy()
    out = enhance.enhanced_crop(image, QRectF(0, 0, 300, 120), 900, 360, "pro")
    ptr = out.constBits()
    ptr.setsize(out.byteCount())
    got = np.frombuffer(ptr, np.uint8).reshape(360, out.bytesPerLine())[:, : 900 * 4].reshape(360, 900, 4)[:, :, :3]
    gray = lambda a: cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)
    plain = cv2.resize(gray(noisy), (900, 360), interpolation=cv2.INTER_CUBIC)
    assert enhance._edge_energy(gray(got)) > enhance._edge_energy(plain) * 1.5
    assert gray(got)[250:350, 10:150].std() < plain[250:350, 10:150].std() * 1.1  # шум на фоне заметно не вырос


def test_pro_is_available_everywhere_and_grey_without_engine(qtbot, qapp, monkeypatch):
    """«Pro» работает и на Windows (только opencv и numpy); без них все строки серые и выбрать нечего."""
    modes = enhance.load_modes(None)
    from atlas.shared.widgets.enhance_control import EnhanceControl
    control = EnhanceControl(modes, "pro")
    qtbot.addWidget(control)
    assert control.mode == "pro" and all(row.isEnabled() for row in control.drum.rows)
    assert enhance.usable_mode("pro") == "pro" and enhance.usable_mode("light") is None  # режима на Qt больше нет
    monkeypatch.setattr(enhance, "cv2", None)
    assert enhance.usable_mode("pro") is None and not enhance.engine_available()
    assert enhance.enhanced_crop(board(), QRectF(0, 0, 100, 100), 200, 200, "pro") is None
    grey = EnhanceControl(modes, "pro")
    qtbot.addWidget(grey)
    assert not any(row.isEnabled() for row in grey.drum.rows) and grey.mode is None
    grey.drum.show()
    qtbot.keyClick(grey.drum, Qt.Key_Down)  # серые строки стрелки пропускают
    assert grey.drum.current == 0


def _view_with_enhanced(qtbot, qapp, mode="deblur"):
    apply_theme(qapp)
    cache = FakeCache()
    view = PhotoView(cache, settle_ms=10)
    view.resize(600, 500)
    qtbot.addWidget(view)
    view.show()
    cache.memory[("a.jpg", L1)] = type("H", (), {"image": soft_board(1000, 750), "level": L1})()
    view.set_photo("a.jpg")
    qtbot.wait(50)
    return view


def test_hold_original_and_curtain(qtbot, qapp):
    view = _view_with_enhanced(qtbot, qapp)
    plain = view.grab().toImage()
    view.set_enhance("deblur")
    qtbot.waitUntil(lambda: view.enhanced_shown, timeout=3000)
    enhanced = view.grab().toImage()
    assert enhanced != plain  # улучшение видно
    view.set_show_original(True)  # держат клавишу «до»
    assert view.grab().toImage() == plain
    view.set_show_original(False)
    assert view.grab().toImage() == enhanced
    view.set_curtain(True)  # шторка по центру: слева исходное, справа улучшенное
    curtain = view.grab().toImage()
    half = view.width() // 2
    assert curtain.copy(5, 5, half - 40, view.height() - 10) == plain.copy(5, 5, half - 40, view.height() - 10)
    assert curtain.copy(half + 40, 5, half - 50, view.height() - 10) == enhanced.copy(half + 40, 5, half - 50, view.height() - 10)


def test_curtain_is_dragged_by_mouse_not_pan(qtbot, qapp):
    view = _view_with_enhanced(qtbot, qapp)
    view.set_enhance("deblur")
    qtbot.waitUntil(lambda: view.enhanced_shown, timeout=3000)
    view.set_curtain(True)
    state = view.state()
    line = int(view._curtain_x())
    qtbot.mousePress(view, Qt.LeftButton, pos=QPoint(line + 3, 100))  # рядом с границей — тянем её
    move = QMouseEvent(QEvent.MouseMove, QPointF(450, 100), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)  # кнопка зажата
    QApplication.sendEvent(view, move)
    qtbot.mouseRelease(view, Qt.LeftButton, pos=QPoint(450, 100))
    assert abs(view.curtain_pos - 450 / 600) < 0.03
    assert view.state() == state  # фото не сдвинулось
    view.set_curtain_pos(0.001)
    assert view.curtain_pos >= 0.02  # у самого края не прячем


def test_compare_curtain_button_and_key(qtbot, qapp):
    from atlas.features.compare import logic
    from atlas.features.compare.screen import CompareScreen
    apply_theme(qapp)
    screen = CompareScreen(FakeCache(), logic.DEFAULT_HOTKEYS)
    qtbot.addWidget(screen)
    assert not screen.curtain_button.isEnabled()  # без включённого «Качества» шторки нет
    screen.set_enhance("deblur")
    assert screen.curtain_button.isEnabled()
    screen.curtain_button.click()
    assert all(view.curtain for view in screen.views)
    qtbot.keyPress(screen, Qt.Key_Q)
    assert all(view._show_original for view in screen.views)
    qtbot.keyRelease(screen, Qt.Key_Q)
    assert not any(view._show_original for view in screen.views)
    screen.set_enhance(None)  # выключили «Качество» — шторка тоже уходит
    assert not any(view.curtain for view in screen.views) and not screen.curtain_button.isEnabled()
