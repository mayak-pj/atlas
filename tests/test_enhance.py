"""Улучшение фото при приближении (шаг 12.5): резкость в рабочем потоке, файл и кэш не меняются."""
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
    assert not enhance.wants_enhance(0.5, 1.0)
    assert not enhance.wants_enhance(1.0, 1.0)
    assert enhance.wants_enhance(2.0, 1.0)
    assert not enhance.wants_enhance(4.0, 0)


def test_edge_gets_overshoot_and_thin_line_gets_brighter(qapp):
    source = board()
    result = enhance.enhanced_crop(source, QRectF(100, 60, 300, 150), 1800, 900, 2)
    assert (result.width(), result.height()) == (1800, 900)
    # у края светлого предмета (x = 300 на экране): тёмный выброс по тёмной стороне и светлый — по светлой
    row = [gray(result, x, 400) for x in range(280, 340)]
    assert min(row) < 85 and max(row) > 165
    # дорожка 130 на фоне 90 стала ярче, чем в простом растяжении
    plain = source.copy(300, 100, 2, 80).scaled(12, 480).pixel(0, 100) & 255
    assert max(gray(result, x, 400) for x in range(1190, 1230)) > plain + 10
    assert gray(result, 20, 20) in range(85, 95)  # ровный фон не изменился


def test_does_not_change_source_and_refuses_huge(qapp):
    source = board()
    before = source.copy()
    assert enhance.enhanced_crop(source, QRectF(0, 0, 100, 100), 5000, 5000) is None
    assert enhance.enhanced_crop(source, QRectF(0, 0, 100, 100), 400, 400, 0) is None
    enhance.enhanced_crop(source, QRectF(0, 0, 100, 100), 400, 400)
    assert source == before


def test_photo_view_enhances_at_high_zoom(qtbot, qapp):
    apply_theme(qapp)
    cache = FakeCache()
    view = PhotoView(cache, settle_ms=10)
    view.resize(600, 500)
    qtbot.addWidget(view)
    view.show()
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
    view.set_enhance(0)
    assert view._enh_image is None
    view.zoom_by(1.1)
    qtbot.wait(100)
    assert view._enh_image is None
