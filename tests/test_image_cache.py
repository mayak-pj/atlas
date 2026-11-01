"""ImageCache: уровни, EXIF, память, диск, очередь, отказы."""
import os
import struct
import threading

import pytest
from PyQt5.QtCore import QObject, QThread, pyqtSlot
from PyQt5.QtGui import QColor, QImage, QPainter

from atlas.core.config import AppPaths
from atlas.shared.viewer import decode
from atlas.shared.viewer.disk_cache import DiskCache, default_cache_dir
from atlas.shared.viewer.image_cache import CacheSettings, ImageCache
from atlas.shared.viewer.job_queue import JobQueue
from atlas.shared.viewer.levels import CURRENT, L0, L1, L2, L3, NEIGHBOR, WARMUP, scaled_size
from atlas.shared.viewer.memory_cache import MemoryCache


def make_jpeg(path, width=800, height=1200, color="#808080"):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor(color))
    assert image.save(str(path), "JPEG", 90)
    return path


def add_orientation(path, orientation):
    """Вставляет в JPEG блок EXIF с поворотом: Qt такой блок записать не умеет."""
    entry = struct.pack("<HHIHH", 0x0112, 3, 1, orientation, 0)
    tiff = b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 1) + entry + struct.pack("<I", 0)
    body = b"Exif\x00\x00" + tiff
    data = path.read_bytes()
    path.write_bytes(data[:2] + b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body + data[2:])


@pytest.fixture
def cache_factory(qapp, tmp_path):
    made = []

    def make(**values):
        values.setdefault("disk_dir", tmp_path / "кэш")
        cache = ImageCache(CacheSettings(**values))
        made.append(cache)
        return cache

    yield make
    for cache in made:
        cache.stop()


@pytest.fixture
def decode_calls(monkeypatch):
    """Считает чтения исходников."""
    calls = []
    original = decode.decode_file

    def counted(path, level):
        calls.append((str(path), level))
        return original(path, level)

    monkeypatch.setattr(decode, "decode_file", counted)
    return calls


def fetch(qtbot, cache, path, level, priority=CURRENT):
    with qtbot.waitSignal(cache.ready, timeout=10000) as blocker:
        assert cache.get(path, level, priority) is None
    return blocker.args[2]


# --- уровни и декодирование ---------------------------------------------------------------
def test_scaled_size_rounds_down_for_dct():
    assert scaled_size(3456, 5184, L1) == (864, 1296)
    assert scaled_size(3456, 5184, L2) == (1728, 2592)
    assert scaled_size(3456, 5184, L3) == (3456, 5184)
    assert scaled_size(3457, 5187, L1) == (864, 1296)
    assert scaled_size(3, 2, L1) == (1, 1)


@pytest.mark.parametrize("level,size", [(L1, (200, 300)), (L2, (400, 600)), (L3, (800, 1200))])
def test_decode_levels(qapp, tmp_path, level, size):
    image = decode.decode_file(make_jpeg(tmp_path / "a.jpg"), level)
    assert (image.width(), image.height()) == size


def test_exif_rotation_is_applied(qapp, tmp_path):
    """Файл 800×400: левая половина красная. Поворот на 90° по часовой: красное сверху, размер 100×200."""
    path = tmp_path / "rotated.jpg"
    image = QImage(800, 400, QImage.Format_RGB32)
    image.fill(QColor("#0000FF"))
    painter = QPainter(image)
    painter.fillRect(0, 0, 400, 400, QColor("#FF0000"))
    painter.end()
    assert image.save(str(path), "JPEG", 95)
    add_orientation(path, 6)

    for level, size in ((L1, (100, 200)), (L2, (200, 400)), (L3, (400, 800))):
        result = decode.decode_file(path, level)
        assert (result.width(), result.height()) == size
        top = result.pixelColor(result.width() // 2, result.height() // 8)
        bottom = result.pixelColor(result.width() // 2, result.height() * 7 // 8)
        assert top.red() > 200 and top.blue() < 80
        assert bottom.blue() > 200 and bottom.red() < 80


def test_wrong_extension_is_read_by_content(qapp, tmp_path):
    path = make_jpeg(tmp_path / "a.jpg")
    renamed = path.with_name("a.png")
    path.rename(renamed)
    assert not decode.decode_file(renamed, L1).isNull()


def test_garbage_raises(qapp, tmp_path):
    path = tmp_path / "bad.jpg"
    path.write_bytes(b"not a jpeg")
    with pytest.raises(decode.DecodeError):
        decode.decode_file(path, L1)


# --- память -------------------------------------------------------------------------------
def test_memory_evicts_least_recently_used():
    memory = MemoryCache(100)
    memory.put("a", L1, "A", 40)
    memory.put("b", L1, "B", 40)
    assert memory.best("a", L1).image == "A"  # теперь самое старое — b
    memory.put("c", L1, "C", 40)
    assert memory.best("b", L1) is None
    assert memory.best("a", L1) and memory.best("c", L1)
    assert memory.size_bytes == 80


def test_memory_level_cap():
    memory = MemoryCache(10000, {L3: 2})
    for name in "abc":
        memory.put(name, L3, name, 72)
    memory.put("a", L1, "small", 1)
    assert memory.best("a", L3).level == L1  # L3 вытеснен потолком, L1 остался
    assert memory.best("b", L3).level == L3 and memory.best("c", L3).level == L3


def test_memory_oversize_is_not_stored_and_replaces_old_value():
    memory = MemoryCache(100)
    memory.put("a", L1, "old", 50)
    memory.put("a", L1, "too big", 500)
    assert memory.best("a", L1) is None
    assert memory.size_bytes == 0


def test_memory_best_prefers_exact_then_higher_then_lower():
    memory = MemoryCache(1000)
    memory.put("a", L0, "l0", 1)
    memory.put("a", L1, "l1", 1)
    memory.put("a", L3, "l3", 1)
    assert memory.best("a", L1).image == "l1"
    assert memory.best("a", L2).image == "l3"
    memory.forget("a")
    memory.put("a", L0, "l0", 1)
    assert memory.best("a", L3).image == "l0"
    assert memory.best("other", L1) is None


# --- очередь ------------------------------------------------------------------------------
def test_queue_priorities_and_order():
    queue = JobQueue(workers=4)
    queue.put("w1", L1, WARMUP, False)
    queue.put("w2", L1, WARMUP, False)
    queue.put("n", L1, NEIGHBOR, True)
    queue.put("old", L1, CURRENT, True)
    queue.put("new", L1, CURRENT, True)
    got = [queue.take().path for _ in range(5)]
    assert got == ["new", "old", "n", "w1", "w2"]  # внутри приоритета: новые первыми, прогрев по порядку


def test_queue_warmup_never_takes_the_last_worker():
    queue = JobQueue(workers=2)
    queue.put("w1", L1, WARMUP, False)
    queue.put("w2", L1, WARMUP, False)
    first = queue.take()
    assert first.path == "w1"
    taken = []
    thread = threading.Thread(target=lambda: taken.append(queue.take()), daemon=True)
    thread.start()
    thread.join(0.2)
    assert not taken  # второй поток не занят прогревом: ждёт текущее
    queue.put("cur", L3, CURRENT, True)
    thread.join(5)
    assert taken[0].path == "cur"
    queue.done(first)
    queue.close()


def test_queue_merges_duplicates_and_raises_priority():
    queue = JobQueue(workers=4)
    queue.put("a", L1, WARMUP, False)
    queue.put("b", L1, NEIGHBOR, True)
    queue.put("a", L1, CURRENT, True)
    job = queue.take()
    assert (job.path, job.priority, job.to_memory) == ("a", CURRENT, True)
    assert queue.take().path == "b"
    queue.close()


def test_queue_running_warmup_does_not_swallow_a_memory_request():
    queue = JobQueue(workers=4)
    queue.put("a", L1, WARMUP, False)
    warm = queue.take()
    queue.put("a", L1, WARMUP, False)  # то же самое уже идёт
    queue.put("a", L1, CURRENT, True)  # а это — нет: прогрев не кладёт в память
    queue.done(warm)
    job = queue.take()
    assert job.to_memory
    queue.done(job)
    assert queue.wait_idle(0.1)


def test_queue_cancel_keeps_warmup():
    queue = JobQueue(workers=4)
    queue.put("a", L3, CURRENT, True)
    queue.put("b", L1, NEIGHBOR, True)
    queue.put("w", L1, WARMUP, False)
    queue.cancel_foreground()
    assert queue.take().path == "w"
    queue.close()
    assert queue.take() is None


# --- диск ---------------------------------------------------------------------------------
def test_disk_roundtrip_cyrillic_and_change_of_file(qapp, tmp_path):
    disk = DiskCache(tmp_path / "кэш с пробелом", 10 ** 9)
    image = QImage(50, 70, QImage.Format_RGB32)
    image.fill(QColor("#336699"))
    signature = ("R:\\Проект\\a.jpg", 100, 1)
    assert disk.load(signature, L1) is None
    disk.save(signature, L1, image)
    assert disk.has(signature, L1)
    assert disk.load(signature, L1).width() == 50
    assert not disk.has(("R:\\Проект\\a.jpg", 100, 2), L1)
    assert not disk.has(("R:\\Проект\\a.jpg", 101, 1), L1)
    assert not disk.has(signature, L0)
    assert not list((tmp_path / "кэш с пробелом").rglob("*.tmp"))


def test_disk_trim_removes_longest_unused(qapp, tmp_path):
    disk = DiskCache(tmp_path / "c", 10 ** 9)
    image = QImage(64, 64, QImage.Format_RGB32)
    image.fill(QColor("#336699"))
    signatures = [("p{}".format(i), 1, 1) for i in range(5)]
    for number, signature in enumerate(signatures):
        disk.save(signature, L1, image)
        os.utime(str(disk._file(signature, L1)), (1000 + number, 1000 + number))
    size = disk._file(signatures[0], L1).stat().st_size
    disk.limit_bytes = size * 3
    disk.trim()
    assert [disk.has(signature, L1) for signature in signatures] == [False, False, False, True, True]


def test_disk_unavailable_folder_disables_cache(qapp, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    disk = DiskCache(blocker / "cache", 10 ** 9)
    image = QImage(4, 4, QImage.Format_RGB32)
    assert not disk.enabled
    disk.save(("p", 1, 1), L1, image)
    assert disk.load(("p", 1, 1), L1) is None and not disk.has(("p", 1, 1), L1)


def test_default_folder_follows_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_cache_dir() == tmp_path / "Atlas" / "cache"


# --- ImageCache ---------------------------------------------------------------------------
def test_get_loads_then_serves_from_memory(qtbot, cache_factory, tmp_path, decode_calls):
    cache = cache_factory()
    path = make_jpeg(tmp_path / "Папка фото" / "плата 1.jpg")
    image = fetch(qtbot, cache, path, L2)
    assert image.width() == 400
    hit = cache.get(path, L2)
    assert hit.level == L2 and hit.image.width() == 400
    assert decode_calls == [(str(path), L2)]


def test_lower_level_is_returned_while_better_one_loads(qtbot, cache_factory, tmp_path):
    cache = cache_factory()
    path = make_jpeg(tmp_path / "a.jpg")
    fetch(qtbot, cache, path, L1)
    with qtbot.waitSignal(cache.ready, timeout=10000) as blocker:
        assert cache.get(path, L3).level == L1
    assert blocker.args[1] == L3
    assert cache.get(path, L2).level == L3  # лучшее уже есть — читать L2 незачем
    assert cache.wait_idle(5)


def test_l1_and_l0_come_from_one_read_and_survive_restart(qtbot, cache_factory, tmp_path, decode_calls):
    path = make_jpeg(tmp_path / "a.jpg")
    cache = cache_factory()
    thumb = fetch(qtbot, cache, path, L0)
    assert max(thumb.width(), thumb.height()) == 160
    assert len(decode_calls) == 1
    assert cache.get(path, L1).level == L0  # пока готовится лучшее, показываем что есть
    assert cache.wait_idle(5)
    assert cache.get(path, L1).image.width() == 200
    assert cache.get(path, L0).level == L0

    assert fetch(qtbot, cache_factory(), path, L1).width() == 200
    assert fetch(qtbot, cache_factory(), path, L0).height() == 160
    assert len(decode_calls) == 1


def test_changed_file_is_read_again(qtbot, cache_factory, tmp_path, decode_calls):
    path = make_jpeg(tmp_path / "a.jpg")
    fetch(qtbot, cache_factory(), path, L1)
    make_jpeg(path, 400, 600)
    os.utime(str(path), (2000000000, 2000000000))
    assert fetch(qtbot, cache_factory(), path, L1).width() == 100
    assert len(decode_calls) == 2


def test_forget_drops_replaced_file_from_memory(qtbot, cache_factory, tmp_path):
    path = make_jpeg(tmp_path / "a.jpg")
    cache = cache_factory()
    fetch(qtbot, cache, path, L3)
    make_jpeg(path, 400, 600)
    cache.forget(path)
    assert fetch(qtbot, cache, path, L3).width() == 400


def test_corrupt_cache_file_is_rebuilt(qtbot, cache_factory, tmp_path, decode_calls):
    path = make_jpeg(tmp_path / "a.jpg")
    fetch(qtbot, cache_factory(), path, L1)
    for item in (tmp_path / "кэш").rglob("*_L1.jpg"):
        item.write_bytes(b"broken")
    assert fetch(qtbot, cache_factory(), path, L1).width() == 200
    assert len(decode_calls) == 2


def test_prefetch_fills_disk_only(qtbot, cache_factory, tmp_path, decode_calls):
    paths = [make_jpeg(tmp_path / "{}.jpg".format(i)) for i in range(3)]
    cache = cache_factory()
    received = []
    cache.ready.connect(lambda *args: received.append(args))
    cache.prefetch(paths)
    assert cache.wait_idle(20)
    qtbot.wait(50)
    assert not received
    assert len(list((tmp_path / "кэш").rglob("*_L0.jpg"))) == 3
    assert len(list((tmp_path / "кэш").rglob("*_L1.jpg"))) == 3
    assert cache.get(paths[0], L1) is None  # в памяти пусто, запрос ушёл в очередь
    assert cache.wait_idle(20)
    cache.prefetch(paths)
    assert cache.wait_idle(20)
    assert len(decode_calls) == 3


def test_failed_file_reports_once_and_retries_later(qtbot, cache_factory, tmp_path):
    path = tmp_path / "bad.jpg"
    path.write_bytes(b"not a jpeg")
    cache = cache_factory(retry_after_s=0.3)
    errors = []
    cache.failed.connect(lambda *args: errors.append(args))
    with qtbot.waitSignal(cache.failed, timeout=5000):
        assert cache.get(path, L3) is None
    assert cache.get(path, L3) is None  # перерисовка окна не запускает чтение заново
    assert cache.wait_idle(5)
    qtbot.wait(20)
    assert len(errors) == 1
    qtbot.wait(350)
    make_jpeg(path)
    assert fetch(qtbot, cache, path, L3).width() == 800


def test_missing_file_reports_failure(qtbot, cache_factory, tmp_path):
    cache = cache_factory()
    with qtbot.waitSignal(cache.failed, timeout=5000) as blocker:
        cache.get(tmp_path / "нет.jpg", L1)
    assert blocker.args[1] == L1


def test_works_without_disk_folder(qtbot, cache_factory, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    path = make_jpeg(tmp_path / "a.jpg")
    cache = cache_factory(disk_dir=blocker / "cache")
    assert fetch(qtbot, cache, path, L1).width() == 200
    cache.prefetch([make_jpeg(tmp_path / "b.jpg")])
    assert cache.wait_idle(5)


def test_get_does_no_file_io_in_gui_thread(qtbot, cache_factory, tmp_path, monkeypatch):
    """Файл на сетевом диске: обращение к нему из GUI-потока заморозило бы окно."""
    gui = threading.current_thread()
    seen = []
    original_signature = decode.file_signature
    original_decode = decode.decode_file

    def signature(path):
        seen.append(threading.current_thread())
        return original_signature(path)

    def decoded(path, level):
        seen.append(threading.current_thread())
        return original_decode(path, level)

    monkeypatch.setattr(decode, "file_signature", signature)
    monkeypatch.setattr(decode, "decode_file", decoded)
    path = make_jpeg(tmp_path / "a.jpg")
    fetch(qtbot, cache_factory(), path, L1)
    assert seen and gui not in seen


def test_ready_arrives_in_the_receiver_thread(qtbot, cache_factory, tmp_path):
    class Receiver(QObject):
        thread_seen = None

        @pyqtSlot(str, int, QImage)
        def on_ready(self, path, level, image):
            Receiver.thread_seen = QThread.currentThread()

    receiver = Receiver()
    cache = cache_factory()
    cache.ready.connect(receiver.on_ready)
    fetch(qtbot, cache, make_jpeg(tmp_path / "a.jpg"), L1)
    assert Receiver.thread_seen is receiver.thread()


def test_stop_ends_threads_and_later_calls_are_harmless(qtbot, cache_factory, tmp_path):
    path = make_jpeg(tmp_path / "a.jpg")
    cache = cache_factory()
    fetch(qtbot, cache, path, L1)
    threads = list(cache._threads)
    cache.stop()
    assert threads and not any(thread.is_alive() for thread in threads)
    assert cache.get(tmp_path / "other.jpg", L1) is None
    cache.prefetch([path])
    assert cache.wait_idle(1)


def test_no_threads_until_first_request(cache_factory):
    assert cache_factory()._threads == []


def test_settings_from_config(tmp_path):
    class Config:
        @staticmethod
        def get(name, default=None):
            assert name == "image_cache"
            return {"disk_dir": "var/c", "memory_limit_mb": 64, "workers": 3, "unknown": 1}

    paths = AppPaths(tmp_path)
    settings = CacheSettings.from_config(Config, paths)
    assert settings.disk_dir == tmp_path / "var" / "c"
    assert (settings.memory_limit_mb, settings.workers, settings.max_l3) == (64, 3, 6)


def test_service_is_registered_in_core(qapp, tmp_path):
    from atlas.app import build_core

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "app.json").write_text('{"database": {"path": "var/a.sqlite"}}', encoding="utf-8")
    (tmp_path / "config" / "features.json").write_text('{"features": []}', encoding="utf-8")
    ctx = build_core(AppPaths(tmp_path))
    assert isinstance(ctx.services.get("image_cache"), ImageCache)
