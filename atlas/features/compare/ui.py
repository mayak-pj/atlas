from __future__ import annotations

import json
import logging
import queue
import threading
from dataclasses import replace
from datetime import date

from PyQt5.QtCore import QObject, pyqtSignal

from atlas.core import ui_state
from atlas.core.domain.photo_names import load_pattern
from atlas.core.feature import Feature
from atlas.features.compare import logic
from atlas.features.compare.screen import CompareScreen

log = logging.getLogger("atlas.compare")

SLOT_LEFT = "compare.left"
SLOT_RIGHT = "compare.right"
SLOT_TOOLBAR = "compare.toolbar"
EVENT_FOLDER_OPENED = "folder.opened"
EVENT_PHOTO_CHANGED = "photo.changed"
EVENT_PHOTO_MARKED = "photo.marked"
SHELL_MESSAGE_MS = 15000
STOP_WAIT_S = 2.0  # сеть могла пропасть: дольше не держим закрытие программы
TEXT_LOAD_FAILED = "Не удалось открыть папку"
TEXT_FOLDER_GONE = "Папка не найдена"
TEXT_NOT_FOUND = "Такой же детали нет в других проверках"
TEXT_NOT_FOUND_NEIGHBORS = "Такой же детали нет ни в этом проекте, ни в соседних проектах"
TEXT_FIND_FAILED = "Не удалось найти такую же деталь"
TEXT_MARK_FAILED = "Отметка не сохранена: база недоступна, попробуйте ещё раз"
TEXT_ROTATION_FAILED = "Поворот не сохранён: при следующем открытии фото будет как раньше"


class _Signals(QObject):
    loaded = pyqtSignal(int, object)  # номер запроса, (папка, деталь, фото) или None
    failed = pyqtSignal(int)
    marked = pyqtSignal(object)  # MarkResult
    mark_failed = pyqtSignal(int)  # id фото
    rotation_failed = pyqtSignal()
    found = pyqtSignal(int, object)  # номер поиска, FindResult или None
    find_failed = pyqtSignal(int)


class FindResult:
    """Чужая папка для эталона. source: own — тот же проект, neighbor — соседний проект, given — задана вызывающим."""

    def __init__(self, source, folder, part, photos):
        self.source = source
        self.folder = folder
        self.part = part
        self.photos = photos


class MarkResult:
    def __init__(self, folder_id, photo_id, mark, sn, defect_kind, status):
        self.folder_id = folder_id
        self.photo_id = photo_id
        self.mark = mark
        self.sn = sn
        self.defect_kind = defect_kind
        self.status = status  # статус папки после отметки


class CompareFeature(Feature):
    """Сервис «compare»: open_folder(folder_id), set_reference(path), set_reference_folder(folder_id),
    find_same_part(), current_folder(), views(), active_view()."""

    def on_start(self):
        self.screen = None
        self.folder = None
        self._request = 0
        self._threads = []
        self.signals = _Signals()
        self.signals.loaded.connect(self._on_loaded)
        self.signals.failed.connect(self._on_failed)
        self.signals.marked.connect(self._on_marked)
        self.signals.mark_failed.connect(self._on_mark_failed)
        self.signals.rotation_failed.connect(self._on_rotation_failed)
        self.signals.found.connect(self._on_found)
        self.signals.find_failed.connect(self._on_find_failed)
        self._find_request = 0
        # Отметки и повороты пишутся одной очередью: два быстрых нажатия не должны прийти в базу в обратном порядке
        self._mark_queue = queue.Queue()
        self._mark_thread = threading.Thread(target=self._mark_loop, daemon=True)
        self._mark_thread.start()
        self.ctx.services.register("compare", self)

    def create_tab(self):
        cache = self.ctx.services.get("image_cache")
        data = self.ctx.paths.data
        self.screen = CompareScreen(cache, self._hotkeys(), load_pattern(data), logic.load_defect_kinds(data))
        self.screen.photo_changed.connect(self._on_photo_changed)
        self.screen.mark_requested.connect(self._on_mark_requested)
        self.screen.rotation_changed.connect(self._on_rotation_changed)
        self.screen.find_requested.connect(self.find_same_part)
        self.screen.restore_panels(ui_state.load(self.ctx.paths).get(logic.PANELS_KEY))
        self.screen.panels_changed.connect(self._save_panels)
        shell = self.ctx.shell
        if shell is not None:
            shell.register_slot(SLOT_LEFT, self.screen.left_layout)
            shell.register_slot(SLOT_RIGHT, self.screen.right_layout)
            shell.register_slot(SLOT_TOOLBAR, self.screen.toolbar_layout)
        return self.screen

    def on_stop(self):
        self._request += 1  # ответы запросов, которые ещё идут, больше никому не нужны
        self.ctx.services.unregister("compare")
        self._mark_queue.put(None)
        self._mark_thread.join(STOP_WAIT_S)
        for thread in self._threads:
            thread.join(STOP_WAIT_S)

    def _save_panels(self, state):
        """Выбор панелей — в var/ui_state.json: при следующем запуске панели те же."""
        ui_state.save(self.ctx.paths, logic.PANELS_KEY, state)

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

    def set_reference_folder(self, folder_id):
        """Показать в окне эталона фото этой папки (первое; дальше листаются). Чтение базы — в фоне; из GUI-потока."""
        self._find(lambda: self._given(folder_id))

    def find_same_part(self):
        """«Найти такую же деталь»: последняя проверка в своём проекте, иначе в соседних; открывается эталоном."""
        folder = self.folder
        if folder is None or self.screen is None:
            return
        self.screen.find_button.setEnabled(False)
        self._find(lambda: self._search(folder))

    def current_folder(self):
        """Folder или None."""
        return self.folder

    def views(self):
        """Все окна просмотра (PhotoView), в том числе скрытые; пусто, пока вкладка не создана."""
        return list(self.screen.views) if self.screen is not None else []

    def active_view(self):
        """Окно, в котором сейчас работает человек, или None."""
        return self.screen.active_view() if self.screen is not None else None

    # --- чтение базы в фоне ---------------------------------------------------
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

    def _load(self, folder_id):
        folder = self.ctx.services.get("folders").get(folder_id)
        if folder is None:
            raise LookupError("{}: {}".format(TEXT_FOLDER_GONE, folder_id))
        return self._read(folder)

    def _read(self, folder):
        part = self.ctx.services.get("parts").get(folder.part_id)
        photos = [
            logic.PhotoItem(
                photo.id, logic.photo_path(folder.path, photo.rel_path), photo.mark, photo.sn, photo.defect_kind,
                photo.rotation,
            )
            for photo in self.ctx.services.get("folders").photos(folder.id)
        ]
        return folder, part, photos

    # --- поиск такой же детали ------------------------------------------------
    def _find(self, work):
        self._find_request += 1
        request = self._find_request
        self._threads = [thread for thread in self._threads if thread.is_alive()]
        thread = threading.Thread(target=self._find_work, args=(request, work), daemon=True)
        self._threads.append(thread)
        thread.start()

    def _find_work(self, request, work):
        try:
            result = work()
        except Exception:  # нет сети, база занята
            log.exception("Не удалось найти такую же деталь")
            self.signals.find_failed.emit(request)
            return
        self.signals.found.emit(request, result)

    def _neighbor_since(self):
        config = self.ctx.config
        return logic.neighbor_since(
            date.today(),
            bool(config.get("compare.neighbor_search_year_only", True)),
            int(config.get("compare.neighbor_search_days", 0) or 0),
        )

    def _search(self, folder):
        """Не в GUI-потоке. Сначала свой проект, потом проекты того же вида за выбранный срок."""
        services = self.ctx.services
        folders = services.get("folders")
        part = services.get("parts").get(folder.part_id)
        if part is None:
            return None
        found = folders.latest_for_part(part.name, project_id=part.project_id, exclude_folder_id=folder.id)
        source = "own"
        if found is None:
            found = folders.latest_for_part(
                part.name, kind=part.kind, exclude_project_id=part.project_id, since=self._neighbor_since()
            )
            source = "neighbor"
        return self._result(source, found) if found is not None else None

    def _given(self, folder_id):
        folder = self.ctx.services.get("folders").get(folder_id)
        if folder is None:
            raise LookupError("{}: {}".format(TEXT_FOLDER_GONE, folder_id))
        return self._result("given", folder)

    def _result(self, source, folder):
        _folder, part, photos = self._read(folder)
        return FindResult(source, folder, part, photos)

    def _on_found(self, request, result):
        if request != self._find_request or self.screen is None:
            return
        self.screen.find_button.setEnabled(self.folder is not None)
        shell = self.ctx.shell
        if result is None:
            if shell is not None:
                shell.show_message(TEXT_NOT_FOUND_NEIGHBORS, SHELL_MESSAGE_MS)
            return
        if not result.photos:
            if shell is not None:
                shell.show_message(TEXT_NOT_FOUND, SHELL_MESSAGE_MS)
            return
        part = result.part
        where = "{}, {}".format(part.project if part else "?", result.folder.folder_date)
        other = result.source == "neighbor"
        note = where
        if other:
            warning = "В проекте нет такой детали, взята из проекта {}".format(where)
            note = warning[0].lower() + warning[1:]
            if shell is not None:
                shell.show_message(warning, SHELL_MESSAGE_MS)
        self.screen.set_reference_folder(result.photos, note, other)

    def _on_find_failed(self, request):
        if request != self._find_request or self.screen is None:
            return
        self.screen.find_button.setEnabled(self.folder is not None)
        if self.ctx.shell is not None:
            self.ctx.shell.show_message(TEXT_FIND_FAILED, SHELL_MESSAGE_MS)

    # --- ответы ---------------------------------------------------------------
    def _on_failed(self, request):
        if request == self._request and self.screen is not None:
            self.screen.show_failure(TEXT_LOAD_FAILED)

    def _on_loaded(self, request, result):
        if request != self._request or self.screen is None or result is None:
            return  # пришёл ответ на устаревший запрос, или папок ещё нет
        folder, part, photos = result
        self.folder = folder
        self._find_request += 1  # найденная для прежней папки деталь больше не нужна
        self.screen.set_photos(photos)
        if self.ctx.shell is not None and part is not None:
            self.ctx.shell.set_context(part.kind, part.project, part.device, part.name, folder.path)
        self.ctx.bus.publish(EVENT_FOLDER_OPENED, {"folder_id": folder.id, "part_id": folder.part_id})

    def _on_photo_changed(self, photo, index):
        if self.folder is not None:
            self.ctx.bus.publish(EVENT_PHOTO_CHANGED, {"folder_id": self.folder.id, "photo_id": photo.id, "index": index})

    # --- отметки --------------------------------------------------------------
    def _on_mark_requested(self, photo, mark, sn, defect_kind):
        if self.folder is None:
            return
        user = self.ctx.user
        job = (self.folder, photo.id, mark, sn, defect_kind, user.id if user else None)
        self._mark_queue.put(lambda: self._mark_job(job))

    def _on_rotation_changed(self, photo_ids, rotation):
        self._mark_queue.put(lambda: self._rotation_job(photo_ids, rotation))

    def _mark_loop(self):
        while True:
            job = self._mark_queue.get()
            if job is None:
                return
            job()

    def _mark_job(self, job):
        photo_id = job[1]
        try:
            self.signals.marked.emit(self._write_mark(*job))
        except Exception:  # нет сети, база занята: сообщаем на экране, отметка не меняется
            log.exception("Не удалось сохранить отметку фото %s", photo_id)
            self.signals.mark_failed.emit(photo_id)

    def _rotation_job(self, photo_ids, rotation):
        try:
            self.ctx.services.get("folders").set_rotation(photo_ids, rotation)
        except Exception:  # на экране поворот уже виден и работает, не сохранился только на будущее
            log.exception("Не удалось сохранить поворот фото %s", photo_ids)
            self.signals.rotation_failed.emit()

    def _write_mark(self, folder, photo_id, mark, sn, defect_kind, user_id):
        folders = self.ctx.services.get("folders")
        folders.mark_photo(photo_id, mark, sn, user_id, defect_kind)
        status = folders.get(folder.id).status
        if mark and status == "new":  # первая отметка: папка в работе (панель папок и коллеги это видят)
            folders.set_status(folder.id, "in_work", user_id)
            status = "in_work"
        return MarkResult(folder.id, photo_id, mark, sn, defect_kind, status)

    def _on_marked(self, result):
        if self.screen is None:
            return
        self.screen.apply_mark(result.photo_id, result.mark, result.sn, result.defect_kind)
        if self.folder is not None and self.folder.id == result.folder_id and self.folder.status != result.status:
            self.folder = replace(self.folder, status=result.status)
        self.ctx.bus.publish(EVENT_PHOTO_MARKED, {"photo_id": result.photo_id, "mark": result.mark, "sn": result.sn})

    def _on_mark_failed(self, photo_id):
        if self.screen is not None:
            self.screen.show_mark_failure(TEXT_MARK_FAILED)

    def _on_rotation_failed(self):
        if self.screen is not None:
            self.screen.show_mark_failure(TEXT_ROTATION_FAILED)
