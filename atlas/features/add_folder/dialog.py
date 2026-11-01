"""Окно «Добавить папку»: путь (можно вставить), вид, проект, устройство, деталь, дата. Фото ищутся в фоне."""
from __future__ import annotations

import threading

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout,
)

from atlas.features.add_folder import logic
from atlas.shared.fs.photos import photo_paths

TITLE = "Добавить папку"
TEXT_ADD = "Добавить"
TEXT_CANCEL = "Отмена"
TEXT_BROWSE = "Обзор…"
TEXT_PICK = "Папка с фото"
TEXT_PATH_PLACEHOLDER = "Вставьте путь, например R:\\Проект\\Деталь\\31.10, или нажмите «Обзор…»"
TEXT_HINT = "Папка только читается: ничего не копируется и не меняется."
TEXT_SCANNING = "Ищу фото…"
TEXT_NO_PATH = "Укажите папку с фото"


class _Signals(QObject):
    scanned = pyqtSignal(int, object, str)  # номер запроса, список фото или None, текст ошибки


def scan_folder(path):
    """(список фото, ошибка). Не из GUI-потока."""
    from pathlib import Path

    try:
        folder = Path(path)
        if not folder.is_dir():
            return None, "Нет такой папки (или она недоступна): {}".format(path)
        return photo_paths(folder), ""
    except OSError as exc:
        return None, "Не удалось прочитать папку: {}".format(exc)


class AddFolderDialog(QDialog):
    def __init__(self, kinds, parts=(), no_device=logic.DEFAULT_NO_DEVICE, today=None, scan=scan_folder, parent=None):
        """kinds — виды проектов; parts — уже внесённые детали (подсказки в списках); scan(путь) → (фото, ошибка)."""
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.setModal(True)
        self.setMinimumWidth(560)
        self._kinds = tuple(kinds)
        self._no_device = no_device
        self._today = today
        self._scan = scan
        self._options = logic.known_options(parts)
        self._touched = set()  # поля, куда человек уже писал сам: подсказка по пути их не трогает
        self._request = 0
        self._photos = None  # фото того пути, который сейчас в поле; None — ещё не найдены
        self._scanned_path = None
        self._error = ""
        self._signals = _Signals()
        self._signals.scanned.connect(self._on_scanned)

        self.path = QLineEdit()
        self.path.setPlaceholderText(TEXT_PATH_PLACEHOLDER)
        self.browse_button = QPushButton(TEXT_BROWSE)
        self.browse_button.setFocusPolicy(Qt.NoFocus)
        row = QHBoxLayout()
        row.addWidget(self.path, 1)
        row.addWidget(self.browse_button)
        self.kind = QComboBox()
        for kind in self._kinds:
            self.kind.addItem(str(kind), kind)
        self.project = QComboBox()
        self.project.setEditable(True)
        self.device = QComboBox()
        self.device.setEditable(True)
        self.part = QLineEdit()
        self.date = QLineEdit(logic.today_text() if today is None else today.isoformat())
        self.date.setPlaceholderText("ГГГГ-ММ-ДД")
        self.status = QLabel(TEXT_NO_PATH)
        self.status.setProperty("role", "muted")
        self.status.setWordWrap(True)
        hint = QLabel(TEXT_HINT)
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Папка", row)
        form.addRow("Вид проекта", self.kind)
        form.addRow("Проект", self.project)
        form.addRow("Устройство", self.device)
        form.addRow("Деталь", self.part)
        form.addRow("Дата папки", self.date)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.add_button = buttons.button(QDialogButtonBox.Ok)
        self.add_button.setText(TEXT_ADD)
        buttons.button(QDialogButtonBox.Cancel).setText(TEXT_CANCEL)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.status)
        layout.addWidget(hint)
        layout.addWidget(buttons)

        self.browse_button.clicked.connect(lambda _=False: self.browse())
        self.path.editingFinished.connect(self._path_changed)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.project.currentTextChanged.connect(self._project_changed)
        for name, widget in (("project", self.project.lineEdit()), ("device", self.device.lineEdit()),
                             ("part", self.part), ("date", self.date)):
            widget.textEdited.connect(lambda _text, key=name: self._touched.add(key))
            widget.textChanged.connect(self._refresh)
        self.kind.activated.connect(lambda _index: self._touched.add("kind"))
        self._fill_projects()
        self._refresh()

    # --- действия ---------------------------------------------------------------
    def choose_directory(self, start):
        """Системное окно выбора папки; в тестах подменяется."""
        return QFileDialog.getExistingDirectory(self, TEXT_PICK, start)

    def browse(self):
        chosen = self.choose_directory(logic.clean_path(self.path.text()))
        if chosen:
            self.path.setText(chosen)
            self._path_changed()

    def set_path(self, text):
        """Путь вписан или вставлен: подсказать поля и искать фото."""
        self.path.setText(text)
        self._path_changed()

    def data(self):
        """FolderData, если всё заполнено верно; иначе None."""
        result = self._checked()
        return result if isinstance(result, logic.FolderData) else None

    # --- внутреннее -------------------------------------------------------------
    def _path_changed(self):
        text = logic.clean_path(self.path.text())
        if text == self._scanned_path:
            return
        self._scanned_path = text
        self._photos = None
        self._error = ""
        if not text:
            self._request += 1
            self._refresh()
            return
        self._apply_suggestion(logic.suggest(text, self._kinds, self._no_device, self._today))
        self._request += 1
        threading.Thread(target=self._work, args=(self._request, text), daemon=True).start()
        self._refresh()

    def _work(self, request, path):
        photos, error = self._scan(path)
        try:
            self._signals.scanned.emit(request, photos, error)
        except RuntimeError:
            pass  # окно уже закрыли: результат не нужен

    def _on_scanned(self, request, photos, error):
        if request != self._request:
            return  # путь уже сменили
        self._photos = photos
        self._error = error
        self._refresh()

    def _apply_suggestion(self, suggestion):
        if suggestion.kind is not None and "kind" not in self._touched:
            self.kind.setCurrentIndex(max(0, self.kind.findData(suggestion.kind)))
        for key, box, value in (("project", self.project, suggestion.project), ("device", self.device, suggestion.device)):
            if value and key not in self._touched:
                box.setEditText(value)
        if suggestion.part and "part" not in self._touched:
            self.part.setText(suggestion.part)
        if suggestion.date and "date" not in self._touched:
            self.date.setText(suggestion.date)

    def _fill_projects(self):
        current = self.project.currentText()
        self.project.blockSignals(True)
        self.project.clear()
        projects = self._options.get(self.kind.currentData(), {})
        self.project.addItems(sorted(projects))
        self.project.setEditText(current)
        self.project.blockSignals(False)
        self._fill_devices()

    def _fill_devices(self):
        current = self.device.currentText()
        self.device.clear()
        devices = self._options.get(self.kind.currentData(), {}).get(self.project.currentText(), [])
        self.device.addItems(devices)
        self.device.setEditText(current)

    def _kind_changed(self, _index):
        self._fill_projects()
        self._refresh()

    def _project_changed(self, _text):
        self._fill_devices()
        self._refresh()

    def _checked(self):
        return logic.check(
            self.path.text(), self.kind.currentData(), self.project.currentText(), self.device.currentText(),
            self.part.text(), self.date.text(), self._photos if self._photos is not None else (), self._kinds, self._today,
        )

    def _refresh(self, *_args):
        warn = False  # сообщение об ошибке — заметным цветом, обычная подсказка — серым
        text = logic.clean_path(self.path.text())
        if not text:
            message, ready = TEXT_NO_PATH, False
        elif self._error:
            message, ready = self._error, False
            warn = True
        elif self._photos is None or text != self._scanned_path:
            message, ready = TEXT_SCANNING, False
        else:
            result = self._checked()
            ready = isinstance(result, logic.FolderData)
            message = "Фото в папке: {}".format(len(self._photos)) if ready else str(result)
            if not ready and self._photos:
                message = "Фото в папке: {}. {}".format(len(self._photos), result)
            warn = not ready
        self.status.setProperty("role", "warn" if warn else "muted")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.setText(message)
        self.add_button.setEnabled(ready)
