"""Замер скорости просмотра без человека: atlas.exe --viewbench [ПАПКА] --report ОТЧЁТЫ [--photos 500] [--flips 20] [--workers N].

ПАПКА с фото только читается, лучше всего настоящая папка на сетевом диске. Без неё создаются тестовые фото на локальном диске
и потом удаляются; такие цифры сетевого диска не показывают. Кэш — во временной папке, рабочий кэш и базу замер не трогает.
Код выхода: 0 — замер прошёл (цели — в отчёте), 1 — не удалось выполнить, 3 — некуда писать отчёт, 4 — зависание.
"""
from __future__ import annotations

import dataclasses
import gc
import logging
import os
import platform
import shutil
import statistics
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

from atlas.core.config import AppPaths, Config, ConfigError
from atlas.core.logging_setup import configure, install_excepthook
from atlas.core.process_memory import peak_mb
from atlas.core.qt_runtime import prepare
from atlas.core.report import TextReport

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NO_REPORT = 3
EXIT_HUNG = 4
HANG_TIMEOUT_S = 3600

GOAL_SHARP_MS = 300  # план: чёткость не позже 300 мс после остановки
GOAL_PREVIEW_MS = 50  # «без задержки» при листании с прогретым кэшем
HOLD_INTERVAL_S = 0.033  # автоповтор клавиши Windows — около 30 раз в секунду
HOLD_ZOOM = 6.0
NEIGHBORS = 2  # столько следующих фото запрашивается заранее, как будет на шаге 3.2
STEP_WINDOWS = (1, 2, 4)
STEP_ZOOMS = (1.0, 3.0, 12.0)
SHARP_LIMIT_S = 15.0
DISTINCT_TEST_PHOTOS = 8  # остальные — копии: разные пути, поэтому кэш считает их разными фото
PHOTO_SUFFIXES = (".jpg", ".jpeg")
_HEARTBEAT_MS = 5
WINDOW_SIZE = (1280, 720)

log = logging.getLogger("atlas.viewbench")


class BenchError(Exception):
    """Замер невозможен. Текст идёт в отчёт."""


def summarize(values):
    """(медиана, p95, максимум) или None для пустого списка."""
    if not values:
        return None
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    return statistics.median(ordered), p95, ordered[-1]


def _ms(values):
    summary = summarize(values)
    if summary is None:
        return "нет данных"
    return "медиана {:.0f}, p95 {:.0f}, макс. {:.0f} мс".format(*(item * 1000 for item in summary))


class _Pump:
    """Цикл событий с настоящей отрисовкой. Разрывы между тактами показывают, насколько GUI-поток был занят."""

    def __init__(self, app):
        from PyQt5.QtCore import Qt, QTimer

        self._app = app
        self._last = None
        self.gaps = []
        self._timer = QTimer()
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(_HEARTBEAT_MS)
        self._timer.timeout.connect(self._beat)
        self._timer.start()

    def _beat(self):
        now = time.perf_counter()
        if self._last is not None:
            self.gaps.append(now - self._last)
        self._last = now

    def run_until(self, condition, limit):
        """True — условие выполнилось до истечения limit секунд."""
        from PyQt5.QtCore import QEventLoop

        deadline = time.perf_counter() + limit
        while not condition():
            if time.perf_counter() >= deadline:
                return False
            self._app.processEvents(QEventLoop.AllEvents | QEventLoop.WaitForMoreEvents)
        return True

    def wait(self, seconds):
        deadline = time.perf_counter() + seconds
        self.run_until(lambda: time.perf_counter() >= deadline, seconds + 1)

    def stop(self):
        self._timer.stop()

    def take_gaps(self):
        gaps, self.gaps = self.gaps, []
        self._last = None
        return gaps


def _find_photos(folder, count):
    photos = sorted(path for path in folder.rglob("*") if path.suffix.lower() in PHOTO_SUFFIXES and path.is_file())
    if len(photos) < 2:
        raise BenchError("В папке {} меньше двух фото JPEG".format(folder))
    return photos[:count]


def _make_photos(folder, count):
    from atlas.shared.viewer.test_photo import save_noise_photo

    first = folder / "фото 0000.jpg"
    if not save_noise_photo(first):
        raise BenchError("Не удалось записать тестовое фото в {}".format(folder))
    needed = first.stat().st_size * 1.2 * count
    free = shutil.disk_usage(str(folder)).free
    if free < needed:
        raise BenchError("Мало места для тестовых фото: нужно {:.1f} ГБ, свободно {:.1f} ГБ. Укажите папку с настоящими фото или уменьшите --photos".format(
            needed / 1024 ** 3, free / 1024 ** 3))
    photos = [first]
    for number in range(1, count):
        path = folder / "фото {:04d}.jpg".format(number)
        if number < DISTINCT_TEST_PHOTOS:
            save_noise_photo(path)
        else:
            shutil.copyfile(str(photos[number % DISTINCT_TEST_PHOTOS]), str(path))
        photos.append(path)
    return photos


class _Stage:
    """Окно с N просмотрщиками в ряд на своём ImageCache: память пуста, как после запуска программы."""

    def __init__(self, settings, windows, size):
        from PyQt5.QtWidgets import QHBoxLayout, QWidget

        from atlas.shared.viewer.image_cache import ImageCache
        from atlas.shared.viewer.photo_view import PhotoView
        from atlas.shared.viewer.sync_group import SyncGroup

        self.cache = ImageCache(settings)
        self.window = QWidget()
        self.window.setWindowTitle("Atlas — замер просмотра, ничего нажимать не нужно")
        self.window.resize(*size)
        layout = QHBoxLayout(self.window)
        self.group = SyncGroup(self.cache)
        self.views = []
        for _ in range(windows):
            view = PhotoView(self.cache)
            layout.addWidget(view)
            self.group.add(view)
            self.views.append(view)
        self.window.show()

    def close(self):
        """Память предыдущего сценария должна освободиться, иначе пик памяти в отчёте будет ложным."""
        self.window.close()
        self.cache.stop()
        self.window.deleteLater()
        for view in self.views:
            self.group.remove(view)
            view.clear()
        self.views = []
        self.cache = self.group = self.window = None


def _release(pump):
    pump.wait(0.05)  # deleteLater выполняется в цикле событий
    gc.collect()


def _hold(pump, settings, size, photos, report, title):
    """Удержание стрелки: новое фото каждые 33 мс, зум 6×."""
    from atlas.shared.viewer.levels import L1, NEIGHBOR

    stage = _Stage(settings, 1, size)
    view = stage.views[0]
    stage.group.set_state(HOLD_ZOOM, 0.5, 0.5)
    flipped, delays = {}, []

    def on_shown(path):
        delays.append(time.perf_counter() - flipped[path])

    view.photo_shown.connect(on_shown)
    pump.take_gaps()
    started = time.perf_counter()
    for number, photo in enumerate(photos):
        flipped[str(photo)] = time.perf_counter()
        stage.group.show_photo(view, photo)
        for ahead in photos[number + 1:number + 1 + NEIGHBORS]:
            stage.cache.get(ahead, L1, NEIGHBOR)
        pump.wait(max(0.0, started + (number + 1) * HOLD_INTERVAL_S - time.perf_counter()))
    pump.run_until(lambda: view.is_current_shown, SHARP_LIMIT_S)
    gaps = pump.take_gaps()
    report.line("{}, {} фото:".format(title, len(photos)))
    report.line("  успели показаться {} из {} ({:.0f}%), остальные пролистаны раньше, чем прочитались".format(
        len(delays), len(photos), 100.0 * len(delays) / len(photos)))
    report.line("  от нажатия до картинки: {}".format(_ms(delays)))
    report.line("  занятость GUI-потока (разрыв между тактами): {}".format(_ms(gaps)))
    view = None
    stage.close()
    _release(pump)
    return delays, gaps, len(delays) / float(len(photos))


def _warm(pump, settings, photos, report):
    from atlas.shared.viewer.image_cache import ImageCache

    cache = ImageCache(settings)
    started = time.perf_counter()
    cache.prefetch(photos)
    finished = pump.run_until(lambda: cache.wait_idle(0.0), HANG_TIMEOUT_S / 2)
    elapsed = time.perf_counter() - started
    cache.stop()
    cache = None
    _release(pump)
    if not finished:
        raise BenchError("Прогрев не завершился")
    report.line("Прогрев L0 и L1 на локальный диск, {} фото: {:.1f} с, {:.0f} мс на фото, {:.0f} фото в минуту".format(
        len(photos), elapsed, elapsed / len(photos) * 1000, len(photos) / elapsed * 60))
    return elapsed


def _step(pump, settings, size, photos, windows, zoom, flips, report):
    """Шаг и остановка: все окна получают новые фото, ждём первую картинку и чёткий уровень. Режим «Ракурсы» — самый тяжёлый случай."""
    stage = _Stage(settings, windows, size)
    stage.group.set_state(zoom, 0.5, 0.5)
    first, sharp, missed = [], [], 0
    position = 0
    pump.wait(0.05)
    for _ in range(flips):
        started = time.perf_counter()
        for view in stage.views:
            stage.group.show_photo(view, photos[position % len(photos)])
            position += 1
        pump.run_until(lambda: all(view.is_current_shown for view in stage.views), SHARP_LIMIT_S)
        first.append(time.perf_counter() - started)
        if pump.run_until(lambda: all(view.is_sharp for view in stage.views), SHARP_LIMIT_S):
            sharp.append(time.perf_counter() - started)
        else:
            missed += 1
    levels = ",".join("L{}".format(view.shown_level) for view in stage.views if view.shown_level is not None)
    report.line("{} окна, зум {:.0f}× ({}): первая картинка {}; чётко {}{}".format(
        windows, zoom, levels, _ms(first), _ms(sharp), "; не дождались: {}".format(missed) if missed else ""))
    stage.close()
    _release(pump)
    return sharp, missed


def _load_settings(paths, disk_dir, workers):
    from atlas.shared.viewer.image_cache import CacheSettings

    try:
        settings = CacheSettings.from_config(Config.load(paths), paths)
    except ConfigError:
        log.warning("Настройки не прочитаны, замер идёт со значениями по умолчанию")
        settings = CacheSettings(disk_dir=disk_dir)
    settings = dataclasses.replace(settings, disk_dir=disk_dir)
    return dataclasses.replace(settings, workers=workers) if workers else settings


def _bench(report, out, folder, count, flips, workers, paths, work):
    from PyQt5.QtCore import qVersion
    from PyQt5.QtWidgets import QApplication

    prepare()
    app = QApplication.instance() or QApplication(["atlas"])
    from atlas.core.theme import apply_theme
    from atlas.shared.viewer.photo_view import SETTLE_MS

    apply_theme(app)
    available = app.primaryScreen().availableSize()
    size = (min(WINDOW_SIZE[0], available.width()), min(WINDOW_SIZE[1], available.height()))
    # Отдельная папка кэша у сценария без прогрева: иначе он заполнил бы кэш, и прогрев ничего бы не показал
    settings = _load_settings(paths, work / "кэш", workers)
    cold_settings = dataclasses.replace(settings, disk_dir=work / "кэш без прогрева")

    report.line("ОС: {}. Python {}. Qt {}".format(platform.platform(), platform.python_version(), qVersion()))
    report.line("Экран {}×{}, окно замера {}×{}".format(available.width(), available.height(), *size))
    report.line("Потоков чтения: {}, память {} МБ, пауза до чёткого уровня {} мс".format(settings.workers, settings.memory_limit_mb, SETTLE_MS))
    if folder is not None:
        photos = _find_photos(folder, count)
        report.line("Фото из папки: {}".format(folder))
    else:
        photo_dir = work / "Фото замер"
        photo_dir.mkdir()
        report.line("Тестовые фото на локальном диске: системный кэш уже держит их в памяти, это лучший случай, а не сетевой диск")
        photos = _make_photos(photo_dir, count)
    sizes = [path.stat().st_size for path in photos[:20]]
    report.line("Фото: {}, средний файл {:.1f} МБ".format(len(photos), sum(sizes) / len(sizes) / 1024 / 1024))
    report.line()

    pump = _Pump(app)
    _hold(pump, cold_settings, size, photos, report, "Удержание стрелки, кэш пуст, чтение идёт на 2 фото вперёд")
    report.line()
    _warm(pump, settings, photos, report)
    report.line()
    warm_delays, warm_gaps, warm_share = _hold(pump, settings, size, photos, report, "Удержание стрелки, после прогрева")
    report.line()
    report.line("Шаг и остановка, после прогрева, чётко — с учётом паузы:")
    results = {}
    for windows in STEP_WINDOWS:
        for zoom in STEP_ZOOMS:
            results[(windows, zoom)] = _step(pump, settings, size, photos, windows, zoom, flips, report)
    pump.stop()
    report.line()
    peak = peak_mb()
    report.line("Пик памяти процесса: {}".format("неизвестно" if peak is None else "{:.0f} МБ".format(peak)))
    report.line()
    _verdict(report, warm_delays, warm_share, results)


def _verdict(report, delays, share, results):
    preview = summarize(delays)
    preview_ok = preview is not None and preview[0] * 1000 <= GOAL_PREVIEW_MS
    report.line("ЦЕЛЬ: листание с прогретым кэшем — картинка не дольше {} мс: {} (медиана {}, показано {:.0f}%)".format(
        GOAL_PREVIEW_MS, "ДА" if preview_ok else "НЕТ", "нет данных" if preview is None else "{:.0f} мс".format(preview[0] * 1000), share * 100))
    for (windows, zoom), (sharp, missed) in sorted(results.items()):
        summary = summarize(sharp)
        good = summary is not None and not missed and summary[1] * 1000 <= GOAL_SHARP_MS
        report.line("ЦЕЛЬ: чётко за {} мс, {} окна, зум {:.0f}×: {} (p95 {})".format(
            GOAL_SHARP_MS, windows, zoom, "ДА" if good else "НЕТ", "нет данных" if summary is None else "{:.0f} мс".format(summary[1] * 1000)))


def run(folder, out, count=500, flips=20, workers=None, paths=None, label=None):
    """Возвращает код выхода (см. начало файла)."""
    out = Path(out)
    try:
        out.mkdir(parents=True, exist_ok=True)
        report = TextReport(out / "viewbench_{}.txt".format(label or os.environ.get("COMPUTERNAME") or platform.node() or "pc"))
    except OSError:
        return EXIT_NO_REPORT
    configure(out / "logs")
    install_excepthook()

    def on_hang():
        report.line("ИТОГ: ЗАВИСАНИЕ — нет завершения за {} с".format(HANG_TIMEOUT_S))
        os._exit(EXIT_HUNG)

    watchdog = threading.Timer(HANG_TIMEOUT_S, on_hang)
    watchdog.daemon = True
    watchdog.start()
    work = None
    code = EXIT_OK
    try:
        work = Path(tempfile.mkdtemp(prefix="atlas_viewbench_"))
        _bench(report, out, None if folder is None else Path(folder), count, flips, workers, paths or AppPaths.discover(), work)
    except BenchError as exc:
        report.line("ОШИБКА: {}".format(exc))
        code = EXIT_FAILED
    except Exception:
        log.exception("Замер прерван")
        report.line("ОШИБКА: {}".format(traceback.format_exc()))
        code = EXIT_FAILED
    finally:
        watchdog.cancel()
        if work is not None:
            shutil.rmtree(str(work), ignore_errors=True)
    report.line("ИТОГ: {}".format("ЗАМЕР ЗАВЕРШЁН" if code == EXIT_OK else "ЗАМЕР НЕ ВЫПОЛНЕН"))
    return code
