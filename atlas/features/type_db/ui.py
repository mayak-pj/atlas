from __future__ import annotations

import logging
import threading
from pathlib import Path

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import QPushButton

from atlas.core import theme
from atlas.core.domain.photo_names import load_pattern, parse_photo_name
from atlas.core.feature import Feature
from atlas.features.type_db import logic, render
from atlas.features.type_db.dialog import CardDialog
from atlas.features.type_db.repo import Repo
from atlas.features.type_db.screen import TypeDbScreen
from atlas.features.type_db.store import SaveRequest, StoreError, TypeStore

log = logging.getLogger("atlas.type_db")

SLOT_TOOLBAR = "compare.toolbar"
PANEL_KEY = "type_db"
EVENT_TYPE_ADDED = "type.added"
EVENT_TYPE_ARCHIVED = "type.archived"
EVENT_TYPE_RESTORED = "type.restored"
MESSAGE_MS = 15000
STOP_WAIT_S = 5.0  # запись картинок на сетевой диск; дольше закрытие программы не держим
DEFAULT_DIR = "var/type_db"  # TODO(OPEN_ITEMS №12): настоящая папка на сетевом диске
TEXT_BUTTON = "+ В базу типов"
TEXT_TIP = "Сохранить это фото с обводкой и подписями (и вырезку, если она выделена) в базу типов"
TEXT_NO_COMPARE = "Сравнение выключено: фото взять негде"
TEXT_NO_PHOTO = "Откройте фото: оно ещё не показано"
TEXT_FOREIGN = "Это фото из другой папки: откройте его папку и добавьте из неё"
TEXT_BUSY = "Предыдущая карточка ещё сохраняется"
TEXT_FAILED = "Не удалось подготовить карточку: база недоступна"
TEXT_SAVED = "Добавлено в базу типов: {}"
TEXT_ARCHIVE_FAILED = "Не удалось изменить архив: база недоступна, попробуйте ещё раз"
TEXT_ARCHIVED = "В архиве: {}"
TEXT_RESTORED = "Возвращено из архива: {}"


class _Signals(QObject):
    loaded = pyqtSignal(object)  # [Entry] или None, если база недоступна
    archived = pyqtSignal(int, bool, object, int)  # запись, в архиве ли, время из базы, деталь
    archive_failed = pyqtSignal(int)
    prepared = pyqtSignal(object)  # _Draft
    saved = pyqtSignal(int, object, object)  # id записи, Part, CardData
    failed = pyqtSignal(str)


class _Draft:
    """Всё, что известно к моменту открытия окна карточки."""

    def __init__(self, part, number, request_base):
        self.part = part
        self.number = number
        self.base = request_base  # (путь фото, поворот, фигуры, SN)


class TypeDbFeature(Feature):
    """Кнопка «+ В базу типов» (4.2), вкладка «База типов» с поиском (4.3).

    Сервис «type_db» (из любого потока, кроме GUI: ходит в базу): `types_for_part(part_id, include_archived=False)` →
    [TypeRecord] (архивные не отдаёт: архив эталоном не служит), `search(query="", include_archived=True)` → [Entry] в порядке
    выдачи: живые, потом архив; новые первыми, `archive(type_id)` / `restore(type_id)` → (part_id, время) или None.
    """

    def on_start(self):
        self.busy = False
        self.screen = None
        self._stopped = False
        self._reader = None
        self._reload_again = False
        self._threads = []
        self.signals = _Signals()
        self.signals.loaded.connect(self._on_loaded)
        self.signals.archived.connect(self._on_archived)
        self.signals.archive_failed.connect(self._on_archive_failed)
        self.signals.prepared.connect(self._on_prepared)
        self.signals.saved.connect(self._on_saved)
        self.signals.failed.connect(self._on_failed)
        data = self.ctx.paths.data
        self._pattern = load_pattern(data)
        self.repo = Repo(self.ctx.db)
        config = self.ctx.config
        root = self.ctx.paths.resolve(config.get("type_db.dir", DEFAULT_DIR))
        tokens = theme.current()
        colors = {"defect": tokens.qcolor("defect"), "outline": tokens.qcolor("bg"), "crop": tokens.qcolor("text"), "dim": tokens.qcolor("bg")}
        self.store = TypeStore(
            self.repo, root, colors,
            max_side=int(config.get("type_db.max_side", render.DEFAULT_MAX_SIDE)),
            quality=int(config.get("type_db.jpeg_quality", render.JPEG_QUALITY)),
            create_root=not Path(str(config.get("type_db.dir", DEFAULT_DIR))).is_absolute(),
        )
        self.add_button = QPushButton(TEXT_BUTTON)
        self.add_button.setFocusPolicy(Qt.NoFocus)  # стрелки и пробел принадлежат экрану сравнения
        self.add_button.setToolTip(TEXT_TIP)
        self.add_button.clicked.connect(lambda _=False: self.start())
        self._root = root
        if self.ctx.shell is not None:
            self.ctx.shell.add_panel(SLOT_TOOLBAR, self.add_button, key=PANEL_KEY, order=10)
        self._unsubscribe = [self.ctx.bus.subscribe(EVENT_TYPE_ADDED, lambda _payload: self.refresh())]
        self.ctx.services.register("type_db", self)

    def create_tab(self):
        cache = self.ctx.services.get("image_cache")
        kinds = self.ctx.services.get("parts").kinds
        self.screen = TypeDbScreen(cache, self._root, kinds, animations=bool(self.ctx.config.get("ui.animations", True)))
        self.screen.shown.connect(self.refresh)
        self.screen.archive_toggled.connect(self._on_archive_toggled)
        self.refresh()
        return self.screen

    def on_stop(self):
        self._stopped = True
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self.ctx.services.unregister("type_db")
        if self._reader is not None:
            self._reader.join(STOP_WAIT_S)
        for thread in self._threads:
            thread.join(STOP_WAIT_S)

    # --- сервис -----------------------------------------------------------------
    def types_for_part(self, part_id, include_archived=False):
        return self.repo.for_part(part_id, include_archived)

    def search(self, query="", include_archived=True):
        found = logic.select(self._read(), query)
        return found if include_archived else [item for item in found if not item.archived]

    def archive(self, type_id):
        """В архив: запись остаётся, но внизу выдачи и эталоном не служит. Не из GUI-потока."""
        return self.repo.set_archived(type_id, True, self._user_id())

    def restore(self, type_id):
        return self.repo.set_archived(type_id, False, self._user_id())

    # --- архив с экрана ---------------------------------------------------------
    def _on_archive_toggled(self, type_id, archived):
        self._run_archive(type_id, archived)

    def _run_archive(self, type_id, archived):
        self._threads = [thread for thread in self._threads if thread.is_alive()]
        thread = threading.Thread(target=self._archive_work, args=(type_id, archived), daemon=True)
        self._threads.append(thread)
        thread.start()

    def _archive_work(self, type_id, archived):
        try:
            result = self.archive(type_id) if archived else self.restore(type_id)
        except Exception:  # база занята, обрыв сети
            log.exception("Архив не изменён")
            result = None
        if result is None:
            self.signals.archive_failed.emit(type_id)
        else:
            self.signals.archived.emit(type_id, archived, result[1], result[0])

    def _on_archived(self, type_id, archived, stamp, part_id):
        if self.screen is not None:
            self.screen.apply_archive(type_id, archived, stamp)
        self.ctx.bus.publish(EVENT_TYPE_ARCHIVED if archived else EVENT_TYPE_RESTORED, {"type_id": type_id, "part_id": part_id})
        self.refresh()

    def _on_archive_failed(self, type_id):
        if self.screen is not None:
            self.screen.archive_failed(type_id)
        self._say(TEXT_ARCHIVE_FAILED)

    def _user_id(self):
        user = self.ctx.user
        return user.id if user is not None else None

    # --- чтение для вкладки: в фоне, по одному запросу ------------------------------
    def refresh(self):
        if self._stopped or self.screen is None:
            return
        if self._reader is not None:
            self._reload_again = True
            return
        self._reader = threading.Thread(target=self._read_for_screen, daemon=True)
        self._reader.start()

    def _read_for_screen(self):
        try:
            entries = self._read()
        except Exception as exc:  # нет сети, база занята: остаётся прежний список
            log.warning("Не удалось прочитать базу типов: %s", exc)
            entries = None
        self.signals.loaded.emit(entries)

    def _read(self):
        services = self.ctx.services
        parts = services.get("parts")
        names = {user.id: user.name for user, _ in services.get("users").all()}
        known = {}
        entries = []
        for record in self.repo.all():
            if record.part_id not in known:
                known[record.part_id] = parts.get(record.part_id)
            part = known[record.part_id]
            if part is not None:
                entries.append(logic.entry_of(record, part, names.get(record.created_by)))
        return entries

    def _on_loaded(self, entries):
        self._reader = None
        if self._stopped or self.screen is None:
            return
        if entries is None:
            self.screen.show_failure()
        else:
            self.screen.set_entries(entries)
        if self._reload_again:
            self._reload_again = False
            self.refresh()

    # --- нажатие кнопки ---------------------------------------------------------
    def start(self):
        """Снимок окна и папки, затем — в фоне — деталь и следующий номер, потом окно карточки."""
        if self.busy:
            self._say(TEXT_BUSY)
            return
        compare = self.ctx.services.get_optional("compare")
        view = compare.active_view() if compare is not None else None
        folder = compare.current_folder() if compare is not None else None
        if compare is None:
            self._say(TEXT_NO_COMPARE)
            return
        if view is None or view.path is None or not view.is_current_shown or folder is None:
            self._say(TEXT_NO_PHOTO)
            return
        if not logic.under_folder(view.path, folder.path):
            self._say(TEXT_FOREIGN)
            return
        annotations = self.ctx.services.get_optional("annotations")
        shapes = tuple(annotations.shapes(view.path)) if annotations is not None else ()
        parsed = parse_photo_name(Path(str(view.path).replace("\\", "/")).name, self._pattern)
        base = (str(view.path), view.rotation, shapes, parsed.sn if parsed is not None else None)
        photo = compare.active_photo() if hasattr(compare, "active_photo") else None
        mark = photo.mark if photo is not None and str(photo.path) == str(view.path) else None
        self.busy = True
        self._run(self._prepare, folder.part_id, base, mark)

    def _prepare(self, part_id, base, mark=None):
        part = self.ctx.services.get("parts").get(part_id)
        number = logic.default_type_no(self.repo.numbers(part_id), mark)
        self.signals.prepared.emit(_Draft(part, number, base))

    def _on_prepared(self, draft):
        card = self.ask_card(draft)
        if card is None:
            self.busy = False
            return
        path, rotation, shapes, sn = draft.base
        request = SaveRequest(draft.part, card, path, rotation, shapes, sn, self._user_id())
        self._run(self._save, request)

    def ask_card(self, draft):
        """Окно карточки → CardData или None (отмена). Подменяется в тестах."""
        part = draft.part
        path, _rotation, shapes, _sn = draft.base
        crops = sum(1 for shape in shapes if type(shape).__name__ == "Crop")
        notes = len(shapes) - crops
        summary = "Сохранится фото с обводками и подписями ({}); вырезка: {}".format(notes, "есть" if crops else "нет")
        text = " › ".join((part.kind, part.project, part.device, part.name))
        parent = self.ctx.shell if self.ctx.shell is not None else None
        dialog = CardDialog(text, draft.number, part.article, summary, parent)
        return dialog.card() if dialog.exec_() == dialog.Accepted else None

    def _save(self, request):
        record_id = self.store.save(request)
        self.signals.saved.emit(record_id, request.part, request.card)

    def _on_saved(self, record_id, part, card):
        self.busy = False
        self.ctx.bus.publish(EVENT_TYPE_ADDED, {"type_id": record_id, "part_id": part.id})
        self._say(TEXT_SAVED.format("{}, {}".format(part.name, logic.label(card.kind, card.type_no))))

    def _on_failed(self, text):
        self.busy = False
        self._say(text)

    # --- фон --------------------------------------------------------------------
    def _run(self, work, *args):
        self._threads = [thread for thread in self._threads if thread.is_alive()]
        thread = threading.Thread(target=self._guard, args=(work,) + args, daemon=True)
        self._threads.append(thread)
        thread.start()

    def _guard(self, work, *args):
        try:
            work(*args)
        except StoreError as exc:
            self.signals.failed.emit(str(exc))
        except Exception:  # база занята, обрыв сети: программа работает дальше
            log.exception("Карточка «В базу» не сохранена")
            self.signals.failed.emit(TEXT_FAILED)

    def _say(self, text):
        if self.ctx.shell is not None:
            self.ctx.shell.show_message(text, MESSAGE_MS)
