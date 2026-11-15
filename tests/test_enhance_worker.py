"""«Качество» при листании (шаг 12.8): один расчёт на все окна, новый запрос заменяет ждущий, идущий прерывается."""
import threading
import time

import pytest
from PyQt5.QtCore import QRectF
from PyQt5.QtGui import QColor, QImage

from atlas.core.theme import apply_theme
from atlas.shared.viewer import enhance
from atlas.shared.viewer.enhance_worker import Cancelled, EnhanceWorker
from atlas.shared.viewer.levels import L1
from atlas.shared.viewer.photo_view import PhotoView
from tests.test_photo_view import FakeCache


class SlowEnhance:
    """Подмена enhanced_crop: «считает» steps шагов по step_s и проверяет отмену между ними, как деконволюция."""

    def __init__(self, steps=10, step_s=0.01):
        self.steps, self.step_s = steps, step_s
        self.lock = threading.Lock()
        self.running = self.max_running = 0
        self.started, self.cancelled, self.finished = [], [], []

    def __call__(self, image, source, width, height, mode="deblur", cancelled=None):
        with self.lock:
            self.running += 1
            self.max_running = max(self.max_running, self.running)
            self.started.append(image.cacheKey())
        try:
            for _ in range(self.steps):
                if cancelled is not None and cancelled():
                    with self.lock:
                        self.cancelled.append(image.cacheKey())
                    raise Cancelled()
                time.sleep(self.step_s)
            out = QImage(int(width), int(height), QImage.Format_RGB32)
            out.fill(QColor(200, 30, 30))
            with self.lock:
                self.finished.append(image.cacheKey())
            return out
        finally:
            with self.lock:
                self.running -= 1


def photo(shade):
    image = QImage(1000, 750, QImage.Format_RGB32)
    image.fill(QColor(shade, shade, shade))
    return image


def _views(qtbot, qapp, count, worker, cache, delay_ms=300):
    apply_theme(qapp)
    views = []
    for _ in range(count):
        view = PhotoView(cache, settle_ms=10, enhance_delay_ms=delay_ms, enhance_worker=worker)
        view.resize(600, 500)
        qtbot.addWidget(view)
        view.show()
        view.set_enhance("pro")
        views.append(view)
    return views


@pytest.fixture
def slow(monkeypatch):
    monkeypatch.setattr(enhance, "usable_mode", lambda mode: mode)  # без opencv тоже: считает подмена
    fake = SlowEnhance()
    monkeypatch.setattr(enhance, "enhanced_crop", fake)
    return fake


def test_twenty_fast_flips_run_one_calculation_and_last_photo_is_ready(qtbot, qapp, slow):
    cache, worker = FakeCache(), EnhanceWorker()
    images = {}
    for index in range(20):
        images[index] = photo(60 + index * 5)
        cache.memory[("p%d.jpg" % index, L1)] = type("H", (), {"image": images[index], "level": L1})()
    views = _views(qtbot, qapp, 2, worker, cache)  # два окна, как «Сравнение» с эталоном
    for index in range(20):
        for view in views:
            view.set_photo("p%d.jpg" % index)
        qtbot.wait(40)  # листание быстрее ENHANCE_DELAY_MS
    assert slow.started == []  # пока листают, «Качество» не начинало считать
    qtbot.waitUntil(lambda: all(view.enhanced_shown for view in views), timeout=5000)
    assert slow.max_running == 1  # одновременно — только один расчёт на все окна
    last = images[19].cacheKey()
    assert slow.started == [last, last]  # по одному расчёту на окно, и только для последнего фото
    assert all(view.path == "p19.jpg" for view in views)
    worker.close()


def test_running_calculation_is_interrupted_when_photo_changes(qtbot, qapp, slow):
    slow.steps = 200  # 2 с, если не прервать
    cache, worker = FakeCache(), EnhanceWorker()
    first, second = photo(80), photo(120)
    cache.memory[("a.jpg", L1)] = type("H", (), {"image": first, "level": L1})()
    cache.memory[("b.jpg", L1)] = type("H", (), {"image": second, "level": L1})()
    view, = _views(qtbot, qapp, 1, worker, cache, delay_ms=10)
    view.set_photo("a.jpg")
    qtbot.waitUntil(lambda: bool(slow.started), timeout=2000)
    slow.steps = 3
    view.set_photo("b.jpg")
    qtbot.waitUntil(lambda: view.enhanced_shown, timeout=2000)
    assert slow.cancelled == [first.cacheKey()]  # прежний расчёт прерван между шагами, а не досчитан
    assert slow.finished == [second.cacheKey()]
    assert slow.max_running == 1
    worker.close()


def test_new_request_replaces_waiting_one_and_cancelled_result_is_dropped():
    worker = EnhanceWorker()
    gate, results = threading.Event(), []
    owner_a, owner_b = object(), object()

    def blocking(cancelled):
        gate.wait(2)
        return "a1"

    worker.submit(owner_a, "a1", blocking, lambda key, result: results.append((key, result)))
    time.sleep(0.05)  # a1 считается
    for key in ("b1", "b2", "b3"):  # пока поток занят, у окна b ждёт только последнее
        worker.submit(owner_b, key, lambda cancelled, key=key: key, lambda key, result: results.append((key, result)))
    worker.cancel(owner_a)  # окну a результат не нужен
    gate.set()
    assert worker.wait_idle(2)
    assert results == [("b3", "b3")]
    worker.close()


def test_enhanced_crop_stops_between_steps(qapp):
    pytest.importorskip("cv2")
    from tests.test_enhance import soft_board
    image = soft_board(400, 300)
    calls = []

    def cancelled():
        calls.append(1)
        return len(calls) > 2

    for mode in ("deblur", "max", "pro"):
        calls.clear()
        with pytest.raises(Cancelled):
            enhance.enhanced_crop(image, QRectF(0, 0, 400, 300), 800, 600, mode, cancelled=cancelled)
        assert len(calls) == 3
