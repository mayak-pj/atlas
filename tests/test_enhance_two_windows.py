"""«Качество» в двух окнах (шаг 12.9, замечание 15.11: «эталон + фото из папки, после подгонки работает только на одно»).

Причина: размытие оценивается по видимой части каждого окна. Резкая часть только растягивалась, и окно выглядело
так, будто «Качество» выключено. Теперь «Pro» при приближении снимает мягкость растягивания и у резкого фото,
а окно, где улучшать нечего, говорит об этом подписью.
"""
from pathlib import Path

import pytest
from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QImage
from PyQt5.QtTest import QTest

from atlas.shared.viewer import enhance
from atlas.shared.viewer.levels import L1
from atlas.shared.viewer.photo_view import TEXT_SHARP
from tests.test_compare_flow import App, _photos
from tests.test_enhance import blurred_text
from tests.test_enhance_worker import SlowEnhance, _views, photo


def _edges(image):
    cv2 = pytest.importorskip("cv2")
    from atlas.shared.viewer.enhance import _edge_energy, _to_bgr
    return _edge_energy(cv2.cvtColor(_to_bgr(image), cv2.COLOR_BGR2GRAY).astype("float32"))


def test_sharp_part_is_reported_and_pro_still_sharpens_when_magnified(qapp):
    pytest.importorskip("cv2")
    text, _ = blurred_text()
    sharp = QImage(text.data, 300, 120, text.strides[0], QImage.Format_RGB888).rgbSwapped().copy()
    whole = QRectF(0, 0, 300, 120)
    info = {}
    enhance.enhanced_crop(sharp, whole, 300, 120, "deblur", info=info)
    assert info["sigma"] is None  # резкое фото: «OpenCV» его не трогает и честно говорит об этом
    enhance.enhanced_crop(sharp, whole, 300, 120, "pro", info=info)
    assert info["sigma"] is None  # без приближения у «Pro» тоже нечего снимать
    part = QRectF(50, 20, 100, 75)
    out = enhance.enhanced_crop(sharp, part, 400, 300, "pro", info=info)  # приближение 4×
    assert info["sigma"] == pytest.approx(2.0)  # мягкость самого растягивания: 0,5 пикселя фото на сетке экрана
    plain = sharp.copy(part.toRect()).scaled(800, 600, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    assert _edges(out) > _edges(plain) * 1.2  # окно с резким фото при зуме тоже заметно меняется


@pytest.fixture
def slow(monkeypatch):
    monkeypatch.setattr(enhance, "usable_mode", lambda mode: mode)
    fake = SlowEnhance(steps=2)
    monkeypatch.setattr(enhance, "enhanced_crop", fake)
    return fake


def test_window_with_sharp_photo_says_there_is_nothing_to_improve(qtbot, qapp, slow):
    from tests.test_photo_view import FakeCache
    from atlas.shared.viewer.enhance_worker import EnhanceWorker

    cache, worker = FakeCache(), EnhanceWorker()
    soft, crisp = photo(80), photo(160)
    slow.sigma = lambda image: None if image.cacheKey() == crisp.cacheKey() else 1.5
    cache.memory[("эталон.jpg", L1)] = type("H", (), {"image": crisp, "level": L1})()
    cache.memory[("фото.jpg", L1)] = type("H", (), {"image": soft, "level": L1})()
    reference, current = _views(qtbot, qapp, 2, worker, cache, delay_ms=10)
    reference.set_photo("эталон.jpg")
    current.set_photo("фото.jpg")
    qtbot.waitUntil(lambda: reference.enhanced_shown and current.enhanced_shown, timeout=3000)
    assert reference.enhance_unchanged and not current.enhance_unchanged
    assert reference._note.isVisible() and reference._note.text() == TEXT_SHARP
    assert not current._note.isVisible()
    reference.set_show_original(True)  # «до» (клавиша Q): подпись не мешает смотреть исходное
    assert not reference._note.isVisible()
    reference.set_show_original(False)
    assert reference._note.isVisible()
    reference.set_enhance(None)
    assert not reference._note.isVisible()
    worker.close()


def test_reference_from_other_folder_keeps_quality_in_both_windows_after_adjusting(tmp_path, qtbot, monkeypatch, slow):
    """Сценарий замечания: эталон из другой папки (другой размер), «Синхронно» выкл, подгонка, вкл, «В кадр»."""
    app = App(tmp_path, qtbot, size=(1200, 1800))
    try:
        app.wait_open()
        screen = app.screen
        from atlas.features.compare.logic import PhotoItem

        other = tmp_path / "эталон"
        _photos(other, 2, (3000, 2000))
        screen.set_reference_folder([PhotoItem(100 + n, str(other / "фото {:03d}.jpg".format(n + 1))) for n in range(2)])
        app.wait_shown()
        screen.set_enhance("pro")

        def both_ready(step):
            try:
                qtbot.waitUntil(lambda: all(view.enhanced_shown for view in screen._visible_views()), timeout=3000)
            except AssertionError:
                raise AssertionError("после «{}» «Качество» не в обоих окнах".format(step))

        both_ready("включили")
        reference, current = screen._visible_views()
        reference.zoom_by(3.0)
        both_ready("зум")
        screen.sync_button.click()
        current.zoom_by(1.5)
        both_ready("подгонка без «Синхронно»")
        QTest.mouseClick(current, Qt.LeftButton)
        app.press(Qt.Key_Right)
        app.wait_shown()
        both_ready("листание")
        screen.sync_button.click()
        reference.zoom_by(1.3)
        both_ready("«Синхронно» снова")
        screen.fit()
        both_ready("«В кадр»")
        assert Path(current.path).name == "фото 002.jpg"
    finally:
        app.stop()
