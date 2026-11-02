from __future__ import annotations

import logging
import threading
from pathlib import Path

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from atlas.core.feature import Feature
from atlas.features.comments import logic
from atlas.features.comments.repo import Repo
from atlas.features.comments.screen import CommentsScreen
from atlas.features.comments.store import PhotoStore, StoreError

log = logging.getLogger("atlas.comments")

EVENT_POSTED = "comment.posted"
DEFAULT_DIR = "var/comments"  # TODO(OPEN_ITEMS №12): настоящая папка на сетевом диске
DEFAULT_REFRESH_S = 30
STOP_WAIT_S = 3.0
MESSAGE_MS = 6000
TEXT_SENT = "Сообщение отправлено"
TEXT_FAILED = "Не удалось отправить: база недоступна, попробуйте ещё раз"


class _Signals(QObject):
    loaded = pyqtSignal(object)  # (items, users, part) или None, если база недоступна
    posted = pyqtSignal(int, object)
    failed = pyqtSignal(str)


class CommentsFeature(Feature):
    """Вкладка «Комментарии» со счётчиком на вкладке. Сервис «comments»: `pending_count(user_id)` (не из GUI-потока).

    Событие `comment.posted` — `{comment_id, to_user}`. Истёкшие сообщения вместе с файлами фото удаляются
    при запуске и раз в сутки работы.
    """

    def on_start(self):
        self._stopped = False
        self._busy_read = False
        self._again = False
        self._purged = False
        self._threads = []
        self.part_id = self.folder_id = None
        self.items, self.users, self.part = [], {}, None
        self.screen = None
        self.signals = _Signals()
        self.signals.loaded.connect(self._on_loaded)
        self.signals.posted.connect(self._on_posted)
        self.signals.failed.connect(self._on_failed)
        config = self.ctx.config
        configured = str(config.get("comments.dir", DEFAULT_DIR))
        self._root = self.ctx.paths.resolve(configured)
        self.lifetimes, self.max_photos = logic.load_options(self.ctx.paths.data)
        self.repo = Repo(self.ctx.db)
        self.store = PhotoStore(self._root, create_root=not Path(configured).is_absolute())
        self._unsubscribe = [self.ctx.bus.subscribe("folder.opened", self._on_opened),
                             self.ctx.bus.subscribe("user.logged_in", lambda _payload: self.refresh())]
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh)
        self.timer.start(int(float(config.get("comments.refresh_s", DEFAULT_REFRESH_S)) * 1000))
        self.ctx.services.register("comments", self)

    def create_tab(self):
        can_open = self.ctx.services.get_optional("compare") is not None
        self.screen = CommentsScreen(self._root, self.lifetimes, self.max_photos, can_open)
        self.screen.send_requested.connect(self.send)
        self.screen.done_requested.connect(self.mark_done)
        self.screen.open_requested.connect(self._open_in_compare)
        self.screen.shown.connect(self.refresh)
        self.refresh()
        return self.screen

    def badge(self):
        return logic.pending_count(self.items, self._user_id()) or None

    def on_stop(self):
        self._stopped = True
        self.timer.stop()
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self.ctx.services.unregister("comments")
        for thread in list(self._threads):
            thread.join(STOP_WAIT_S)

    # --- сервис -----------------------------------------------------------------
    def pending_count(self, user_id=None):
        return logic.pending_count(self.repo.all(self._user_id(user_id)), self._user_id(user_id))

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
        self.part_id, self.folder_id = payload.get("part_id"), payload.get("folder_id")
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
            if not self._purged:
                self.store.discard_rels(self.repo.purge_expired())
                self._purged = True
            items = self.repo.all(user_id)
            users = {user.id: (user.name, user.color) for user, _ in self.ctx.services.get("users").all()}
            part = self.ctx.services.get("parts").get(part_id) if part_id is not None else None
            result = (items, users, part)
        except Exception as exc:  # нет сети, база занята: остаётся прежнее
            log.warning("Не удалось прочитать комментарии: %s", exc)
            result = None
        self.signals.loaded.emit(result)

    def _on_loaded(self, result):
        self._busy_read = False
        self._threads = [thread for thread in self._threads if thread.is_alive()]
        if self._stopped:
            return
        if result is not None:
            self.items, self.users, self.part = result
            if self.screen is not None:
                self.screen.set_data(self.items, self.users, self._user_id(), self.part, self.folder_id)
            if self.ctx.shell is not None and hasattr(self.ctx.shell, "refresh_badges"):
                self.ctx.shell.refresh_badges()
        if self._again:
            self._again = False
            self.refresh()

    # --- запись -----------------------------------------------------------------
    def send(self, draft):
        if self.screen is not None:
            self.screen.set_busy(True)
        self._spawn(self._write, draft, self._user_id())

    def _write(self, draft, user_id):
        rels = []
        try:
            draft = logic.checked(draft, self.max_photos)
            rels = self.store.save(draft.photos)
            comment_id = self.repo.add(draft, user_id, rels)
        except (logic.CommentError, StoreError) as exc:
            self.store.discard_rels(rels)
            self.signals.failed.emit(str(exc))
            return
        except Exception as exc:  # база не ответила: файлы не оставляем
            log.warning("Не удалось записать комментарий: %s", exc)
            self.store.discard_rels(rels)
            self.signals.failed.emit(TEXT_FAILED)
            return
        self.signals.posted.emit(comment_id, draft)

    def _on_posted(self, comment_id, draft):
        if self._stopped:
            return
        if self.screen is not None:
            self.screen.set_busy(False)
            self.screen.clear_form()
        self.ctx.bus.publish(EVENT_POSTED, {"comment_id": comment_id, "to_user": draft.to_user_id})
        if self.ctx.shell is not None:
            self.ctx.shell.show_message(TEXT_SENT, MESSAGE_MS)
        self.refresh()

    def _on_failed(self, text):
        if self._stopped:
            return
        if self.screen is not None:
            self.screen.set_busy(False)
            self.screen.show_error(text)

    def mark_done(self, comment_id):
        self._spawn(self._mark, comment_id, self._user_id())

    def _mark(self, comment_id, user_id):
        try:
            self.repo.mark_done(comment_id, user_id)
        except Exception as exc:
            log.warning("Не удалось отметить «Готово»: %s", exc)
        self._again = True
        self.signals.loaded.emit(None)  # перечитать: «занято» снимется само

    def _open_in_compare(self, item):
        compare = self.ctx.services.get_optional("compare")
        if compare is not None and item.folder_id is not None:
            compare.open_folder(item.folder_id)
