"""Окно «Виды замечаний»: список, поле, «Добавить», «Исправить», «Удалить». База — в фоне."""
from __future__ import annotations

import logging
import threading

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QVBoxLayout,
)

from atlas.features.defect_kinds.logic import KindError

log = logging.getLogger("atlas.defect_kinds")

TITLE = "Виды замечаний"
HINT = "Список общий для всех. Исправленный вид меняется и в уже поставленных замечаниях; удалённый — остаётся в старых."
TEXT_LOADING = "Загрузка…"
TEXT_FAILED = "Не удалось: {}"


class _Signals(QObject):
    done = pyqtSignal(object, object)  # список видов, текст итога
    failed = pyqtSignal(str)


class KindsDialog(QDialog):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle(TITLE)
        self.setMinimumWidth(460)
        self._signals = _Signals()
        self._signals.done.connect(self._on_done)
        self._signals.failed.connect(self._on_failed)
        self._threads = []
        layout = QVBoxLayout(self)
        hint = QLabel(HINT)
        hint.setWordWrap(True)
        hint.setProperty("role", "muted")
        layout.addWidget(hint)
        self.list = QListWidget()
        self.list.currentTextChanged.connect(self._on_selected)
        layout.addWidget(self.list, 1)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Название вида, например «Сбит элемент»")
        self.edit.textChanged.connect(lambda _=None: self._refresh())
        self.edit.returnPressed.connect(self.add)
        layout.addWidget(self.edit)
        row = QHBoxLayout()
        self.add_button = QPushButton("Добавить")
        self.add_button.clicked.connect(self.add)
        self.rename_button = QPushButton("Исправить")
        self.rename_button.clicked.connect(self.rename)
        self.remove_button = QPushButton("Удалить")
        self.remove_button.clicked.connect(self.remove)
        for button in (self.add_button, self.rename_button, self.remove_button):
            button.setAutoDefault(False)
            row.addWidget(button)
        row.addStretch(1)
        close = QPushButton("Закрыть")
        close.setAutoDefault(False)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)
        self.status = QLabel(TEXT_LOADING)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self._busy = False
        self._run(lambda: (self.service.names(), ""))

    # --- действия -------------------------------------------------------------
    def selected(self):
        item = self.list.currentItem()
        return item.text() if item is not None else None

    def add(self):
        name = self.edit.text()
        self._run(lambda: (self._after(self.service.add(name)), "Добавлено"))

    def rename(self):
        old, new = self.selected(), self.edit.text()
        if old is None:
            return

        def work():
            fixed = self.service.rename(old, new)
            return self.service.names(), "Исправлено. Замечаний с этим видом: {}".format(fixed)
        self._run(work)

    def remove(self):
        name = self.selected()
        if name is None or not self._confirm("Удалить вид «{}» из списка? В уже поставленных замечаниях он останется.".format(name)):
            return

        def work():
            self.service.remove(name)
            return self.service.names(), "Удалено"
        self._run(work)

    def _confirm(self, text):
        return QMessageBox.question(self, TITLE, text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def _after(self, _):
        return self.service.names()

    # --- фон -------------------------------------------------------------------
    def _run(self, work):
        self._busy = True
        self._refresh()
        self._threads = [thread for thread in self._threads if thread.is_alive()]
        thread = threading.Thread(target=self._work, args=(work,), daemon=True)
        self._threads.append(thread)
        thread.start()

    def _work(self, work):
        try:
            names, text = work()
        except KindError as exc:
            self._signals.failed.emit(str(exc))
        except Exception as exc:  # нет сети, база занята
            log.exception("Виды замечаний: не удалось")
            self._signals.failed.emit(TEXT_FAILED.format(exc))
        else:
            self._signals.done.emit(names, text)

    def _on_done(self, names, text):
        current = self.edit.text().strip()
        self.list.clear()
        self.list.addItems(names)
        matches = self.list.findItems(current, Qt.MatchExactly) if current else []
        if matches:
            self.list.setCurrentItem(matches[0])
        self.status.setProperty("role", "muted")
        self.status.setText(text)
        self._restyle()
        self._busy = False
        self._refresh()

    def _on_failed(self, text):
        self.status.setProperty("role", "warn")
        self.status.setText(text)
        self._restyle()
        self._busy = False
        self._refresh()

    def _restyle(self):
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _on_selected(self, text):
        if text:
            self.edit.setText(text)
        self._refresh()

    def _refresh(self):
        text = self.edit.text().strip()
        chosen = self.selected()
        self.add_button.setEnabled(not self._busy and bool(text))
        self.rename_button.setEnabled(not self._busy and chosen is not None and bool(text) and text != chosen)
        self.remove_button.setEnabled(not self._busy and chosen is not None)

    def wait_idle(self):
        """Для тестов и закрытия: дождаться фоновых записей."""
        for thread in self._threads:
            thread.join(5)
