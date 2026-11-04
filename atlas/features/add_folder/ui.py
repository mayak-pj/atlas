from __future__ import annotations

import logging
import threading

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import QPushButton

from atlas.core.feature import Feature
from atlas.features.add_folder import logic
from atlas.features.add_folder.dialog import AddFolderDialog
from atlas.shared.widgets.icons import set_icon

log = logging.getLogger("atlas.add_folder")

SLOT_LEFT = "compare.left"
PANEL_KEY = "add_folder"
EVENT_FOLDER_COPIED = "folder.copied"
STOP_WAIT_S = 2.0  # сеть могла пропасть: дольше не держим закрытие программы
MESSAGE_MS = 10000
TEXT_BUTTON = "Добавить папку…"
TEXT_TIP = "Внести папку с фото в базу, не копируя её. Позже это будет делать импорт из письма."
TEXT_FAILED = "Не удалось добавить папку: {}"
TEXT_ADDED = "Папка добавлена: фото {}"
TEXT_EXISTING = "Эта папка уже была в базе: фото {}, новых {}"


class _Signals(QObject):
    prepared = pyqtSignal(object)  # уже внесённые детали (для подсказок)
    saved = pyqtSignal(object, int, int)  # Folder, добавлено фото, всего фото
    failed = pyqtSignal(str)


class AddFolderFeature(Feature):
    """Кнопка в `compare.left`. Работает только через сервисы ядра `parts` и `folders`; `compare` необязателен."""

    def on_start(self):
        self.busy = False
        self._stopped = False
        self._threads = []
        self.signals = _Signals()
        self.signals.prepared.connect(self._on_prepared)
        self.signals.saved.connect(self._on_saved)
        self.signals.failed.connect(self._on_failed)
        self._no_device = logic.load_no_device(self.ctx.paths.data)
        self._tails = logic.load_part_tails(self.ctx.paths.data)
        self.button = QPushButton(TEXT_BUTTON)
        self.button.setFocusPolicy(Qt.NoFocus)  # стрелки и пробел принадлежат экрану сравнения
        set_icon(self.button, "folder-plus")
        self.button.setToolTip(TEXT_TIP)
        self.button.clicked.connect(lambda _=False: self.start())
        if self.ctx.shell is not None:
            self.ctx.shell.add_panel(SLOT_LEFT, self.button, key=PANEL_KEY, order=-10)  # над панелью папок

    def on_stop(self):
        self._stopped = True
        for thread in self._threads:
            thread.join(STOP_WAIT_S)

    # --- действие ---------------------------------------------------------------
    def start(self):
        """Нажата кнопка: прочитать известные детали (в фоне), потом спросить папку."""
        if self.busy or self._stopped:
            return
        self._set_busy(True)
        self._spawn(self._read_parts)

    def ask_folder(self, parts):
        """Окно выбора; FolderData или None. В тестах подменяется."""
        dialog = AddFolderDialog(self.ctx.services.get("parts").kinds, parts, self._no_device, parent=self.button.window(),
                                 tails=self._tails)
        if dialog.exec_() != dialog.Accepted:
            return None
        return dialog.data()

    def _read_parts(self):
        try:
            parts = self.ctx.services.get("parts").all()
        except Exception as exc:  # нет сети: подсказок не будет, но папку добавить можно
            log.warning("Не удалось прочитать детали для подсказок: %s", exc)
            parts = []
        self.signals.prepared.emit(parts)

    def _on_prepared(self, parts):
        if self._stopped:
            return
        data = self.ask_folder(parts)
        if data is None:
            self._set_busy(False)
            return
        self._spawn(self._register, data)

    def _register(self, data):
        try:
            services = self.ctx.services
            part = services.get("parts").ensure(data.kind, data.project, data.device, data.part)
            user = self.ctx.user.id if self.ctx.user is not None else None
            folders = services.get("folders")
            folder = folders.add(part.id, data.path, data.date, user)
            added = folders.add_photos(folder.id, data.photos)
        except Exception as exc:  # причина нужна человеку, а не только журналу
            log.exception("Не удалось добавить папку")
            self.signals.failed.emit(str(exc))
            return
        self.signals.saved.emit(folder, added, len(data.photos))

    def _on_saved(self, folder, added, total):
        self._set_busy(False)
        if self._stopped:
            return
        self.ctx.bus.publish(EVENT_FOLDER_COPIED, {"folder_id": folder.id, "part_id": folder.part_id})
        text = TEXT_ADDED.format(total) if added else TEXT_EXISTING.format(total, added)
        if self.ctx.shell is not None:
            self.ctx.shell.show_message(text, MESSAGE_MS)
        compare = self.ctx.services.get_optional("compare")
        if compare is not None:
            compare.open_folder(folder.id)

    def _on_failed(self, text):
        self._set_busy(False)
        if self.ctx.shell is not None and not self._stopped:
            self.ctx.shell.show_message(TEXT_FAILED.format(text), MESSAGE_MS)

    def _set_busy(self, busy):
        self.busy = busy
        self.button.setEnabled(not busy)

    def _spawn(self, target, *args):
        thread = threading.Thread(target=target, args=args, daemon=True)
        self._threads.append(thread)
        thread.start()
