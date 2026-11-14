"""Замер запуска (14.11.2026, замечание с выезда: «запускается секунд 30»).

В журнал пишется, сколько заняли части запуска: от создания процесса до Python (распаковка и загрузка exe и DLL —
с сетевого диска и через антивирус это и бывает долго), окно Qt, база, функции, окно входа, окно программы.
"""
from __future__ import annotations

import logging
import sys
import time

log = logging.getLogger("atlas.startup")


def process_age():
    """Секунд с создания процесса или None (не Windows, не удалось узнать)."""
    if sys.platform != "win32":
        return None
    try:
        from atlas.core.process_start_win import age_seconds

        return age_seconds()
    except (OSError, ImportError, AttributeError, ValueError):
        return None


class StartupTimer:
    def __init__(self, clock=time.monotonic, age=process_age):
        self._clock = clock
        self._start = clock()
        self._last = self._start
        self.before_python = age()  # всё, что было до первой строки main
        self.steps = []  # [(что, секунд)]

    def mark(self, what):
        now = self._clock()
        self.steps.append((what, now - self._last))
        self._last = now

    def total(self):
        return (self._last - self._start) + (self.before_python or 0.0)

    def text(self):
        parts = []
        if self.before_python is not None:
            parts.append("до Python {:.1f} с".format(self.before_python))
        parts += ["{} {:.1f} с".format(what, seconds) for what, seconds in self.steps]
        return "Запуск: {}; всего {:.1f} с".format(", ".join(parts), self.total())

    def log(self):
        log.info(self.text())
