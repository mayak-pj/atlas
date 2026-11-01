from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtWidgets import QLabel

from atlas.core.feature import Feature
from atlas.features.presence import logic
from atlas.features.presence.repo import PresenceRepo

log = logging.getLogger("atlas.presence")

SLOT_ONLINE = "shell.online"
EVENT_CHANGED = "presence.changed"
DEFAULT_HEARTBEAT_S = 30
DEFAULT_OFFLINE_AFTER_S = 90
STOP_WAIT_S = 2.0  # сеть могла пропасть: дольше не держим закрытие программы


@dataclass(frozen=True)
class OnlineUser:
    user_id: int
    name: str
    color: str
    folder_id: Optional[int]
    folder_text: Optional[str]


class _Signals(QObject):
    finished = pyqtSignal(object)


class PresenceFeature(Feature):
    """Сервис «presence»: online() — [OnlineUser], working_on(folder_id) — [OnlineUser]. БД не трогают, отвечают из памяти."""

    def on_start(self):
        self.repo = PresenceRepo(self.ctx.db)
        heartbeat = self.ctx.config.get("presence.heartbeat_s", DEFAULT_HEARTBEAT_S)
        offline_after = self.ctx.config.get("presence.offline_after_s", DEFAULT_OFFLINE_AFTER_S)
        self.tracker = logic.OnlineTracker(offline_after)
        self.user = None
        self.folder_id = None
        self._online = []
        self._folder_texts = {}  # папка не меняет деталь и дату: достаточно прочитать один раз
        self._thread = None
        self._again = False
        self._stopped = False
        self.label = None
        self.signals = _Signals()
        self.signals.finished.connect(self._on_finished)
        self.timer = QTimer()
        self.timer.setInterval(int(heartbeat * 1000))
        self.timer.timeout.connect(self._tick)
        bus = self.ctx.bus
        self._unsubscribe = [
            bus.subscribe("user.logged_in", self._on_login),
            bus.subscribe("folder.opened", self._on_folder_opened),
            bus.subscribe("folder.done", self._on_folder_done),
        ]
        self.ctx.services.register("presence", self)

    def on_stop(self):
        self._stopped = True
        self.timer.stop()
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self.ctx.services.unregister("presence")
        if self._thread is not None:
            self._thread.join(STOP_WAIT_S)
        if self.user is not None:
            leaving = threading.Thread(target=self._leave, args=(self.user.id,), daemon=True)
            leaving.start()
            leaving.join(STOP_WAIT_S)

    # --- сервис ---------------------------------------------------------------
    def online(self):
        return list(self._online)

    def working_on(self, folder_id):
        return [item for item in self._online if item.folder_id == folder_id]

    # --- события --------------------------------------------------------------
    def _on_login(self, payload):
        self.user = payload["user"]
        self.label = QLabel()
        self.label.setProperty("role", "muted")
        self.label.hide()
        if self.ctx.shell is not None:
            self.ctx.shell.add_panel(SLOT_ONLINE, self.label, key="presence")
        self.label.hide()  # слот показывает панель сразу, а список ещё пуст
        self.timer.start()
        self._tick()

    def _on_folder_opened(self, payload):
        self.folder_id = payload.get("folder_id")
        self._tick()

    def _on_folder_done(self, payload):
        if payload.get("folder_id") == self.folder_id:
            self.folder_id = None
            self._tick()

    # --- сигнал: только в фоновом потоке и по одному ---------------------------
    def _tick(self):
        if self.user is None or self._stopped:
            return
        if self._thread is not None:
            self._again = True  # папка сменилась, пока идёт запрос: повторим сразу после него
            return
        self._thread = threading.Thread(target=self._work, args=(self.user.id, self.folder_id), daemon=True)
        self._thread.start()

    def _work(self, user_id, folder_id):
        result = None
        try:
            self.repo.beat(user_id, folder_id)
            result = self._read()
        except Exception as exc:  # нет сети, база занята: покажем по старым данным, следующий сигнал — через heartbeat
            log.warning("Не удалось обновить присутствие: %s", exc)
        self.signals.finished.emit(result)

    def _read(self):
        rows = self.repo.rows()
        people = {user.id: user for user, _ in self.ctx.services.get("users").all()}
        for folder_id in {row.folder_id for row in rows if row.folder_id is not None}:
            if folder_id not in self._folder_texts:
                self._folder_texts[folder_id] = self._describe(folder_id)
        return rows, people

    def _describe(self, folder_id):
        folder = self.ctx.services.get("folders").get(folder_id)
        if folder is None:
            return None
        return logic.describe_folder(folder, self.ctx.services.get("parts").get(folder.part_id))

    def _leave(self, user_id):
        try:
            self.repo.leave(user_id)
        except Exception as exc:  # запись исчезнет сама: другие перестанут видеть сигнал
            log.warning("Не удалось отметить выход: %s", exc)

    def _on_finished(self, result):
        self._thread = None
        if self._stopped:
            return
        if result is not None:  # база недоступна — чужие сигналы неизвестны, поэтому держим прежний список
            rows, people = result
            self._apply(self._build(self.tracker.update(rows, time.monotonic()), people))
        if self._again:
            self._again = False
            self._tick()

    def _build(self, rows, people):
        result = []
        for row in rows:
            user = people.get(row.user_id)
            if user is not None:
                text = self._folder_texts.get(row.folder_id) if row.folder_id is not None else None
                result.append(OnlineUser(user.id, user.name, user.color, row.folder_id, text))
        return sorted(result, key=lambda item: item.name)

    def _apply(self, online):
        changed = online != self._online
        self._online = online
        others = [item for item in online if self.user is None or item.user_id != self.user.id]
        if self.label is not None:
            self.label.setText(logic.online_text([item.name for item in others]))
            self.label.setToolTip(logic.tooltip_text([(item.name, item.folder_text) for item in others]))
            self.label.setVisible(bool(others))
        if changed:
            self.ctx.bus.publish(EVENT_CHANGED, {"online": list(online)})
