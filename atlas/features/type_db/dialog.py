"""Окно «В базу типов»: деталь (только для чтения), тип или дефект, номер, описание, артикул."""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPlainTextEdit, QSpinBox, QVBoxLayout,
)

from atlas.features.type_db import logic

TITLE = "В базу типов"
TEXT_SAVE = "Сохранить"
TEXT_CANCEL = "Отмена"
TEXT_KIND_TYPE = "Тип"
TEXT_KIND_DEFECT = "Дефект"
PLACEHOLDER = "Чем отличается: например, третий чип NAND на месте пустой площадки"


class CardDialog(QDialog):
    def __init__(self, part_text, number, article, summary, parent=None):
        """part_text — «A › Проект › Устройство › Деталь»; summary — что будет сохранено («Вырезка есть, подписей: 1»)."""
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.setModal(True)
        self.setMinimumWidth(460)
        self.part_label = QLabel(part_text)
        self.part_label.setWordWrap(True)
        self.kind = QComboBox()
        self.kind.addItem(TEXT_KIND_TYPE, logic.KIND_TYPE)
        self.kind.addItem(TEXT_KIND_DEFECT, logic.KIND_DEFECT)
        self.number = QSpinBox()
        self.number.setRange(1, logic.MAX_TYPE_NO)
        self.number.setValue(number)
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText(PLACEHOLDER)
        self.description.setFixedHeight(90)
        self.article = QLineEdit(article or "")
        self.summary = QLabel(summary)
        self.summary.setProperty("role", "muted")
        form = QFormLayout()
        form.addRow("Деталь", self.part_label)
        form.addRow("Это", self.kind)
        form.addRow("Номер типа", self.number)
        form.addRow("Отличие", self.description)
        form.addRow("Артикул / модель", self.article)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.save_button = buttons.button(QDialogButtonBox.Save)
        self.save_button.setText(TEXT_SAVE)
        buttons.button(QDialogButtonBox.Cancel).setText(TEXT_CANCEL)
        for button in (self.save_button, buttons.button(QDialogButtonBox.Cancel)):
            button.setFocusPolicy(Qt.StrongFocus)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.summary)
        layout.addWidget(buttons)
        self.kind.currentIndexChanged.connect(self._refresh)
        self.description.textChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self):
        self.number.setEnabled(self.kind.currentData() == logic.KIND_TYPE)
        self.save_button.setEnabled(bool(self.description.toPlainText().strip()))

    def card(self):
        kind = self.kind.currentData()
        return logic.CardData(
            kind, self.number.value() if kind == logic.KIND_TYPE else None,
            self.description.toPlainText(), self.article.text(),
        )
