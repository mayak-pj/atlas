"""Экран «Правила» и панель «Правила к детали». Только рисуют готовые данные, в базу не ходят."""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QButtonGroup, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from atlas.features.rules import logic
from atlas.shared.widgets.flow import FlowLayout

TEXT_NEW = "НОВОЕ"
TEXT_READ = "Прочитано"
TEXT_READ_ALL = "Отметить все прочитанными"
TEXT_EMPTY = "Правил пока нет"
TEXT_EMPTY_FILTER = "По этому фильтру правил нет"
TEXT_FORM = "Новое правило"
TEXT_TITLE = "Заголовок"
TEXT_TITLE_HINT = "Коротко, что проверять"
TEXT_SCOPE = "Относится к"
TEXT_BODY = "Описание"
TEXT_BODY_HINT = "Подробности, можно приложить фото"
TEXT_ATTACH = "Приложить фото"
TEXT_PUBLISH = "Опубликовать"
TEXT_PUBLISHING = "Сохраняю…"
TEXT_NOTE = "После публикации у коллег вкладка «Правила» подсветится, а правило к детали покажется в сводке на экране сравнения."
TEXT_NO_PART = "Откройте папку — тогда правило можно привязать к виду, проекту, устройству или детали"
TEXT_PANEL = "Правила к детали"
TEXT_PHOTOS = "Фото: {}"
TEXT_PHOTO_TITLE = "Фото правила"
FILTERS = ((logic.FILTER_ALL, "Все"), (logic.FILTER_GENERAL, "Общие"), (logic.FILTER_PART, "К детали"))
SCOPE_TITLES = (
    (logic.SCOPE_GENERAL, "Общее"), (logic.SCOPE_KIND, "Вид"), (logic.SCOPE_PROJECT, "Проект"),
    (logic.SCOPE_DEVICE, "Устройство"), (logic.SCOPE_PART, "Деталь"),
)
IMAGE_FILTER = "Фото (*.jpg *.jpeg *.png);;Все файлы (*)"


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


class _Thumb(QLabel):
    clicked = pyqtSignal(str)

    def __init__(self, rel, path):
        super().__init__()
        self.rel = rel
        self.setProperty("role", "thumb")
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.setText("нет файла")
        else:
            self.setPixmap(pixmap.scaledToHeight(90, Qt.SmoothTransformation))
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.rel)


class PhotoDialog(QDialog):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TEXT_PHOTO_TITLE)
        layout = QVBoxLayout(self)
        label = QLabel()
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            label.setText("Не удалось открыть фото")
        else:
            label.setPixmap(pixmap.scaled(1000, 760, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(label)


class RuleCard(QFrame):
    read_clicked = pyqtSignal(int)
    photo_clicked = pyqtSignal(str)

    def __init__(self, rule, author, root, today=None, compact=False, parent=None):
        super().__init__(parent)
        self.rule = rule
        self.setProperty("role", "rule")
        self.setProperty("new", "false" if rule.read else "true")
        column = QVBoxLayout(self)
        column.setContentsMargins(12, 10, 12, 10)
        column.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(6)
        if not rule.read:
            head.addWidget(_pill(TEXT_NEW, "type2"))
        head.addWidget(_pill(logic.scope_text(rule), "muted" if rule.scope == logic.SCOPE_GENERAL else "ok"))
        head.addStretch(1)
        column.addLayout(head)
        column.addWidget(_label(rule.title, "heading"))
        if rule.body:
            column.addWidget(_label(rule.body, "dim"))
        if rule.photos:
            thumbs = QWidget()
            thumbs.setProperty("role", "plain")
            flow = FlowLayout(thumbs, spacing=6)
            for rel in rule.photos:
                thumb = _Thumb(rel, Path(root) / logic.thumb_rel(rel))
                thumb.clicked.connect(self.photo_clicked)
                flow.addWidget(thumb)
            column.addWidget(thumbs)
        foot = QHBoxLayout()
        foot.setSpacing(8)
        who = (author + " · " if author else "") + logic.short_date(rule.created_at, today)
        foot.addWidget(_label(who, "muted", wrap=False))
        foot.addStretch(1)
        if not rule.read:
            button = QPushButton(TEXT_READ)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda _=False: self.read_clicked.emit(rule.id))
            foot.addWidget(button)
        column.addLayout(foot)


def _clear(layout, keep=1):
    while layout.count() > keep:
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()


class RulesScreen(QWidget):
    publish_requested = pyqtSignal(object)  # Draft
    read_requested = pyqtSignal(list)
    read_all_requested = pyqtSignal()
    shown = pyqtSignal()

    def __init__(self, root, kinds, today=None, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.today = today
        self.rules, self.names, self.part = [], {}, None
        self.filter_key = logic.FILTER_ALL
        self.photo_paths = []
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(10)
        bar = FlowLayout(spacing=8)
        self.filter_buttons = {}
        group = QButtonGroup(self)
        keys = list(FILTERS) + [(logic.FILTER_KIND_PREFIX + kind, kind) for kind in kinds]
        for key, text in keys:
            button = QPushButton(text)
            button.setProperty("role", "chip")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.NoFocus)
            group.addButton(button)
            button.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            bar.addWidget(button)
            self.filter_buttons[key] = button
        self.filter_buttons[logic.FILTER_ALL].setChecked(True)
        self.read_all_button = QPushButton(TEXT_READ_ALL)
        self.read_all_button.setFocusPolicy(Qt.NoFocus)
        self.read_all_button.clicked.connect(lambda _=False: self.read_all_requested.emit())
        bar.addWidget(self.read_all_button)
        left.addLayout(bar)
        self.scroll = QScrollArea()
        self.scroll.setProperty("role", "plain")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setProperty("role", "plain")
        self.list = QVBoxLayout(body)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(10)
        self.list.addStretch(1)
        self.scroll.setWidget(body)
        left.addWidget(self.scroll, 1)
        outer.addLayout(left, 1)
        outer.addWidget(self._build_form())
        self._refresh_form()

    # --- форма --------------------------------------------------------------------
    def _build_form(self):
        form = QFrame()
        form.setProperty("role", "panel")
        form.setMinimumWidth(280)
        form.setMaximumWidth(380)
        column = QVBoxLayout(form)
        column.setContentsMargins(16, 16, 16, 16)
        column.setSpacing(10)
        column.addWidget(_label(TEXT_FORM, "caption"))
        column.addWidget(_label(TEXT_TITLE, "muted"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText(TEXT_TITLE_HINT)
        column.addWidget(self.title_edit)
        column.addWidget(_label(TEXT_SCOPE, "muted"))
        chips = FlowLayout(spacing=6)
        self.scope_buttons = {}
        group = QButtonGroup(self)
        for scope, text in SCOPE_TITLES:
            button = QPushButton(text)
            button.setProperty("role", "chip")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.NoFocus)
            group.addButton(button)
            button.clicked.connect(lambda _=False: self._refresh_form())
            chips.addWidget(button)
            self.scope_buttons[scope] = button
        self.scope_buttons[logic.SCOPE_GENERAL].setChecked(True)
        column.addLayout(chips)
        self.scope_note = _label("", "muted")
        column.addWidget(self.scope_note)
        column.addWidget(_label(TEXT_BODY, "muted"))
        self.body_edit = QPlainTextEdit()
        self.body_edit.setPlaceholderText(TEXT_BODY_HINT)
        self.body_edit.setMinimumHeight(110)
        column.addWidget(self.body_edit)
        self.attach_button = QPushButton(TEXT_ATTACH)
        self.attach_button.setFocusPolicy(Qt.NoFocus)
        self.attach_button.clicked.connect(lambda _=False: self.attach())
        column.addWidget(self.attach_button)
        self.photos_label = _label("", "muted")
        column.addWidget(self.photos_label)
        self.publish_button = QPushButton(TEXT_PUBLISH)
        self.publish_button.setProperty("role", "primary")
        self.publish_button.setFocusPolicy(Qt.NoFocus)
        self.publish_button.clicked.connect(lambda _=False: self.publish())
        column.addWidget(self.publish_button)
        self.error_label = _label("", "warn")
        column.addWidget(self.error_label)
        column.addWidget(_label(TEXT_NOTE, "muted"))
        column.addStretch(1)
        return form

    def current_scope(self):
        for scope, button in self.scope_buttons.items():
            if button.isChecked():
                return scope
        return logic.SCOPE_GENERAL

    def _refresh_form(self):
        has_part = self.part is not None
        for scope, button in self.scope_buttons.items():
            button.setEnabled(scope == logic.SCOPE_GENERAL or has_part)
        if not has_part and self.current_scope() != logic.SCOPE_GENERAL:
            self.scope_buttons[logic.SCOPE_GENERAL].setChecked(True)
        scope = self.current_scope()
        if scope != logic.SCOPE_GENERAL:
            self.scope_note.setText(logic.scope_label_for(scope, self.part))
        else:
            self.scope_note.setText("" if has_part else TEXT_NO_PART)
        self.photos_label.setText(TEXT_PHOTOS.format(len(self.photo_paths)) if self.photo_paths else "")

    def attach(self, paths=None):
        if paths is None:
            paths, _ = QFileDialog.getOpenFileNames(self, TEXT_ATTACH, "", IMAGE_FILTER)
        for path in paths:
            if path not in self.photo_paths and len(self.photo_paths) < logic.MAX_PHOTOS:
                self.photo_paths.append(path)
        self._refresh_form()

    def publish(self):
        draft = logic.draft_for(self.current_scope(), self.part, self.title_edit.text(), self.body_edit.toPlainText(),
                                self.photo_paths)
        try:
            logic.checked(draft)
        except logic.RuleError as exc:
            self.show_error(str(exc))
            return
        self.show_error("")
        self.publish_requested.emit(draft)

    def set_busy(self, busy):
        self.publish_button.setEnabled(not busy)
        self.publish_button.setText(TEXT_PUBLISHING if busy else TEXT_PUBLISH)

    def show_error(self, text):
        self.error_label.setText(text)

    def clear_form(self):
        self.title_edit.clear()
        self.body_edit.clear()
        self.photo_paths = []
        self.show_error("")
        self._refresh_form()

    # --- список -------------------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        self.shown.emit()

    def set_data(self, rules, names, part):
        self.rules, self.names, self.part = rules, names, part
        self._refresh_form()
        self._render()

    def _set_filter(self, key):
        self.filter_key = key
        self._render()

    def _render(self):
        _clear(self.list)
        shown = logic.filtered(self.rules, self.filter_key)
        if not shown:
            text = TEXT_EMPTY if not self.rules else TEXT_EMPTY_FILTER
            self.list.insertWidget(0, _label(text, "muted"))
        for index, rule in enumerate(shown):
            card = RuleCard(rule, self.names.get(rule.author_id, ""), self.root, self.today)
            card.read_clicked.connect(lambda rule_id: self.read_requested.emit([rule_id]))
            card.photo_clicked.connect(self.open_photo)
            self.list.insertWidget(index, card)
        self.read_all_button.setEnabled(logic.unread_count(self.rules) > 0)

    def open_photo(self, rel):
        PhotoDialog(self.root / rel, self).exec_()


class RulesPanel(QFrame):
    """Правила к открытой детали в правой колонке экрана сравнения. Пустая — скрыта."""

    read_requested = pyqtSignal(list)
    photo_clicked = pyqtSignal(str)

    def __init__(self, root, today=None, parent=None):
        super().__init__(parent)
        self.setProperty("role", "panel")
        self.root, self.today = Path(root), today
        self.shown_rules = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(8)
        outer.addWidget(_label(TEXT_PANEL, "caption"))
        self.column = QVBoxLayout()
        self.column.setSpacing(8)
        outer.addLayout(self.column)
        self.setVisible(False)

    def show_rules(self, rules, names):
        self.shown_rules = list(rules)
        while self.column.count():
            item = self.column.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        for rule in rules:
            card = RuleCard(rule, names.get(rule.author_id, ""), self.root, self.today, compact=True)
            card.read_clicked.connect(lambda rule_id: self.read_requested.emit([rule_id]))
            card.photo_clicked.connect(self.photo_clicked)
            self.column.addWidget(card)
        self.setVisible(bool(rules))
