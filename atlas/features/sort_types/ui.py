from __future__ import annotations

import logging
import threading

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QMessageBox, QPushButton, QWidget

from atlas.core.feature import Feature
from atlas.features.sort_types import logic
from atlas.features.sort_types.ops import Sorter
from atlas.features.sort_types.repo import Repo

log = logging.getLogger("atlas.sort_types")

SLOT_TOOLBAR = "compare.toolbar"
PANEL_KEY = "sort_types"
EVENT_FOLDER_OPENED = "folder.opened"
EVENT_FOLDER_SORTED = "folder.sorted"
STOP_WAIT_S = 2.0
TEXT_SORT = "Разложить по типам"
TEXT_UNDO = "Отменить раскладку"
TEXT_NOTHING = "Раскладывать нечего: нет фото с отметкой «Тип N» вне своей подпапки"
TEXT_FAILED = "Не удалось выполнить действие: папка или база недоступны"
TEXT_NO_UNDO_LOG = " Отмена этой раскладки недоступна: журнал не записан."
TITLE = "Раскладка по типам"


class _Signals(QObject):
    planned = pyqtSignal(int, object)  # папка, Plan
    finished = pyqtSignal(int, str, object)  # папка, "sort" | "undo", Result
    state = pyqtSignal(int, bool)  # папка, можно ли отменить
    failed = pyqtSignal()


class SortTypesFeature(Feature):
    def on_start(self):
        self.folder_id = None
        self.busy = False
        self._threads = []
        self.signals = _Signals()
        self.signals.planned.connect(self._on_planned)
        self.signals.finished.connect(self._on_finished)
        self.signals.state.connect(self._on_state)
        self.signals.failed.connect(self._on_failed)
        data = self.ctx.paths.data
        self.sorter = Sorter(self.ctx.services.get("folders"), Repo(self.ctx.db), logic.load_template(data))
        self.widget = QWidget()
        row = QHBoxLayout(self.widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.sort_button = self._button(TEXT_SORT, self._start_sort)
        self.undo_button = self._button(TEXT_UNDO, self._start_undo)
        row.addWidget(self.sort_button)
        row.addWidget(self.undo_button)
        self._unsubscribe = [self.ctx.bus.subscribe(EVENT_FOLDER_OPENED, self._on_opened)]
        if self.ctx.shell is not None:
            self.ctx.shell.add_panel(SLOT_TOOLBAR, self.widget, key=PANEL_KEY)
        compare = self.ctx.services.get_optional("compare")
        folder = compare.current_folder() if compare is not None else None
        self._set_folder(folder.id if folder is not None else None)

    def on_stop(self):
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        for thread in self._threads:
            thread.join(STOP_WAIT_S)

    def _button(self, text, action):
        button = QPushButton(text)
        button.setFocusPolicy(Qt.NoFocus)  # стрелки и пробел принадлежат экрану сравнения
        button.clicked.connect(lambda _=False: action())
        return button

    # --- состояние ------------------------------------------------------------
    def _on_opened(self, payload):
        self._set_folder(payload["folder_id"])

    def _set_folder(self, folder_id):
        self.folder_id = folder_id
        self.undo_button.setEnabled(False)  # узнаем из журнала
        self._refresh_buttons()
        if folder_id is not None:
            self._run(self._read_state, folder_id)

    def _refresh_buttons(self):
        self.sort_button.setEnabled(self.folder_id is not None and not self.busy)
        if self.busy:
            self.undo_button.setEnabled(False)

    def _on_state(self, folder_id, can_undo):
        if folder_id == self.folder_id:
            self.undo_button.setEnabled(can_undo and not self.busy)

    # --- фон ------------------------------------------------------------------
    def _run(self, work, *args):
        self._threads = [thread for thread in self._threads if thread.is_alive()]
        thread = threading.Thread(target=self._guard, args=(work,) + args, daemon=True)
        self._threads.append(thread)
        thread.start()

    def _guard(self, work, *args):
        try:
            work(*args)
        except Exception:  # нет сети, база занята, файл открыт: сообщаем, программа работает дальше
            log.exception("Раскладка по типам не удалась")
            self.signals.failed.emit()

    def _read_state(self, folder_id):
        self.signals.state.emit(folder_id, self.sorter.can_undo(folder_id))

    def _build_plan(self, folder_id):
        self.signals.planned.emit(folder_id, self.sorter.plan(folder_id))

    def _do_sort(self, folder_id, plan):
        result = self.sorter.apply(folder_id, plan, self._user_id())
        self.signals.finished.emit(folder_id, "sort", result)

    def _do_undo(self, folder_id):
        self.signals.finished.emit(folder_id, "undo", self.sorter.undo(folder_id))

    def _user_id(self):
        user = self.ctx.user
        return user.id if user is not None else None

    # --- действия -------------------------------------------------------------
    def _start_sort(self):
        if self.busy or self.folder_id is None:
            return
        self._set_busy(True)
        self._run(self._build_plan, self.folder_id)

    def _start_undo(self):
        if self.busy or self.folder_id is None:
            return
        if not self._ask("Вернуть фото последней раскладки на прежние места?"):
            return
        self._set_busy(True)
        self._run(self._do_undo, self.folder_id)

    def _on_planned(self, folder_id, plan):
        if folder_id != self.folder_id:  # папку сменили, пока строился план
            self._set_busy(False)
            return
        if not plan.moves:
            self._set_busy(False)
            self._say(TEXT_NOTHING)
            return
        if not self._ask(logic.confirm_text(plan)):
            self._set_busy(False)
            return
        self._run(self._do_sort, folder_id, plan)

    def _on_finished(self, folder_id, kind, result):
        self._set_busy(False)
        text = "Перемещено фото: {}".format(result.moved) if kind == "sort" else "Возвращено фото: {}".format(result.moved)
        if result.failed:
            text += ". Не удалось: {} (например, {}: {})".format(len(result.failed), *result.failed[0])
        if result.skipped:
            text += ". Изменены позже и не тронуты: {}".format(result.skipped)
        if not result.journal_ok:
            text += "." + TEXT_NO_UNDO_LOG
        self._say(text)
        if result.moved:
            self.ctx.bus.publish(EVENT_FOLDER_SORTED, {"folder_id": folder_id, "moved": result.moved, "kind": kind})
            compare = self.ctx.services.get_optional("compare")
            if compare is not None and folder_id == self.folder_id:
                compare.open_folder(folder_id)  # пути фото сменились: читаем папку заново
        self._run(self._read_state, folder_id)

    def _on_failed(self):
        self._set_busy(False)
        self._say(TEXT_FAILED)

    def _set_busy(self, busy):
        self.busy = busy
        self._refresh_buttons()

    def _say(self, text):
        if self.ctx.shell is not None:
            self.ctx.shell.show_message(text, 15000)

    def _ask(self, text):
        """Подтверждение. Отдельный метод, чтобы тесты подменяли диалог."""
        box = QMessageBox(QMessageBox.Question, TITLE, text, QMessageBox.NoButton, self.widget.window())
        yes = box.addButton("Да", QMessageBox.YesRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.exec_()
        return box.clickedButton() is yes
