"""Шина событий. publish можно вызывать из любого потока.

Обработчики всегда выполняются в потоке, где создана шина (GUI-поток): из других потоков
событие приходит через очередь Qt. Ошибка обработчика не мешает остальным и не роняет программу.
"""
from __future__ import annotations

import logging
import threading

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

log = logging.getLogger("atlas.bus")


class EventBus(QObject):
    _event = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._handlers = {}
        self._event.connect(self._dispatch)

    def subscribe(self, event, handler):
        """Подписаться. Возвращает функцию отписки."""
        with self._lock:
            self._handlers.setdefault(event, []).append(handler)

        def unsubscribe():
            with self._lock:
                handlers = self._handlers.get(event, [])
                if handler in handlers:
                    handlers.remove(handler)

        return unsubscribe

    def publish(self, event, data=None):
        self._event.emit(event, {} if data is None else data)

    @pyqtSlot(str, object)
    def _dispatch(self, event, data):
        with self._lock:
            handlers = list(self._handlers.get(event, []))
        for handler in handlers:
            try:
                handler(data)
            except Exception:
                log.exception("Ошибка в обработчике события %s", event)
