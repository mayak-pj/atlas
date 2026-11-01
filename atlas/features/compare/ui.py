from __future__ import annotations

import json
import logging
import threading

from PyQt5.QtCore import QObject, pyqtSignal

from atlas.core.feature import Feature
from atlas.features.compare import logic
from atlas.features.compare.screen import CompareScreen

log = logging.getLogger("atlas.compare")

SLOT_LEFT = "compare.left"
SLOT_RIGHT = "compare.right"
SLOT_TOOLBAR = "compare.toolbar"
EVENT_FOLDER_OPENED = "folder.opened"
EVENT_PHOTO_CHANGED = "photo.changed"
STOP_WAIT_S = 2.0  # сеть могла пропасть: дольше не держим закрытие программы
TEXT_LOAD_FAILED = "Не удалось открыть папку"
TEXT_FOLDER_GONE = "Папка не найдена"


class _Signals(QObject):
    loaded = pyqtSignal(int, object)  # номер запроса, (папка, деталь, фото) или None
    failed = pyqtSignal(int)


class CompareFeature(Feature):
    """Сервис «compare»: open_folder(folder_id), set_reference(path), current_folder()."""

    def on_start(self):
        self.screen = None
        self.folder = None
        self._request = 0
        self._threads = []
        self.signals = _Signals()
        self.signals.loaded.connect(self._on_loaded)
        self.signals.failed.connect(self._on_failed)
        self.ctx.services.register("compare", self)

    def create_tab(self):
        cache = self.ctx.services.get("image_cache")
        self.screen = CompareScreen(cache, self._hotkeys())
        self.screen.photo_changed.connect(self._on_photo_changed)
        self.screen.first_shown.connect(self._open_latest)
        shell = self.ctx.shell
        if shell is not None:
            shell.register_slot(SLOT_LEFT, self.screen.left_layout)
            shell.register_slot(SLOT_RIGHT, self.screen.right_layout)
            shell.register_slot(SLOT_TOOLBAR, self.screen.toolbar_layout)
        return self.screen

    def on_stop(self):
        self._request += 1  # ответы запросов, которые ещё идут, больше никому не нужны
        self.ctx.services.unregister("compare")
        for thread in self._threads:
            thread.join(STOP_WAIT_S)

    def _hotkeys(self):
        path = self.ctx.paths.data / "hotkeys.json"
        try:
            keys = json.loads(path.read_text(encoding="utf-8-sig"))["compare"]
            return dict(logic.DEFAULT_HOTKEYS, **keys)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("Нет горячих клавиш в %s (%s), взяты стандартные", path, exc)
            return dict(logic.DEFAULT_HOTKEYS)

    # --- сервис ---------------------------------------------------------------
    def open_folder(self, folder_id):
        """Открыть папку в сравнении. Чтение базы — в фоне; из GUI-потока."""
        self._run(self._load, folder_id)

    def set_reference(self, path):
        """Показать в окне эталона это фото."""
        self.screen.set_reference(logic.PhotoItem(None, str(path)))

    def current_folder(self):
        """Folder или None."""
        return self.folder

    # --- чтение базы в фоне ---------------------------------------------------
    def _open_latest(self):
        """TODO(3.3): пока нет панели папок, открываем самую свежую непроверенную, иначе просто самую свежую."""
        if self.folder is None:
            self._run(self._load_latest)

    def _run(self, work, *args):
        self._request += 1
        self._threads = [thread for thread in self._threads if thread.is_alive()]
        thread = threading.Thread(target=self._work, args=(self._request, work) + args, daemon=True)
        self._threads.append(thread)
        thread.start()

    def _work(self, request, work, *args):
        try:
            result = work(*args)
        except Exception:  # нет сети, база занята: сообщаем на экране, программа работает дальше
            log.exception("Не удалось прочитать папку")
            self.signals.failed.emit(request)
            return
        self.signals.loaded.emit(request, result)

    def _load_latest(self):
        folders = self.ctx.services.get("folders")
        latest = folders.recent(1, status="new") or folders.recent(1)
        return self._read(latest[0]) if latest else None

    def _load(self, folder_id):
        folder = self.ctx.services.get("folders").get(folder_id)
        if folder is None:
            raise LookupError("{}: {}".format(TEXT_FOLDER_GONE, folder_id))
        return self._read(folder)

    def _read(self, folder):
        part = self.ctx.services.get("parts").get(folder.part_id)
        photos = [
            logic.PhotoItem(photo.id, logic.photo_path(folder.path, photo.rel_path), photo.mark)
            for photo in self.ctx.services.get("folders").photos(folder.id)
        ]
        return folder, part, photos

    # --- ответы ---------------------------------------------------------------
    def _on_failed(self, request):
        if request == self._request and self.screen is not None:
            self.screen.show_failure(TEXT_LOAD_FAILED)

    def _on_loaded(self, request, result):
        if request != self._request or self.screen is None or result is None:
            return  # пришёл ответ на устаревший запрос, или папок ещё нет
        folder, part, photos = result
        self.folder = folder
        self.screen.set_photos(photos)
        if self.ctx.shell is not None and part is not None:
            self.ctx.shell.set_context(part.kind, part.project, part.device, part.name, folder.path)
        self.ctx.bus.publish(EVENT_FOLDER_OPENED, {"folder_id": folder.id, "part_id": folder.part_id})

    def _on_photo_changed(self, photo, index):
        if self.folder is not None:
            self.ctx.bus.publish(EVENT_PHOTO_CHANGED, {"folder_id": self.folder.id, "photo_id": photo.id, "index": index})
