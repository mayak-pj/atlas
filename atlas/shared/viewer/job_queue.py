"""Очередь декодирования: текущее > соседи > прогрев. Без Qt.

Внутри приоритета новые запросы идут первыми: при удержании стрелки важен последний кадр, а не пролистанные.
Прогрев идёт по порядку и никогда не занимает все потоки: иначе текущее фото ждало бы чужое чтение с сетевого диска.
"""
from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass

from atlas.shared.viewer.levels import WARMUP


@dataclass
class Job:
    path: str
    level: int
    priority: int
    to_memory: bool
    order: int = 0

    @property
    def key(self):
        return self.path, self.level


class JobQueue:
    def __init__(self, workers):
        self._warmup_limit = max(1, workers - 1)
        self._condition = threading.Condition()
        self._pending = {}
        self._running = {}
        self._counter = itertools.count(1)
        self._closed = False

    def put(self, path, level, priority, to_memory):
        job = Job(path, level, priority, to_memory)
        with self._condition:
            if self._closed:
                return
            running = self._running.get(job.key)
            if running is not None and (running.to_memory or not to_memory):
                return  # уже делается, результат подойдёт
            queued = self._pending.get(job.key)
            if queued is not None:
                job.priority = min(queued.priority, priority)
                job.to_memory = queued.to_memory or to_memory
                if job.priority == WARMUP:
                    return  # прогрев не теряет своё место в очереди
            count = next(self._counter)
            job.order = count if job.priority == WARMUP else -count
            self._pending[job.key] = job
            self._condition.notify()

    def take(self):
        """Следующая работа; ждёт, пока она появится. None — очередь закрыта."""
        with self._condition:
            while True:
                if self._closed:
                    return None
                job = self._next_job()
                if job is not None:
                    del self._pending[job.key]
                    self._running[job.key] = job
                    return job
                self._condition.wait()

    def _next_job(self):
        warmups = sum(1 for job in self._running.values() if job.priority == WARMUP)
        allowed = [
            job for job in self._pending.values()
            if job.key not in self._running and (job.priority != WARMUP or warmups < self._warmup_limit)
        ]
        return min(allowed, key=lambda job: (job.priority, job.order), default=None)

    def done(self, job):
        with self._condition:
            self._running.pop(job.key, None)
            self._condition.notify_all()

    def cancel_foreground(self):
        """Забыть несделанное, кроме прогрева: пользователь ушёл на другое фото."""
        with self._condition:
            self._pending = {key: job for key, job in self._pending.items() if job.priority == WARMUP}
            self._condition.notify_all()

    def wait_idle(self, timeout):
        """True — вся работа завершена."""
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._pending or self._running:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._condition.wait(left)
            return True

    def close(self):
        with self._condition:
            self._closed = True
            self._pending.clear()
            self._condition.notify_all()
