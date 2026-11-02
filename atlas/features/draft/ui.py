from __future__ import annotations

import logging
import threading

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from atlas.core.feature import Feature
from atlas.features.draft import logic
from atlas.features.draft.repo import Repo
from atlas.features.draft.screen import DraftScreen

log = logging.getLogger("atlas.draft")

SLOT_ACTIONS = "draft.actions"
STOP_WAIT_S = 3.0
RELOAD_MS = 400
TEXT_FAILED = "Не удалось сохранить: база недоступна, попробуйте ещё раз"


class _Signals(QObject):
    loaded = pyqtSignal(object)  # (folder_id, notes, entries) или None
    saved = pyqtSignal()
    failed = pyqtSignal(str)
    manual_added = pyqtSignal()


class DraftFeature(Feature):
    """Вкладка «Черновик» для открытой папки. Слот `draft.actions` — кнопки других функций (report, sort_types).

    Сервис «draft»: `snapshot(folder_id, user_id=None)` → `Snapshot(notes, entries)` — не из GUI-потока.
    Строки собираются из отметок фото открытой папки (`photo.marked`), ручные — в `draft_items`.
    """

    def on_start(self):
        self._stopped = False
        self._threads = []
        self._reading = False
        self._again = False
        self.folder_id = None
        self.screen = None
        self.signals = _Signals()
        self.signals.loaded.connect(self._on_loaded)
        self.signals.saved.connect(self._on_saved)
        self.signals.failed.connect(self._on_failed)
        self.signals.manual_added.connect(self._on_manual_added)
        self.repo = Repo(self.ctx.db)
        self.reload_timer = QTimer()
        self.reload_timer.setSingleShot(True)
        self.reload_timer.setInterval(RELOAD_MS)
        self.reload_timer.timeout.connect(self.reload)
        self._unsubscribe = [self.ctx.bus.subscribe("folder.opened", self._on_opened),
                             self.ctx.bus.subscribe("photo.marked", lambda _p: self.reload_timer.start()),
                             self.ctx.bus.subscribe("folder.sorted", lambda _p: self.reload_timer.start())]
        self.ctx.services.register("draft", self)

    def create_tab(self):
        self.screen = DraftScreen()
        self.screen.notes_changed.connect(self.save_notes)
        self.screen.text_changed.connect(self.save_text)
        self.screen.remove_requested.connect(self.remove_manual)
        self.screen.add_requested.connect(self.add_manual)
        self.screen.shown.connect(self.reload)
        shell = self.ctx.shell
        if shell is not None and hasattr(shell, "register_slot"):
            shell.register_slot(SLOT_ACTIONS, self.screen.actions_layout())
        self.screen.set_folder(self.folder_id is not None)
        self.reload()
        return self.screen

    def on_stop(self):
        if self.screen is not None:
            try:
                self.screen.flush()
            except RuntimeError:  # окно уже уничтожено
                pass
        self._stopped = True
        self.reload_timer.stop()
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self.ctx.services.unregister("draft")
        for thread in list(self._threads):
            thread.join(STOP_WAIT_S)

    # --- сервис -----------------------------------------------------------------
    def snapshot(self, folder_id, user_id=None):
        """Заметки и строки найденного папки — для Excel и письма (8.2)."""
        notes, comments, manual = self.repo.load(folder_id, self._user_id(user_id))
        photos = self.ctx.services.get("folders").photos(folder_id)
        return Snapshot(notes, logic.all_entries(photos, comments, manual))

    def _user_id(self, user_id=None):
        if user_id is not None:
            return user_id
        user = self.ctx.user
        return user.id if user is not None else 0

    def _spawn(self, target, *args):
        thread = threading.Thread(target=target, args=args, daemon=True)
        self._threads.append(thread)
        thread.start()

    # --- чтение -----------------------------------------------------------------
    def _on_opened(self, payload):
        if self.screen is not None:
            self.screen.flush()  # заметки прежней папки уходят в её запись
        self.folder_id = payload.get("folder_id")
        if self.screen is not None:
            self.screen.set_folder(self.folder_id is not None)
        self.reload()

    def reload(self):
        if self._stopped or self.folder_id is None:
            return
        if self._reading:
            self._again = True
            return
        self._reading = True
        self._spawn(self._read, self.folder_id, self._user_id())

    def _read(self, folder_id, user_id):
        try:
            notes, comments, manual = self.repo.load(folder_id, user_id)
            photos = self.ctx.services.get("folders").photos(folder_id)
            result = (folder_id, notes, logic.all_entries(photos, comments, manual))
        except Exception as exc:  # нет сети: остаётся прежнее
            log.warning("Не удалось прочитать черновик: %s", exc)
            result = None
        self.signals.loaded.emit(result)

    def _on_loaded(self, result):
        self._reading = False
        self._threads = [thread for thread in self._threads if thread.is_alive()]
        if self._stopped:
            return
        if result is not None and result[0] == self.folder_id and self.screen is not None:
            _folder, notes, entries = result
            self.screen.set_notes(notes)
            self.screen.set_entries(entries)
        if self._again:
            self._again = False
            self.reload()

    # --- запись -----------------------------------------------------------------
    def save_notes(self, text):
        if self.folder_id is not None:
            self._spawn(self._write, self.repo.save_notes, self.folder_id, self._user_id(), text)

    def save_text(self, entry, text):
        if self.folder_id is None:
            return
        if entry.manual_id is not None:
            self._spawn(self._write, self.repo.save_manual_text, entry.manual_id, text)
        else:
            self._spawn(self._write, self.repo.save_comment, self.folder_id, entry.key, text)

    def remove_manual(self, entry):
        self._spawn(self._write, self.repo.delete_manual, entry.manual_id)
        self.reload_timer.start()

    def add_manual(self, kind, type_no, sn, body):
        if self.folder_id is None:
            return
        try:
            kind, type_no, sn, body = logic.checked_manual(kind, type_no, sn, body)
        except logic.DraftError as exc:
            self.screen.show_error(str(exc))
            return
        self._spawn(self._add, self.folder_id, kind, type_no, sn, body, self._user_id())

    def _add(self, *args):
        try:
            self.repo.add_manual(*args)
        except Exception as exc:
            log.warning("Не удалось добавить строку черновика: %s", exc)
            self.signals.failed.emit(TEXT_FAILED)
            return
        self.signals.manual_added.emit()

    def _on_manual_added(self):
        if self._stopped:
            return
        if self.screen is not None:
            self.screen.form_done()
        self.reload()
        if self.folder_id is not None:
            self.ctx.bus.publish("draft.changed", {"folder_id": self.folder_id})

    def _write(self, method, *args):
        try:
            method(*args)
        except Exception as exc:
            log.warning("Не удалось сохранить черновик: %s", exc)
            self.signals.failed.emit(TEXT_FAILED)
            return
        self.signals.saved.emit()

    def _on_saved(self):
        if not self._stopped and self.screen is not None:
            self.screen.mark_saved()
        if not self._stopped and self.folder_id is not None:
            self.ctx.bus.publish("draft.changed", {"folder_id": self.folder_id})

    def _on_failed(self, text):
        if not self._stopped and self.screen is not None:
            self.screen.show_error(text)


class Snapshot:
    def __init__(self, notes, entries):
        self.notes, self.entries = notes, entries
