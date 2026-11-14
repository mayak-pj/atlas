"""Улучшение фото при приближении (шаг 12.5): резкость в рабочем потоке, файл и кэш не меняются."""
import pytest
from PyQt5.QtCore import QRectF
from PyQt5.QtGui import QColor, QImage, QPainter

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


def gray(image, x, y):
    return image.pixel(x, y) & 255


def test_wants_enhance_only_when_magnified():
    assert not enhance.wants_enhance(0.3, "deblur")
    assert enhance.wants_enhance(0.8, "deblur")
    assert enhance.wants_enhance(2.0, "deblur")
    assert not enhance.wants_enhance(4.0, None)


def test_edge_gets_overshoot_and_thin_line_gets_brighter(qapp):
    source = board()
    result = enhance.enhanced_crop(source, QRectF(100, 60, 300, 150), 1800, 900, "light")
    assert (result.width(), result.height()) == (1800, 900)
    # у края светлого предмета (x = 300 на экране): тёмный выброс по тёмной стороне и светлый — по светлой
    row = [gray(result, x, 400) for x in range(280, 340)]
    assert min(row) < 85 and max(row) > 165
    # дорожка 130 на фоне 90 стала ярче, чем в простом растяжении
    plain = source.copy(300, 100, 2, 80).scaled(12, 480).pixel(0, 100) & 255
    assert max(gray(result, x, 400) for x in range(1190, 1230)) > plain + 10
    assert gray(result, 20, 20) in range(85, 95)  # ровный фон не изменился


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
    assert [m["id"] for m in modes] == ["light", "deblur", "max"] and all(m["weight"] for m in modes)
    assert enhance.load_modes(tmp_path / "нет.json") == enhance.load_modes(None)
    assert enhance.usable_mode("nonsense") is None


def test_does_not_change_source_and_refuses_huge(qapp):
    source = board()
    before = source.copy()
    assert enhance.enhanced_crop(source, QRectF(0, 0, 100, 100), 5000, 5000) is None
    assert enhance.enhanced_crop(source, QRectF(0, 0, 100, 100), 400, 400, None) is None
    enhance.enhanced_crop(source, QRectF(0, 0, 100, 100), 400, 400)
    assert source == before


def test_photo_view_enhances_at_high_zoom(qtbot, qapp):
    apply_theme(qapp)
    cache = FakeCache()
    view = PhotoView(cache, settle_ms=10)
    view.resize(600, 500)
    qtbot.addWidget(view)
    view.show()
    assert view.enhance_mode is None  # по умолчанию выключено: включает кнопка «Улучшить»
    view.set_enhance("deblur")
    cache.memory[("a.jpg", L1)] = type("H", (), {"image": board(100, 75), "level": L1})()
    view.set_photo("a.jpg")
    assert view._enh_image is None  # при «вписать» масштаб меньше порога
    view.zoom_by(12.0)
    qtbot.wait(50)
    cache.ready.emit("a.jpg", L3, board())
    qtbot.waitUntil(lambda: view.shown_level == L3)
    qtbot.waitUntil(lambda: view._enh_image is not None, timeout=3000)
    pixmap = view.grab().toImage()
    assert not pixmap.isNull()
    view.set_enhance(None)
    assert view._enh_image is None
    view.zoom_by(1.1)
    qtbot.wait(100)
    assert view._enh_image is None


def test_compare_screen_has_enhance_button(qtbot, qapp):
    from atlas.features.compare.screen import CompareScreen
    apply_theme(qapp)
    from atlas.features.compare import logic
    screen = CompareScreen(FakeCache(), logic.DEFAULT_HOTKEYS)
    qtbot.addWidget(screen)
    control = screen.enhance_control
    assert control.active_mode() is None and control.mode == "deblur"
    control.menu.actions()[2].trigger()  # выбрать «Максимум»
    assert control.active_mode() == "max"
    assert all(view.enhance_mode == "max" for view in screen.views)
    control.button.click()  # выключить
    assert control.active_mode() is None
    assert all(view.enhance_mode is None for view in screen.views)
