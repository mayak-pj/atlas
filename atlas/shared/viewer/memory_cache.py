"""LRU в памяти: общий лимит в байтах и потолок числа записей на уровень. Без Qt, потокобезопасно."""
from __future__ import annotations

import threading
from collections import OrderedDict, namedtuple

CachedImage = namedtuple("CachedImage", "image level")
_LEVEL_COUNT = 4


class MemoryCache:
    def __init__(self, limit_bytes, max_items=None):
        self.limit_bytes = limit_bytes
        self._max_items = dict(max_items or {})
        self._lock = threading.Lock()
        self._items = OrderedDict()  # (путь, уровень) → (значение, байты); в начале — самое старое
        self._bytes = 0

    @property
    def size_bytes(self):
        with self._lock:
            return self._bytes

    def put(self, path, level, value, size):
        key = (path, level)
        with self._lock:
            self._remove(key)
            if size > self.limit_bytes:  # такое вытеснило бы всё и само не поместилось
                return
            self._items[key] = (value, size)
            self._bytes += size
            self._evict(level)

    def best(self, path, level):
        """Запрошенный уровень, иначе ближайший выше, иначе ближайший ниже. CachedImage или None."""
        with self._lock:
            for candidate in list(range(level, _LEVEL_COUNT)) + list(range(level - 1, -1, -1)):
                entry = self._items.get((path, candidate))
                if entry is not None:
                    self._items.move_to_end((path, candidate))
                    return CachedImage(entry[0], candidate)
        return None

    def forget(self, path):
        with self._lock:
            for key in [key for key in self._items if key[0] == path]:
                self._remove(key)

    def _remove(self, key):
        entry = self._items.pop(key, None)
        if entry is not None:
            self._bytes -= entry[1]

    def _evict(self, level):
        cap = self._max_items.get(level)
        if cap is not None:
            same = [key for key in self._items if key[1] == level]
            for key in same[: max(0, len(same) - cap)]:
                self._remove(key)
        while self._bytes > self.limit_bytes:
            self._remove(next(iter(self._items)))
