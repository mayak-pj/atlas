"""Экран «Комментарии». Только рисует готовые данные, в базу не ходит."""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QMimeData, Qt, pyqtSignal
from PyQt5.QtGui import QImage, QImageReader, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from atlas.features.comments import logic
from atlas.shared.widgets.flow import FlowLayout

TEXT_HINT = "Сообщение коллегам… можно вставить скриншот (Ctrl+V)"
TEXT_PHOTO = "Фото"
TEXT_DROP = "Убрать фото"
TEXT_BIND = "Привязать к детали"
TEXT_BIND_TO = "Привязано: {}"
TEXT_NO_PART = "Откройте папку — тогда сообщение можно привязать к детали"
TEXT_TO = "Кому:"
TEXT_ALL = "всем"
TEXT_EARLIER = "Пометить «ошибка ранее»"
TEXT_LIFE = "Исчезнет через"
TEXT_SEND = "Отправить"
TEXT_SENDING = "Отправляю…"
TEXT_EMPTY = "Сообщений пока нет"
TEXT_FOR = "для {}"
TEXT_FOR_ME = "для вас"
TEXT_EARLIER_PILL = "ошибка ранее"
TEXT_OPEN = "Открыть в сравнении"
TEXT_REPLY = "Ответить"
TEXT_DONE = "Готово"
TEXT_VIEW = "Фото"
IMAGE_FILTER = "Фото (*.jpg *.jpeg *.png);;Все файлы (*)"
THUMB_HEIGHT = 150
PREVIEW = 56


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
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()


class PasteEdit(QPlainTextEdit):
    """Поле сообщения: картинку из буфера (Ctrl+V) не вставляет в текст, а отдаёт наружу."""

    image_pasted = pyqtSignal(object)  # QImage

    def canInsertFromMimeData(self, source):
        return source.hasImage() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if source.hasImage():
            image = source.imageData()
            if isinstance(image, QImage) and not image.isNull():
                self.image_pasted.emit(image)
                return
        if source.hasText() or source.hasHtml():
            plain = QMimeData()
            plain.setText(source.text())  # без форматирования: только текст
            super().insertFromMimeData(plain)


class PhotoDialog(QDialog):
    """Просмотр фото сообщения, вписанного в окно."""

    def __init__(self, root, rel, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TEXT_VIEW)
        self.pixmap = QPixmap(str(Path(root) / rel))
        layout = QVBoxLayout(self)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)
        self.resize(900, 680)
        self._fit()

    def _fit(self):
        if not self.pixmap.isNull():
            self.label.setPixmap(self.pixmap.scaled(self.label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()


class _Thumb(QLabel):
    clicked = pyqtSignal(str)

    def __init__(self, rel, path):
        super().__init__()
        self.rel = rel
        self.setProperty("role", "thumb")
        self.setCursor(Qt.PointingHandCursor)
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.setText("?")
        else:
            self.setPixmap(pixmap.scaledToHeight(THUMB_HEIGHT, Qt.SmoothTransformation))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.rel)


class CommentCard(QFrame):
    open_clicked = pyqtSignal(object)  # Comment
    reply_clicked = pyqtSignal(object)
    done_clicked = pyqtSignal(int)
    photo_clicked = pyqtSignal(str)

    def __init__(self, item, users, me_id, root, can_open, today=None, parent=None):
        super().__init__(parent)
        self.item = item
        mine = item.author_id == me_id
        self.setProperty("role", "rule")
        self.setProperty("new", "true" if not mine and item.to_user_id == me_id else "false")
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(12)
        name, color = users.get(item.author_id, ("?", "#8B95A3"))
        avatar = QLabel(logic.initials(name))
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setFixedSize(30, 30)
        avatar.setStyleSheet("background: {}; color: #0F1115; border-radius: 15px; font-weight: 700;".format(color))
        row.addWidget(avatar, 0, Qt.AlignTop)
        column = QVBoxLayout()
        column.setSpacing(6)
        row.addLayout(column, 1)
        head = FlowLayout(spacing=6)
        author = _label(name, "heading", wrap=False)
        head.addWidget(author)
        if item.to_user_id is not None:
            who = TEXT_FOR_ME if item.to_user_id == me_id else TEXT_FOR.format(users.get(item.to_user_id, ("?",))[0])
            head.addWidget(_pill(who, "ok"))
        if item.earlier_error:
            head.addWidget(_pill(TEXT_EARLIER_PILL, "defect"))
        if item.part_label:
            head.addWidget(_pill(item.part_label, "type3"))
        when = "{}{}".format(logic.short_date(item.created_at, today),
                             " · " + logic.lifetime_text(item) if logic.lifetime_text(item) else "")
        head.addWidget(_label(when, "muted", wrap=False))
        column.addLayout(head)
        if item.body:
            column.addWidget(_label(item.body))  # обычным цветом текста: это само сообщение, а не служебная строка
        if item.photos:
            photos = QWidget()
            photos.setProperty("role", "plain")
            line = QHBoxLayout(photos)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(6)
            for rel in item.photos:
                thumb = _Thumb(rel, Path(root) / logic.thumb_rel(rel))
                thumb.clicked.connect(self.photo_clicked)
                line.addWidget(thumb)
            line.addStretch(1)
            column.addWidget(photos)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        if item.folder_id is not None and can_open:
            buttons.addWidget(self._button(TEXT_OPEN, lambda: self.open_clicked.emit(item)))
        if not mine:
            buttons.addWidget(self._button(TEXT_REPLY, lambda: self.reply_clicked.emit(item)))
            buttons.addWidget(self._button(TEXT_DONE, lambda: self.done_clicked.emit(item.id)))
        buttons.addStretch(1)
        if buttons.count() > 1:
            column.addLayout(buttons)

    @staticmethod
    def _button(text, handler):
        button = QPushButton(text)
        button.setFocusPolicy(Qt.NoFocus)
        button.clicked.connect(lambda _=False: handler())
        return button


class CommentsScreen(QWidget):
    send_requested = pyqtSignal(object)  # Draft
    done_requested = pyqtSignal(int)
    open_requested = pyqtSignal(object)  # Comment
    shown = pyqtSignal()

    def __init__(self, root, lifetimes, max_photos, can_open=False, today=None, parent=None):
        super().__init__(parent)
        self.root, self.today, self.max_photos, self.can_open = Path(root), today, max_photos, can_open
        self.items, self.users, self.me_id, self.part, self.folder_id = [], {}, 0, None, None
        self.photos = []  # пути к файлам и QImage из буфера
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)
        outer.addWidget(self._build_form(lifetimes))
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
        outer.addWidget(self.scroll, 1)
        self._refresh_form()

    def _build_form(self, lifetimes):
        form = QFrame()
        form.setProperty("role", "panel")
        column = QVBoxLayout(form)
        column.setContentsMargins(14, 14, 14, 14)
        column.setSpacing(10)
        self.edit = PasteEdit()
        self.edit.setPlaceholderText(TEXT_HINT)
        self.edit.setFixedHeight(84)
        self.edit.image_pasted.connect(self.add_image)
        column.addWidget(self.edit)
        self.previews = QWidget()
        self.previews.setProperty("role", "plain")
        self.previews_layout = FlowLayout(self.previews, spacing=4)
        column.addWidget(self.previews)
        bar = FlowLayout(spacing=8)
        self.photo_button = QPushButton(TEXT_PHOTO)
        self.drop_button = QPushButton(TEXT_DROP)
        self.bind_button = QPushButton(TEXT_BIND)
        self.bind_button.setCheckable(True)
        self.earlier_button = QPushButton(TEXT_EARLIER)
        self.earlier_button.setCheckable(True)
        for button in (self.photo_button, self.drop_button, self.bind_button, self.earlier_button):
            button.setFocusPolicy(Qt.NoFocus)
        self.photo_button.clicked.connect(lambda _=False: self.attach())
        self.drop_button.clicked.connect(lambda _=False: self.drop_photos())
        self.bind_button.clicked.connect(lambda _=False: self._refresh_form())
        bar.addWidget(self.photo_button)
        bar.addWidget(self.drop_button)
        bar.addWidget(self.bind_button)
        bar.addWidget(_label(TEXT_TO, "muted", wrap=False))
        self.to_box = QComboBox()
        self.to_box.addItem(TEXT_ALL, None)
        bar.addWidget(self.to_box)
        bar.addWidget(self.earlier_button)
        bar.addWidget(_label(TEXT_LIFE, "muted", wrap=False))
        self.life_box = QComboBox()
        for days, text in lifetimes:
            self.life_box.addItem(text, days)
        bar.addWidget(self.life_box)
        column.addLayout(bar)
        send_row = QHBoxLayout()
        self.note = _label("", "muted")
        self.error_label = _label("", "warn")
        send_row.addWidget(self.note, 1)
        send_row.addWidget(self.error_label, 1)
        self.send_button = QPushButton(TEXT_SEND)
        self.send_button.setProperty("role", "primary")
        self.send_button.setFocusPolicy(Qt.NoFocus)
        self.send_button.clicked.connect(lambda _=False: self.send())
        send_row.addWidget(self.send_button)
        column.addLayout(send_row)
        return form

    # --- форма --------------------------------------------------------------------
    def _refresh_form(self):
        has_part = self.part is not None and self.folder_id is not None
        self.bind_button.setEnabled(has_part)
        if not has_part:
            self.bind_button.setChecked(False)
        self.note.setText(TEXT_BIND_TO.format(logic.part_label(self.part)) if self.bind_button.isChecked()
                          else ("" if has_part else TEXT_NO_PART))
        self.drop_button.setVisible(bool(self.photos))
        self.photo_button.setEnabled(len(self.photos) < self.max_photos)
        self._render_previews()

    def _render_previews(self):
        _clear(self.previews_layout)
        for source in self.photos:
            if isinstance(source, QImage):
                image = source
            else:
                reader = QImageReader(str(source))
                reader.setAutoTransform(True)
                size = reader.size()
                if size.isValid():
                    size.scale(PREVIEW * 2, PREVIEW * 2, Qt.KeepAspectRatio)
                    reader.setScaledSize(size)
                image = reader.read()
            label = QLabel()
            label.setProperty("role", "thumb")
            if image.isNull():
                label.setText("?")
            else:
                label.setPixmap(QPixmap.fromImage(image).scaledToHeight(PREVIEW, Qt.SmoothTransformation))
            self.previews_layout.addWidget(label)

    def add_image(self, image):
        if len(self.photos) < self.max_photos:
            self.photos.append(image)
        self._refresh_form()

    def attach(self, paths=None):
        if paths is None:
            paths, _ = QFileDialog.getOpenFileNames(self, TEXT_PHOTO, "", IMAGE_FILTER)
        for path in paths:
            if path not in self.photos and len(self.photos) < self.max_photos:
                self.photos.append(path)
        self._refresh_form()

    def drop_photos(self):
        self.photos = []
        self._refresh_form()

    def current_draft(self):
        bound = self.bind_button.isChecked() and self.part is not None
        return logic.Draft(
            self.edit.toPlainText(), self.to_box.currentData(),
            self.part.id if bound else None, self.folder_id if bound else None,
            logic.part_label(self.part) if bound else "",
            self.earlier_button.isChecked(), self.life_box.currentData(), tuple(self.photos))

    def send(self):
        draft = self.current_draft()
        try:
            logic.checked(draft, self.max_photos)
        except logic.CommentError as exc:
            self.show_error(str(exc))
            return
        self.show_error("")
        self.send_requested.emit(draft)

    def set_busy(self, busy):
        self.send_button.setEnabled(not busy)
        self.send_button.setText(TEXT_SENDING if busy else TEXT_SEND)

    def show_error(self, text):
        self.error_label.setText(text)

    def clear_form(self):
        self.edit.clear()
        self.photos = []
        self.earlier_button.setChecked(False)
        self.to_box.setCurrentIndex(0)
        self.show_error("")
        self._refresh_form()

    def reply_to(self, item):
        """Адресат — автор, деталь та же (если открыта та же папка — привязка включается)."""
        index = self.to_box.findData(item.author_id)
        self.to_box.setCurrentIndex(max(index, 0))
        if item.folder_id is not None and item.folder_id == self.folder_id:
            self.bind_button.setChecked(True)
        self._refresh_form()
        self.edit.setFocus()

    # --- список -------------------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        self.shown.emit()

    def set_data(self, items, users, me_id, part, folder_id):
        self.items, self.users, self.me_id, self.part, self.folder_id = items, users, me_id, part, folder_id
        current = self.to_box.currentData()
        self.to_box.blockSignals(True)
        while self.to_box.count() > 1:
            self.to_box.removeItem(1)
        for user_id, (name, _color) in sorted(users.items(), key=lambda pair: pair[1][0]):
            if user_id != me_id:
                self.to_box.addItem(name, user_id)
        self.to_box.setCurrentIndex(max(self.to_box.findData(current), 0))
        self.to_box.blockSignals(False)
        self._refresh_form()
        self._render()

    def _render(self):
        while self.list.count() > 1:
            widget = self.list.takeAt(0).widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        shown = [item for item in self.items if logic.visible_to(item, self.me_id)]
        if not shown:
            self.list.insertWidget(0, _label(TEXT_EMPTY, "muted"))
        for index, item in enumerate(shown):
            card = CommentCard(item, self.users, self.me_id, self.root, self.can_open, self.today)
            card.open_clicked.connect(self.open_requested)
            card.reply_clicked.connect(self.reply_to)
            card.done_clicked.connect(self.done_requested)
            card.photo_clicked.connect(lambda rel: PhotoDialog(self.root, rel, self).exec_())
            self.list.insertWidget(index, card)
