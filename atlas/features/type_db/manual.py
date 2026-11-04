"""«+ Добавить из файла…» (04.11.2026): старые фото типов в «БД» вручную, без экрана сравнения.

Накопленное за год лежит неструктурированно, поэтому каждое фото вносится своей карточкой: проект, устройство
(«в составе техники», может быть пустым), деталь, модель, номер типа, описание, дата и кто добавил (обязательно).
После сохранения окно остаётся открытым с теми же полями: следующее фото той же детали — только выбрать файл.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QDate, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox, QCompleter, QDateEdit, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
)

from atlas.features.type_db import logic

TITLE = "Добавить в БД из файла"
TEXT_NO_DEVICE = "Без устройства"  # устройство необязательно, а в базе ядра оно есть у каждой детали
TEXT_HINT = "Каждое фото — своя карточка. После сохранения поля остаются: для следующего фото той же детали выберите только файл."
TEXT_BROWSE = "Обзор…"
TEXT_SAVE = "Сохранить"
TEXT_CLOSE = "Закрыть"
TEXT_SAVING = "Сохраняю…"
TEXT_SAVED = "Добавлено: {}. Можно выбрать следующее фото"
PHOTO_FILTER = "Фото (*.jpg *.jpeg *.png *.bmp)"


class ManualError(ValueError):
    """Поле заполнено неверно: текст показывается человеку."""


@dataclass(frozen=True)
class ManualCard:
    photo: str
    kind: str  # вид проекта (A/B)
    project: str
    device: str  # пусто — «Без устройства»
    part: str
    article: str
    type_no: int
    description: str
    day: str  # ГГГГ-ММ-ДД — дата карточки (когда тип был найден), а не сегодняшняя
    user_id: Optional[int]


def checked(card, no_device=TEXT_NO_DEVICE):
    """Чистая карточка или ManualError. Обязательны: фото, проект, деталь, кто добавил."""
    photo = str(card.photo or "").strip().strip('"')
    if not photo:
        raise ManualError("Выберите фото")
    if not Path(photo).is_file():
        raise ManualError("Нет такого файла: {}".format(photo))

    def text(value):
        return " ".join(str(value or "").split())

    if not text(card.project):
        raise ManualError("Укажите проект")
    if not text(card.part):
        raise ManualError("Укажите наименование детали")
    if card.user_id is None:
        raise ManualError("Укажите, кто добавил")
    if not 1 <= int(card.type_no) <= logic.MAX_TYPE_NO:
        raise ManualError("Номер типа — от 1 до {}".format(logic.MAX_TYPE_NO))
    return ManualCard(photo, card.kind, text(card.project), text(card.device) or no_device, text(card.part),
                      text(card.article), int(card.type_no), text(card.description), card.day, card.user_id)


class ManualDialog(QDialog):
    """Окно ввода. Само в базу не пишет: `save_requested(ManualCard)`, ответ — `saved(text)` / `failed(text)`."""

    save_requested = pyqtSignal(object)

    def __init__(self, kinds, users, current_user_id, names, parent=None):
        """kinds — виды проектов; users — [(id, имя)]; names — {"project"|"device"|"part": [известные]} для подсказок."""
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        hint = QLabel(TEXT_HINT)
        hint.setWordWrap(True)
        hint.setProperty("role", "muted")
        layout.addWidget(hint)
        form = QFormLayout()
        self.photo = QLineEdit()
        self.photo.setPlaceholderText("Путь к фото: можно вставить")
        browse = QPushButton(TEXT_BROWSE)
        browse.setAutoDefault(False)
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.photo, 1)
        row.addWidget(browse)
        form.addRow("Фото", row)
        self.kind = QComboBox()
        for kind in kinds:
            self.kind.addItem(kind, kind)
        form.addRow("Вид проекта", self.kind)
        self.project = self._line(names.get("project", ()), "Проект")
        form.addRow("Проект", self.project)
        self.device = self._line(names.get("device", ()), "Можно оставить пустым")
        form.addRow("В составе техники", self.device)
        self.part = self._line(names.get("part", ()), "Наименование детали")
        form.addRow("Деталь", self.part)
        self.article = QLineEdit()
        self.article.setPlaceholderText("Необязательно")
        form.addRow("Модель / артикул", self.article)
        self.number = QSpinBox()
        self.number.setRange(1, logic.MAX_TYPE_NO)
        form.addRow("Номер типа", self.number)
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText("Чем отличается — необязательно")
        self.description.setFixedHeight(70)
        form.addRow("Отличие", self.description)
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("dd.MM.yyyy")
        form.addRow("Дата", self.day)
        self.user = QComboBox()
        self.user.addItem("— выберите —", None)
        for user_id, name in users:
            self.user.addItem(name, user_id)
        index = self.user.findData(current_user_id)
        self.user.setCurrentIndex(max(index, 0))
        form.addRow("Кто добавил", self.user)
        layout.addLayout(form)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.save_button = QPushButton(TEXT_SAVE)
        self.save_button.setProperty("role", "primary")
        self.save_button.clicked.connect(self.save)
        close = QPushButton(TEXT_CLOSE)
        close.setAutoDefault(False)
        close.clicked.connect(self.accept)
        buttons.addWidget(self.save_button)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _line(self, known, placeholder):
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        completer = QCompleter(sorted(set(known), key=str.casefold), edit)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        edit.setCompleter(completer)
        return edit

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, TITLE, self.photo.text(), PHOTO_FILTER)
        if path:
            self.photo.setText(path)

    def card(self):
        day = self.day.date()
        return ManualCard(
            self.photo.text(), self.kind.currentData(), self.project.text(), self.device.text(), self.part.text(),
            self.article.text(), self.number.value(), self.description.toPlainText(),
            date(day.year(), day.month(), day.day()).isoformat(), self.user.currentData(),
        )

    def save(self):
        try:
            card = checked(self.card())
        except ManualError as exc:
            self.failed(str(exc))
            return
        self.save_button.setEnabled(False)
        self._say(TEXT_SAVING, "muted")
        self.save_requested.emit(card)

    def saved(self, label):
        """Запись прошла: файл — следующий, остальные поля остаются."""
        self.photo.clear()
        self.save_button.setEnabled(True)
        self._say(TEXT_SAVED.format(label), "muted")

    def failed(self, text):
        self.save_button.setEnabled(True)
        self._say(text, "warn")

    def _say(self, text, role):
        self.status.setText(text)
        self.status.setProperty("role", role)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
