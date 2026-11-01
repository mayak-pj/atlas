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
from atlas.features.type_db.store import SaveRequest, StoreError, TypeStore

log = logging.getLogger("atlas.type_db")

SLOT_TOOLBAR = "compare.toolbar"
PANEL_KEY = "type_db"
EVENT_TYPE_ADDED = "type.added"
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


class _Signals(QObject):
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
    """Сейчас только кнопка «+ В базу типов» и запись карточки; вкладка и поиск — шаг 4.3."""

    def on_start(self):
        self.busy = False
        self._threads = []
        self.signals = _Signals()
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
        if self.ctx.shell is not None:
            self.ctx.shell.add_panel(SLOT_TOOLBAR, self.add_button, key=PANEL_KEY, order=10)

    def on_stop(self):
        for thread in self._threads:
            thread.join(STOP_WAIT_S)

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
        self.busy = True
        self._run(self._prepare, folder.part_id, base)

    def _prepare(self, part_id, base):
        part = self.ctx.services.get("parts").get(part_id)
        number = logic.default_type_no(self.repo.numbers(part_id))
        self.signals.prepared.emit(_Draft(part, number, base))

    def _on_prepared(self, draft):
        card = self.ask_card(draft)
        if card is None:
            self.busy = False
            return
        path, rotation, shapes, sn = draft.base
        user = self.ctx.user
        request = SaveRequest(draft.part, card, path, rotation, shapes, sn, user.id if user is not None else None)
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
