"""ImageCache — сервис image_cache: уровни L0–L3, память, локальный диск, фоновая очередь.

Методы можно вызывать из GUI-потока: они смотрят только в память, а всё остальное делают рабочие потоки.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QImage

from atlas.shared.viewer import decode
from atlas.shared.viewer.disk_cache import DiskCache, default_cache_dir
from atlas.shared.viewer.job_queue import JobQueue
from atlas.shared.viewer.levels import CURRENT, DISK_LEVELS, L0, L1, L2, L3, WARMUP
from atlas.shared.viewer.memory_cache import MemoryCache

log = logging.getLogger("atlas.viewer.image_cache")

_MB = 1024 * 1024
_STOP_WAIT_S = 2.0  # чтение с оборванного сетевого диска не должно держать закрытие программы


@dataclass(frozen=True)
class CacheSettings:
    disk_dir: Path
    memory_limit_mb: int = 2048
    disk_limit_mb: int = 4096
    max_l2: int = 12
    max_l3: int = 6
    workers: int = 2
    retry_after_s: float = 10.0
    thumbnail_side: int = 160
    disk_quality: int = 85

    @classmethod
    def from_config(cls, config, paths):
        """Настройки из раздела image_cache. Пустой disk_dir — %LOCALAPPDATA%\\Atlas\\cache."""
        section = config.get("image_cache", {})
        values = {key: section[key] for key in cls.__dataclass_fields__ if key in section and key != "disk_dir"}
        folder = section.get("disk_dir")
        return cls(disk_dir=paths.resolve(folder) if folder else default_cache_dir(), **values)


class ImageCache(QObject):
    ready = pyqtSignal(str, int, QImage)  # путь, уровень, картинка; приходит в потоке получателя
    failed = pyqtSignal(str, int, str)  # путь, уровень, текст ошибки

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._memory = MemoryCache(settings.memory_limit_mb * _MB, {L2: settings.max_l2, L3: settings.max_l3})
        self._disk = None  # создаётся в рабочем потоке: это обращение к диску
        self._disk_lock = threading.Lock()
        self._queue = JobQueue(settings.workers)
        self._threads = []
        self._lock = threading.Lock()
        self._failures = {}  # (путь, уровень) → когда не получилось
        self._epoch = 0
        self._stopped = False

    def get(self, path, level, priority=CURRENT):
        """Лучшее из памяти сразу: CachedImage(image, level) или None.

        Если уровень ниже запрошенного или картинки нет — запрос уходит в очередь, ответ придёт сигналом ready или failed.
        """
        path = str(path)
        hit = self._memory.best(path, level)
        if hit is None or hit.level < level:
            self._enqueue(path, level, priority, True)
        return hit

    def prefetch(self, paths):
        """Подготовить L0 и L1 на локальном диске, в память не загружать. Ошибки не сообщаются: это только ускорение."""
        for path in paths:
            self._enqueue(str(path), L1, WARMUP, False)

    def cancel_pending(self):
        """Вызывать при переходе к другому фото: ещё не начатое для прежнего уже не нужно. Прогрев продолжается."""
        self._queue.cancel_foreground()

    def forget(self, path):
        """Файл заменён: убрать его из памяти. На диске новый файл найдётся по новому размеру и mtime."""
        path = str(path)
        with self._lock:
            self._epoch += 1
            for key in [key for key in self._failures if key[0] == path]:
                del self._failures[key]
        self._memory.forget(path)

    def wait_idle(self, timeout=30.0):
        """Ждать конца всей работы. Для проверок и замеров, из GUI-потока не вызывать."""
        return self._queue.wait_idle(timeout)

    def stop(self):
        """Завершить потоки. Зависшее на сети чтение не ждём дольше 2 с: потоки фоновые."""
        with self._lock:
            self._stopped = True
            threads = list(self._threads)
        self._queue.close()
        deadline = time.monotonic() + _STOP_WAIT_S
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))

    def _enqueue(self, path, level, priority, to_memory):
        with self._lock:
            if self._stopped:
                return
            failed_at = self._failures.get((path, level))
            if failed_at is not None:
                if time.monotonic() - failed_at < self._settings.retry_after_s:
                    return  # иначе перерисовка окна запрашивала бы битый файл без конца
                del self._failures[(path, level)]
            if not self._threads:
                for number in range(max(1, self._settings.workers)):
                    thread = threading.Thread(target=self._work, name="atlas-image-{}".format(number), daemon=True)
                    self._threads.append(thread)
                    thread.start()
        self._queue.put(path, level, priority, to_memory)

    def _work(self):
        while True:
            job = self._queue.take()
            if job is None:
                return
            try:
                self._process(job)
            except (decode.DecodeError, OSError) as exc:
                log.warning("Не загружено фото: %s", exc)
                self._report_failure(job, str(exc))
            except Exception as exc:  # поток не должен умереть: без него встанет весь просмотр
                log.exception("Сбой загрузки %s", job.path)
                self._report_failure(job, str(exc))
            finally:
                self._queue.done(job)

    def _report_failure(self, job, text):
        if not job.to_memory:
            return
        with self._lock:
            self._failures[job.key] = time.monotonic()
            if self._stopped:
                return
        self.failed.emit(job.path, job.level, text)

    def _process(self, job):
        with self._lock:
            epoch = self._epoch
        signature = decode.file_signature(job.path)
        if job.level in DISK_LEVELS:
            image = self._small_level(job, signature)
        else:
            image = decode.decode_file(job.path, job.level)
        if image is None or not job.to_memory:
            return
        with self._lock:
            if self._stopped or epoch != self._epoch:  # пока читали, файл объявили заменённым
                return
        self._memory.put(job.path, job.level, image, image.sizeInBytes())
        self.ready.emit(job.path, job.level, image)

    def _disk_cache(self):
        with self._disk_lock:
            if self._disk is None:
                settings = self._settings
                self._disk = DiskCache(settings.disk_dir, settings.disk_limit_mb * _MB, settings.disk_quality)
            return self._disk

    def _small_level(self, job, signature):
        """L0 и L1 получаются за одно чтение исходника и сразу оба попадают на диск."""
        disk = self._disk_cache()
        if not job.to_memory and (not disk.enabled or (disk.has(signature, L0) and disk.has(signature, L1))):
            return None  # прогрев: уже готово или некуда класть
        if job.to_memory:
            cached = disk.load(signature, job.level)
            if cached is not None:
                return cached
        preview = disk.load(signature, L1)
        if preview is None:
            preview = decode.decode_file(job.path, L1)
            disk.save(signature, L1, preview)
        thumbnail = decode.make_thumbnail(preview, self._settings.thumbnail_side)
        if not disk.has(signature, L0):
            disk.save(signature, L0, thumbnail)
        return thumbnail if job.level == L0 else preview


def create_image_cache(config, paths, parent=None):
    return ImageCache(CacheSettings.from_config(config, paths), parent)
