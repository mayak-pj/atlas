"""Один рабочий поток «Качества» на все окна (12.8). Без Qt.

Раньше каждое новое фото или зум запускали свой поток, и при листании одновременно шли 20+ расчётов «Pro»
(14–19 с каждый вместо 1–5). Теперь:
  - расчёт всегда один; у каждого окна (owner) ждёт не больше одной работы — новая заменяет прежнюю;
  - идущий расчёт прерывается между шагами снятия размытия, если его окно попросило другое или отменило;
  - результат прерванного или заменённого расчёта никому не отдаётся.
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("atlas.viewer.enhance")


class Cancelled(Exception):
    """Расчёт прерван: результат уже не нужен."""


class EnhanceWorker:
    def __init__(self):
        self._condition = threading.Condition()
        self._pending = {}  # owner → (key, work, done); порядок — кто раньше попросил
        self._running = None  # (owner, key, threading.Event отмены)
        self._thread = None
        self._closed = False

    def submit(self, owner, key, work, done):
        """Посчитать для окна `owner`: `work(cancelled)` в рабочем потоке, затем `done(key, result)` там же.

        `cancelled()` — True, если результат уже не нужен: `work` может бросить `Cancelled` или вернуть что угодно.
        Тот же ключ уже ждёт или считается — ничего не делает.
        """
        with self._condition:
            if self._closed:
                return
            running = self._running
            if running is not None and running[0] is owner:
                if running[1] == key and not running[2].is_set():
                    self._pending.pop(owner, None)
                    return  # уже считается именно это
                running[2].set()
            self._pending.pop(owner, None)  # заменённое уходит, новое — в конец очереди
            self._pending[owner] = (key, work, done)
            self._ensure_thread()
            self._condition.notify()

    def cancel(self, owner):
        """Окну больше ничего не нужно: забыть ждущее, прервать идущее."""
        with self._condition:
            self._pending.pop(owner, None)
            if self._running is not None and self._running[0] is owner:
                self._running[2].set()

    @property
    def busy(self):
        with self._condition:
            return self._running is not None or bool(self._pending)

    def wait_idle(self, timeout):
        """True — всё посчитано (для тестов)."""
        import time
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._running is not None or self._pending:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._condition.wait(left)
            return True

    def close(self):
        with self._condition:
            self._closed = True
            self._pending.clear()
            if self._running is not None:
                self._running[2].set()
            self._condition.notify_all()

    def _ensure_thread(self):
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name="enhance", daemon=True)
            self._thread.start()

    def _loop(self):
        while True:
            with self._condition:
                while not self._pending and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                owner = next(iter(self._pending))
                key, work, done = self._pending.pop(owner)
                stop = threading.Event()
                self._running = (owner, key, stop)
            result = None
            try:
                result = work(stop.is_set)
            except Cancelled:
                pass
            except Exception:  # «Качество» только украшение: не вышло — остаётся обычная картинка
                log.exception("Качество: расчёт не удался")
            try:
                if not stop.is_set():
                    done(key, result)
            except RuntimeError:  # окно уже удалено
                pass
            finally:
                with self._condition:
                    self._running = None
                    self._condition.notify_all()


_shared = None
_shared_lock = threading.Lock()


def shared_worker():
    """Общий поток «Качества» для всех окон программы."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = EnhanceWorker()
        return _shared
