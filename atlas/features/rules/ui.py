from __future__ import annotations

import logging
import threading
from pathlib import Path

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from atlas.core.feature import Feature
from atlas.features.rules import logic
from atlas.features.rules.repo import Repo
from atlas.features.rules.screen import RulesPanel, RulesScreen
from atlas.features.rules.store import PhotoStore, StoreError

log = logging.getLogger("atlas.rules")

SLOT_RIGHT = "compare.right"
PANEL_KEY = "rules"
EVENT_PUBLISHED = "rule.published"
DEFAULT_DIR = "var/rules"  # TODO(OPEN_ITEMS №12): настоящая папка на сетевом диске
DEFAULT_REFRESH_S = 60
STOP_WAIT_S = 3.0
MESSAGE_MS = 8000
TEXT_PUBLISHED = "Правило опубликовано"
TEXT_FAILED = "Не удалось записать правило: база недоступна, попробуйте ещё раз"


class _Signals(QObject):
    loaded = pyqtSignal(object)  # (rules, names, part) или None, если база недоступна
    published = pyqtSignal(int, object)  # номер правила, Draft
    failed = pyqtSignal(str)


class RulesFeature(Feature):
    """Вкладка «Правила», счётчик непрочитанных на вкладке, панель «Правила к детали» в compare.right.

    Сервис «rules» (не из GUI-потока: ходит в базу): `for_part(part_id, user_id)` → [Rule] к детали,
    `unread_count(user_id)`. Событие `rule.published` — `{rule_id, part_id?}`.
    """

    def on_start(self):
        self._stopped = False
        self._busy_read = False
        self._again = False
        self._threads = []
        self.part_id = None
        self.rules, self.names, self.part = [], {}, None
        self.screen = None
        self.signals = _Signals()
        self.signals.loaded.connect(self._on_loaded)
        self.signals.published.connect(self._on_published)
        self.signals.failed.connect(self._on_failed)
        config = self.ctx.config
        configured = str(config.get("rules.dir", DEFAULT_DIR))
        self._root = self.ctx.paths.resolve(configured)
        self.repo = Repo(self.ctx.db)
        self.store = PhotoStore(self._root, create_root=not Path(configured).is_absolute())
        self.panel = RulesPanel(self._root)
        self.panel.read_requested.connect(self.mark_read)
        self.panel.photo_clicked.connect(self._open_photo)
        self._unsubscribe = [self.ctx.bus.subscribe("folder.opened", self._on_opened)]
        self._unsubscribe.append(self.ctx.bus.subscribe("user.logged_in", lambda _payload: self.refresh()))
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh)
        self.timer.start(int(float(config.get("rules.refresh_s", DEFAULT_REFRESH_S)) * 1000))
        self.ctx.services.register("rules", self)
        if self.ctx.shell is not None:
            self.ctx.shell.add_panel(SLOT_RIGHT, self.panel, key=PANEL_KEY, order=20)

    def create_tab(self):
        self.screen = RulesScreen(self._root, self.ctx.services.get("parts").kinds)
        self.screen.publish_requested.connect(self.publish)
        self.screen.read_requested.connect(self.mark_read)
        self.screen.read_all_requested.connect(self.mark_all_read)
        self.screen.shown.connect(self.refresh)
        self.refresh()
        return self.screen

    def badge(self):
        count = logic.unread_count(self.rules)
        return count or None

    def on_stop(self):
        self._stopped = True
        self.timer.stop()
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self.ctx.services.unregister("rules")
        for thread in list(self._threads):
            thread.join(STOP_WAIT_S)

    # --- сервис -----------------------------------------------------------------
    def for_part(self, part_id, user_id=None):
        part = self.ctx.services.get("parts").get(part_id)
        if part is None:
            return []
        return logic.for_part(self.repo.all(self._user_id(user_id)), part)

    def unread_count(self, user_id=None):
        return self.repo.unread_count(self._user_id(user_id))

    def _user_id(self, user_id=None):
        if user_id is not None:
            return user_id
        user = self.ctx.user
        return user.id if user is not None else 0

    # --- чтение -----------------------------------------------------------------
    def _spawn(self, target, *args):
        thread = threading.Thread(target=target, args=args, daemon=True)
        self._threads.append(thread)
        thread.start()

    def _on_opened(self, payload):
        self.part_id = payload.get("part_id")
        self.refresh()

    def refresh(self):
        if self._stopped:
            return
        if self._busy_read:
            self._again = True
            return
        self._busy_read = True
        self._spawn(self._read, self._user_id(), self.part_id)

    def _read(self, user_id, part_id):
        try:
            rules = self.repo.all(user_id)
            names = {user.id: user.name for user, _ in self.ctx.services.get("users").all()}
            part = self.ctx.services.get("parts").get(part_id) if part_id is not None else None
            result = (rules, names, part)
        except Exception as exc:  # нет сети, база занята: остаётся прежнее
            log.warning("Не удалось прочитать правила: %s", exc)
            result = None
        self.signals.loaded.emit(result)

    def _on_loaded(self, result):
        self._busy_read = False
        self._threads = [thread for thread in self._threads if thread.is_alive()]
        if self._stopped:
            return
        if result is not None:
            self.rules, self.names, self.part = result
            if self.screen is not None:
                self.screen.set_data(self.rules, self.names, self.part)
            self.panel.show_rules(logic.for_part(self.rules, self.part) if self.part is not None else [], self.names)
            if self.ctx.shell is not None and hasattr(self.ctx.shell, "refresh_badges"):
                self.ctx.shell.refresh_badges()
        if self._again:
            self._again = False
            self.refresh()

    # --- запись -----------------------------------------------------------------
    def publish(self, draft):
        if self.screen is not None:
            self.screen.set_busy(True)
        self._spawn(self._write, draft, self._user_id())

    def _write(self, draft, user_id):
        rels = []
        try:
            draft = logic.checked(draft)
            rels = self.store.save(draft.photo_paths)
            rule_id = self.repo.add(draft, user_id or None, rels)
        except (logic.RuleError, StoreError) as exc:
            self.store.discard_rels(rels)
            self.signals.failed.emit(str(exc))
            return
        except Exception as exc:  # база не ответила: файлы не оставляем
            log.warning("Не удалось записать правило: %s", exc)
            self.store.discard_rels(rels)
            self.signals.failed.emit(TEXT_FAILED)
            return
        self.signals.published.emit(rule_id, draft)

    def _on_published(self, rule_id, draft):
        if self._stopped:
            return
        if self.screen is not None:
            self.screen.set_busy(False)
            self.screen.clear_form()
        self.ctx.bus.publish(EVENT_PUBLISHED, {"rule_id": rule_id, "part_id": draft.part_id})
        if self.ctx.shell is not None:
            self.ctx.shell.show_message(TEXT_PUBLISHED, MESSAGE_MS)
        self.refresh()

    def _on_failed(self, text):
        if self._stopped:
            return
        if self.screen is not None:
            self.screen.set_busy(False)
            self.screen.show_error(text)

    def mark_read(self, rule_ids):
        self._spawn(self._mark, list(rule_ids), False)

    def mark_all_read(self):
        self._spawn(self._mark, [], True)

    def _mark(self, rule_ids, everything):
        user_id = self._user_id()
        try:
            if everything:
                self.repo.mark_all_read(user_id)
            else:
                self.repo.mark_read(rule_ids, user_id)
        except Exception as exc:
            log.warning("Не удалось отметить прочитанным: %s", exc)
        self._again = True
        self.signals.loaded.emit(None)  # перечитать: «занято» снимется само

    def _open_photo(self, rels, index):
        from atlas.features.rules.screen import PhotoDialog

        PhotoDialog(self._root, rels, index, self.panel).exec_()
