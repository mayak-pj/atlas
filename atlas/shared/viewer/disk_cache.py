"""Локальный кэш L0/L1: файлы JPEG, ключ — путь + размер + mtime. Ошибки диска не мешают работе: кэш лишь ускоряет."""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import uuid
from pathlib import Path

from atlas.shared.viewer.decode import read_small

log = logging.getLogger("atlas.viewer.disk_cache")

_FORMAT_VERSION = "1"  # поднять, если меняется способ получения уровней
_TRIM_EVERY_SAVES = 200
_TRIM_TO = 0.9  # чистим с запасом, чтобы не запускать очистку на каждой записи


def default_cache_dir():
    """%LOCALAPPDATA%\\Atlas\\cache; на Mac — ~/.cache/Atlas/cache."""
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / ".cache") / "Atlas" / "cache"


class DiskCache:
    def __init__(self, folder, limit_bytes, quality=85):
        self.folder = Path(folder)
        self.limit_bytes = limit_bytes
        self.quality = quality
        self._lock = threading.Lock()
        self._saves = 0
        self.enabled = self._prepare()

    def _prepare(self):
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            probe = self.folder / ".probe_{}".format(uuid.uuid4().hex)
            probe.write_bytes(b"")
            probe.unlink()
            return True
        except OSError as exc:
            log.warning("Локальный кэш отключён, папка %s недоступна: %s", self.folder, exc)
            return False

    def _file(self, signature, level):
        path, size, mtime = signature
        text = "{}|{}|{}|{}".format(_FORMAT_VERSION, os.path.normcase(path), size, mtime)
        digest = hashlib.sha1(text.encode("utf-8", "surrogatepass")).hexdigest()
        return self.folder / digest[:2] / "{}_L{}.jpg".format(digest, level)

    def has(self, signature, level):
        return self.enabled and self._file(signature, level).is_file()

    def load(self, signature, level):
        """QImage или None. Испорченный файл удаляется: уровень будет построен заново."""
        if not self.enabled:
            return None
        target = self._file(signature, level)
        if not target.is_file():
            return None
        image = read_small(target)
        try:
            if image is None:
                log.warning("Испорченный файл кэша удалён: %s", target)
                target.unlink()
            else:
                os.utime(str(target), None)  # для очистки: «давно не открывали»
        except OSError as exc:
            log.debug("Файл кэша %s: %s", target, exc)
        return image

    def save(self, signature, level, image):
        """Запись через временный файл: второй экземпляр программы и обрыв питания не увидят половину JPEG."""
        if not self.enabled:
            return
        target = self._file(signature, level)
        temp = target.with_name("{}.{}.tmp".format(target.name, uuid.uuid4().hex))
        try:
            target.parent.mkdir(exist_ok=True)
            if not image.save(str(temp), "JPEG", self.quality):
                raise OSError("Qt не записал файл")
            os.replace(str(temp), str(target))
        except OSError as exc:
            log.warning("Не записан файл кэша %s: %s", target, exc)
            _remove_quietly(temp)
            return
        self._trim_sometimes()

    def _trim_sometimes(self):
        with self._lock:
            due = self._saves % _TRIM_EVERY_SAVES == 0  # первая запись после старта тоже проверяет объём
            self._saves += 1
        if due:
            self.trim()

    def trim(self):
        """Удаляет файлы, которые дольше всех не открывали, пока не останется 90% лимита."""
        entries = []
        total = 0
        for path in self.folder.rglob("*"):
            try:
                if path.is_file():
                    stat = path.stat()
                    entries.append((stat.st_mtime, stat.st_size, path))
                    total += stat.st_size
            except OSError:  # файл удалил второй экземпляр программы
                continue
        if total <= self.limit_bytes:
            return
        goal = self.limit_bytes * _TRIM_TO
        for _, size, path in sorted(entries, key=lambda entry: entry[:2]):
            if total <= goal:
                break
            if _remove_quietly(path):
                total -= size


def _remove_quietly(path):
    try:
        path.unlink()
        return True
    except OSError:
        return False
