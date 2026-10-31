"""Реестр сервисов: как функции получают что-то друг от друга."""
from __future__ import annotations

import threading


class ServiceRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._services = {}

    def register(self, name, service):
        with self._lock:
            if name in self._services:
                raise ValueError("Сервис уже зарегистрирован: {}".format(name))
            self._services[name] = service

    def unregister(self, name):
        with self._lock:
            self._services.pop(name, None)

    def get(self, name):
        """Сервис, который обязан быть. Если его нет — KeyError."""
        with self._lock:
            return self._services[name]

    def get_optional(self, name):
        """Сервис или None: вызывающий скрывает свой блок, а не падает."""
        with self._lock:
            return self._services.get(name)
