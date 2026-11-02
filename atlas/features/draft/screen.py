"""Экран «Черновик». Только рисует готовые данные, в базу не ходит."""
from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
    QVBoxLayout, QWidget,
)

from atlas.features.draft import logic

TEXT_NOTES = "Заметки (свободным текстом)"
TEXT_NOTES_HINT = "Заметки по проверке… сохраняются сами"
TEXT_FOUND = "Найдено при проверке — собирается само"
TEXT_FOUND_SUB = "из отметок в «Сравнении»"
TEXT_NO_FOLDER = "Откройте папку в «Сравнении» — черновик ведётся для открытой папки"
TEXT_EMPTY = "Отметок пока нет"
TEXT_SAVED = "Сохранено"
TEXT_SAVING = "Сохраняю…"
TEXT_ADD = "+ Добавить вручную"
TEXT_ADD_OK = "Добавить"
TEXT_CANCEL = "Отмена"
TEXT_REMOVE = "Убрать"
TEXT_SN = "SN"
TEXT_DESC = "Описание"
TEXT_COMMENT = "Пояснение"
AUTOSAVE_MS = 1000


def _label(text, role=None, wrap=True):
    label = QLabel(text)
    if role:
        label.setProperty("role", role)
    label.setWordWrap(wrap)
    label.setTextInteractionFlags(Qt.NoTextInteraction)
    return label


def _pill(text, tone):
    pill = QLabel(text)
    pill.setProperty("role", "pill")
    pill.setProperty("tone", tone)
    return pill


def _clear(layout):
    while layout.count():
        widget = layout.takeAt(0).widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


class EntryRow(QFrame):
    text_changed = pyqtSignal(object, str)  # Entry, пояснение
    remove_requested = pyqtSignal(object)

    def __init__(self, entry, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.setProperty("role", "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(_pill(logic.title(entry), logic.KIND_TONES[entry.kind]))
        for text in (logic.count_text(entry), "SN {}".format(entry.sn) if entry.sn else "", entry.kind_text):
            if text:
                head.addWidget(_label(text, "mono" if text.startswith("SN") else None, wrap=False))
        head.addStretch(1)
        if entry.manual_id is not None:
            button = QPushButton(TEXT_REMOVE)
            button.clicked.connect(lambda: self.remove_requested.emit(self.entry))
            head.addWidget(button)
        layout.addLayout(head)
        self.edit = QLineEdit(entry.text)
        self.edit.setPlaceholderText(TEXT_COMMENT)
        self.edit.setMaxLength(logic.TEXT_LIMIT)
        self.edit.editingFinished.connect(self._finished)
        layout.addWidget(self.edit)
        self._sent = entry.text

    def _finished(self):
        text = self.edit.text().strip()
        if text != self._sent:
            self._sent = text
            self.text_changed.emit(self.entry, text)


class DraftScreen(QWidget):
    notes_changed = pyqtSignal(str)  # после паузы в наборе
    text_changed = pyqtSignal(object, str)
    remove_requested = pyqtSignal(object)
    add_requested = pyqtSignal(str, int, str, str)  # вид, номер типа, SN, описание
    shown = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = []
        self.has_folder = False
        self._loading = False
        self._focus_key = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(AUTOSAVE_MS)
        self.timer.timeout.connect(self.flush)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)
        self.empty = _label(TEXT_NO_FOLDER, "muted")
        outer.addWidget(self.empty)
        columns = QHBoxLayout()
        columns.setSpacing(12)
        outer.addLayout(columns, 1)
        self.body = QWidget()
        self.body.setProperty("role", "plain")
        columns.addWidget(self._build_notes(), 1)
        columns.addWidget(self._build_found(), 2)
        columns.addWidget(self._build_actions(), 1)
        self._sync()

    def _panel(self):
        frame = QFrame()
        frame.setProperty("role", "panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        return frame, layout

    def _build_notes(self):
        frame, layout = self._panel()
        layout.addWidget(_label(TEXT_NOTES, "label"))
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText(TEXT_NOTES_HINT)
        self.notes.textChanged.connect(self._on_typed)
        layout.addWidget(self.notes, 1)
        self.status = _label("", "muted", wrap=False)
        layout.addWidget(self.status)
        return frame

    def _build_found(self):
        frame, layout = self._panel()
        head = QHBoxLayout()
        head.addWidget(_label(TEXT_FOUND, "label", wrap=False))
        head.addStretch(1)
        head.addWidget(_label(TEXT_FOUND_SUB, "muted", wrap=False))
        layout.addLayout(head)
        self.scroll = QScrollArea()
        self.scroll.setProperty("role", "plain")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        holder.setProperty("role", "plain")
        self.list = QVBoxLayout(holder)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(8)
        self.list.addStretch(1)
        self.scroll.setWidget(holder)
        layout.addWidget(self.scroll, 1)
        self.form = self._build_form()
        self.form.setVisible(False)
        layout.addWidget(self.form)
        self.add_button = QPushButton(TEXT_ADD)
        self.add_button.clicked.connect(self._open_form)
        row = QHBoxLayout()
        row.addWidget(self.add_button)
        row.addStretch(1)
        layout.addLayout(row)
        return frame

    def _build_form(self):
        form = QFrame()
        form.setProperty("role", "card")
        layout = QHBoxLayout(form)
        layout.setContentsMargins(10, 8, 10, 8)
        self.kind_box = QComboBox()
        for kind in logic.MANUAL_KINDS:
            self.kind_box.addItem(logic.KIND_TITLES[kind].capitalize(), kind)
        self.kind_box.currentIndexChanged.connect(self._kind_changed)
        self.type_spin = QSpinBox()
        self.type_spin.setRange(1, 99)
        self.sn_edit = QLineEdit()
        self.sn_edit.setPlaceholderText(TEXT_SN)
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText(TEXT_DESC)
        self.desc_edit.setMaxLength(logic.TEXT_LIMIT)
        ok, cancel = QPushButton(TEXT_ADD_OK), QPushButton(TEXT_CANCEL)
        ok.clicked.connect(self._submit)
        cancel.clicked.connect(lambda: self.form.setVisible(False))
        self.form_error = _label("", "warn", wrap=False)
        for widget in (self.kind_box, self.type_spin, self.sn_edit):
            layout.addWidget(widget)
        layout.addWidget(self.desc_edit, 1)
        layout.addWidget(ok)
        layout.addWidget(cancel)
        self._kind_changed()
        return form

    def _build_actions(self):
        frame, layout = self._panel()
        self.actions = layout  # слот draft.actions: сюда функции кладут свои кнопки
        layout.addWidget(_label("Действия", "label"))
        layout.addStretch(1)
        return frame

    # --- слот ---------------------------------------------------------------------
    def actions_layout(self):
        return self.actions

    # --- ввод ---------------------------------------------------------------------
    def _on_typed(self):
        if self._loading:
            return
        self.status.setText(TEXT_SAVING)
        self.timer.start()

    def flush(self):
        """Отдать набранное на сохранение сейчас (пауза набора, уход с вкладки, смена папки)."""
        if self.timer.isActive():
            self.timer.stop()
        if self.has_folder and not self._loading:
            self.notes_changed.emit(self.notes.toPlainText()[:logic.NOTES_LIMIT])

    def mark_saved(self):
        if not self.timer.isActive():
            self.status.setText(TEXT_SAVED)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.flush()

    def showEvent(self, event):
        super().showEvent(event)
        self.shown.emit()

    def _kind_changed(self):
        self.type_spin.setVisible(self.kind_box.currentData() == logic.KIND_TYPE)

    def _open_form(self):
        self.form.setVisible(True)
        self.sn_edit.setFocus()

    def _submit(self):
        self.add_requested.emit(self.kind_box.currentData(), self.type_spin.value(), self.sn_edit.text(),
                                self.desc_edit.text())

    def form_done(self):
        self.sn_edit.clear()
        self.desc_edit.clear()
        self.form.setVisible(False)

    def show_error(self, text):
        self.status.setText(text)

    # --- данные -------------------------------------------------------------------
    def _sync(self):
        for widget in (self.notes, self.add_button):
            widget.setEnabled(self.has_folder)
        self.empty.setVisible(not self.has_folder)

    def set_folder(self, has_folder):
        self.has_folder = has_folder
        self._sync()

    def set_notes(self, text):
        """Подставить заметки, пришедшие из базы; набираемое прямо сейчас не затирается."""
        if self.timer.isActive() or (self.notes.hasFocus() and self.notes.toPlainText() != text and self.notes.document().isModified()):
            return
        self._loading = True
        if self.notes.toPlainText() != text:
            self.notes.setPlainText(text)
        self.notes.document().setModified(False)
        self._loading = False
        self.status.setText("")

    def set_entries(self, entries):
        if entries == self.entries:
            return
        self.entries = list(entries)
        _clear(self.list)
        if not self.entries:
            self.list.addWidget(_label(TEXT_EMPTY, "muted"))
        for entry in self.entries:
            row = EntryRow(entry)
            row.text_changed.connect(self.text_changed)
            row.remove_requested.connect(self.remove_requested)
            self.list.addWidget(row)
        self.list.addStretch(1)
