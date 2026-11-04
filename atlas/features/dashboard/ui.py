from __future__ import annotations

import logging
import threading

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from atlas.core.feature import Feature
from atlas.features.dashboard import logic
from atlas.features.dashboard.screen import TEXT_LOAD_FAILED, DashboardScreen

log = logging.getLogger("atlas.dashboard")

STOP_WAIT_S = 3.0
RELOAD_MS = 800
RELOAD_EVENTS = ("folder.done", "photo.marked", "type.added", "type.archived", "type.restored", "type.deleted", "folder.deleted")


class _Signals(QObject):
    loaded = pyqtSignal(object)  # Stats или None, если база недоступна


class DashboardFeature(Feature):
    """Вкладка «Дашборд»: цифры за неделю / месяц / год из сервисов ядра `folders` и `parts`; новые типы — из
    `type_db`, если он есть (нет — «0»). Своих таблиц нет. Читает в фоне; обновляется при показе вкладки и
    после событий (если вкладка открыта)."""

    def on_start(self):
        self._stopped = False
        self._threads = []
        self._reading = False
        self._again = False
        self.signals = _Signals()
        self.signals.loaded.connect(self._on_loaded)
        self.screen = None
        self.reload_timer = QTimer()
        self.reload_timer.setSingleShot(True)
        self.reload_timer.setInterval(RELOAD_MS)
        self.reload_timer.timeout.connect(self._reload_if_visible)
        self._unsubscribe = [self.ctx.bus.subscribe(name, lambda _p: self.reload_timer.start())
                             for name in RELOAD_EVENTS]

    def create_tab(self):
        self.screen = DashboardScreen(tuple(self.ctx.services.get("parts").kinds))
        self.screen.period_changed.connect(lambda _key: self.reload())
        self.screen.kind_changed.connect(lambda _key: self.reload())
        self.screen.shown.connect(self.reload)
        return self.screen

    def on_stop(self):
        self._stopped = True
        self.reload_timer.stop()
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        for thread in list(self._threads):
            thread.join(STOP_WAIT_S)

    def _reload_if_visible(self):
        if self.screen is not None and self.screen.isVisible():
            self.reload()

    def reload(self):
        if self._stopped or self.screen is None:
            return
        if self._reading:
            self._again = True
            return
        self._reading = True
        thread = threading.Thread(target=self._read, args=(self.screen.period, self.screen.kind), daemon=True)
        self._threads.append(thread)
        thread.start()

    def _read(self, period, kind):
        try:
            result = self._collect(period, kind)
        except Exception as exc:  # нет сети: остаётся прежнее
            log.warning("Не удалось прочитать данные дашборда: %s", exc)
            result = None
        self.signals.loaded.emit(result)

    def _collect(self, period, kind):
        since, until, label = logic.period_range(period)
        clean_since, clean_until = logic.clean_range()
        folders = self.ctx.services.get("folders")
        parts = {part.id: part for part in self.ctx.services.get("parts").all()}
        types = []
        type_db = self.ctx.services.get_optional("type_db")
        if type_db is not None:
            types = [item.part_id for item in type_db.search("", True)
                     if item.kind == "type" and since <= item.created_at < until]
        return logic.build(parts, folders.activity(since, until), folders.activity(clean_since, clean_until), types,
                           kind, label, logic.PERIOD_NOTE[period])

    def _on_loaded(self, stats):
        self._reading = False
        self._threads = [thread for thread in self._threads if thread.is_alive()]
        if self._stopped:
            return
        if self.screen is not None:
            if stats is None:
                self.screen.show_error(TEXT_LOAD_FAILED)
            else:
                self.screen.set_stats(stats)
        if self._again:
            self._again = False
            self.reload()
