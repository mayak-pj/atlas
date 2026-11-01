"""Вкладка «База типов»: поиск, фильтры, сетка карточек, карточка типа справа. Данные приходят готовыми (`set_entries`)."""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from atlas.core import theme
from atlas.features.type_db import logic
from atlas.shared.viewer.levels import L1

MAX_CARDS = 60  # больше виджетов сразу не строим: поиск уточняют, а не листают сотни карточек
CARD_MIN_WIDTH = 250
GRID_SPACING = 12
THUMB_HEIGHT = 150
DETAIL_PHOTO_HEIGHT = 260
DETAIL_CROP_HEIGHT = 150
PLACEHOLDER = "Поиск по названию, артикулу, устройству, описанию…"
TEXT_ALL = "Все проекты"
TEXT_ARCHIVE_NOTE = "Архив — всегда внизу"
TEXT_EMPTY = "В базе типов пока ничего нет: добавьте тип кнопкой «+ В базу типов» на экране сравнения"
TEXT_NOTHING = "Ничего не найдено"
TEXT_PICK = "Выберите карточку слева"
TEXT_NO_FILE = "Нет фото"
TEXT_LOAD_FAILED = "Не удалось прочитать базу типов: показаны прежние данные"
TEXT_ARCHIVED = "В архиве"
TEXT_ACTIVE = "Действует"


def _found_text(count, shown):
    return "Найдено: {}".format(count) if count == shown else "Показано {} из {}".format(shown, count)


class ThumbView(QWidget):
    """Картинка по пути: уровень L1 из общего кэша, читается в фоне; рисуется по центру с сохранением пропорций."""

    def __init__(self, cache, height, parent=None):
        super().__init__(parent)
        self.setObjectName("PhotoView")  # тот же фон и скругление, что у окна просмотра
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(height)
        self._cache = cache
        self._path = None
        self._image = None
        self._failed = False
        cache.ready.connect(self._on_ready)
        cache.failed.connect(self._on_failed)

    def set_path(self, path):
        path = str(path) if path else None
        if path == self._path:
            return
        self._path = path
        self._image = None
        self._failed = path is None
        if path is not None:
            hit = self._cache.get(path, L1)
            if hit is not None:
                self._image = hit.image
        self.update()

    @property
    def has_image(self):
        return self._image is not None

    @property
    def failed(self):
        return self._failed

    def _on_ready(self, path, level, image):
        if path == self._path and (self._image is None or level >= L1):
            self._image = image
            self._failed = False
            self.update()

    def _on_failed(self, path, level, text):
        if path == self._path and self._image is None:
            self._failed = True
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self._image is None:
            painter.setPen(theme.current().qcolor("muted"))
            painter.drawText(self.rect(), Qt.AlignCenter, TEXT_NO_FILE if self._failed else "")
            return
        area = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        scale = min(area.width() / self._image.width(), area.height() / self._image.height())
        width, height = self._image.width() * scale, self._image.height() * scale
        painter.drawImage(QRectF(area.center().x() - width / 2, area.center().y() - height / 2, width, height), self._image)


class TypeCard(QFrame):
    clicked = pyqtSignal(int)

    def __init__(self, entry, cache, root, selected, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.setProperty("role", "type-card")
        self.setProperty("on", bool(selected))
        self.setProperty("archived", entry.archived)
        self.setCursor(Qt.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.thumb = ThumbView(cache, THUMB_HEIGHT)
        self.thumb.set_path(root / entry.photo_rel)
        layout.addWidget(self.thumb)
        body = QVBoxLayout()
        body.setContentsMargins(12, 10, 12, 10)
        body.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.name = QLabel(entry.part_name)
        self.name.setProperty("role", "folder-title")
        head.addWidget(self.name, 1)
        self.pill = QLabel(entry.pill)
        self.pill.setProperty("role", "pill")
        self.pill.setProperty("tone", "muted" if entry.archived else entry.tone)
        head.addWidget(self.pill)
        body.addLayout(head)
        self.description = QLabel(logic.short_text(entry.description))
        self.description.setWordWrap(True)
        self.description.setProperty("role", "dim")
        body.addWidget(self.description)
        meta = " · ".join(part for part in (entry.article, entry.date_text, entry.author) if part)
        self.meta = QLabel(meta)
        self.meta.setProperty("role", "mono")
        body.addWidget(self.meta)
        if entry.archived:
            note = QLabel(TEXT_ARCHIVED)
            note.setProperty("role", "caption")
            body.addWidget(note)
        layout.addLayout(body)
        self.setToolTip("{} › {} › {}".format(entry.project, entry.device, entry.part_name))

    def set_selected(self, selected):
        self.setProperty("on", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.entry.id)
        super().mousePressEvent(event)


class DetailPanel(QFrame):
    """«Карточка типа» справа: что за тип, чем отличается, кто добавил и все типы устройства."""

    def __init__(self, cache, root, parent=None):
        super().__init__(parent)
        self.setProperty("role", "panel")
        self.setMinimumWidth(300)
        self.setMaximumWidth(380)
        self._cache = cache
        self._root = root
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        caption = QLabel("Карточка типа")
        caption.setProperty("role", "caption")
        layout.addWidget(caption)
        self.empty = QLabel(TEXT_PICK)
        self.empty.setProperty("role", "muted")
        layout.addWidget(self.empty)
        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        self.photo = ThumbView(cache, DETAIL_PHOTO_HEIGHT)
        body.addWidget(self.photo)
        self.crop_caption = QLabel("Вырезка")
        self.crop_caption.setProperty("role", "caption")
        body.addWidget(self.crop_caption)
        self.crop = ThumbView(cache, DETAIL_CROP_HEIGHT)
        body.addWidget(self.crop)
        self.title = QLabel()
        self.title.setProperty("role", "heading")
        self.title.setWordWrap(True)
        body.addWidget(self.title)
        pills = QHBoxLayout()
        pills.setSpacing(8)
        self.pill = QLabel()
        self.pill.setProperty("role", "pill")
        self.status = QLabel()
        self.status.setProperty("role", "pill")
        self.status.setProperty("tone", "muted")
        pills.addWidget(self.pill)
        pills.addWidget(self.status)
        pills.addStretch(1)
        body.addLayout(pills)
        self.description = self._field(body, "Отличие")
        self.article = self._field(body, "Артикул / модель")
        self.author = self._field(body, "Добавил")
        self.device_caption = QLabel()
        self.device_caption.setProperty("role", "caption")
        body.addWidget(self.device_caption)
        self.device_types = QLabel()
        self.device_types.setWordWrap(True)
        self.device_types.setTextFormat(Qt.RichText)
        body.addWidget(self.device_types)
        body.addStretch(1)
        layout.addWidget(self.body, 1)
        self.body.hide()

    def _field(self, layout, caption):
        head = QLabel(caption)
        head.setProperty("role", "caption")
        layout.addWidget(head)
        value = QLabel()
        value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(value)
        return value

    def show_entry(self, entry, entries):
        if entry is None:
            self.body.hide()
            self.empty.show()
            return
        self.empty.hide()
        self.body.show()
        self.photo.set_path(self._root / entry.photo_rel)
        self.crop.set_path(self._root / entry.crop_rel if entry.crop_rel else None)
        self.crop.setVisible(bool(entry.crop_rel))
        self.crop_caption.setVisible(bool(entry.crop_rel))
        self.title.setText(entry.part_name)
        self.pill.setText(entry.pill)
        self.pill.setProperty("tone", entry.tone)
        self.status.setText(TEXT_ARCHIVED if entry.archived else TEXT_ACTIVE)
        for label in (self.pill, self.status):
            label.style().unpolish(label)
            label.style().polish(label)
        self.description.setText(entry.description)
        self.article.setText(entry.article or "—")
        self.author.setText(", ".join(part for part in (entry.author, entry.date_text) if part))
        self.device_caption.setText("Все типы устройства «{}»".format(entry.device))
        muted = theme.current().color("muted")
        lines = []
        for part_name, labels in logic.device_summary(entries, entry.device_id):
            texts = [
                '<span style="color:{}">{} (архив)</span>'.format(muted, _escape(text)) if archived else _escape(text)
                for text, archived in labels
            ]
            lines.append("{} — {}".format(_escape(part_name), ", ".join(texts)))
        self.device_types.setText("<br>".join(lines))


def _escape(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class TypeDbScreen(QWidget):
    shown = pyqtSignal()  # вкладку открыли: данные могли измениться у коллег

    def __init__(self, cache, root, kinds, parent=None):
        super().__init__(parent)
        self._cache = cache
        self._root = root
        self._entries = []
        self._visible = []
        self._cards = {}
        self._selected = None
        self._kind = None
        self._device_only = False
        self._loaded = False
        self._columns = 0

        self.search = QLineEdit()
        self.search.setPlaceholderText(PLACEHOLDER)
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Поиск")
        self.search.textChanged.connect(lambda _text: self._refilter())
        self.found = QLabel("")
        self.found.setProperty("role", "muted")
        search_row = QHBoxLayout()
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.found)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.kind_buttons = {}
        for kind, text in [(None, TEXT_ALL)] + [(kind, kind) for kind in kinds]:
            button = self._chip(text)
            button.clicked.connect(lambda _=False, k=kind: self._set_kind(k))
            self.kind_buttons[kind] = button
            chips.addWidget(button)
        self.kind_buttons[None].setChecked(True)
        self.device_button = self._chip("")
        self.device_button.clicked.connect(self._on_device_toggled)
        self.device_button.hide()
        chips.addWidget(self.device_button)
        note = QLabel(TEXT_ARCHIVE_NOTE)
        note.setProperty("role", "muted")
        chips.addWidget(note)
        chips.addStretch(1)

        self.message = QLabel("")
        self.message.setProperty("role", "muted")
        self.message.setAlignment(Qt.AlignCenter)
        self.grid_holder = QWidget()
        self.grid = QGridLayout(self.grid_holder)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(GRID_SPACING)
        self.grid.setAlignment(Qt.AlignTop)
        self.scroll = QScrollArea()
        self.scroll.setProperty("role", "plain")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidget(self.grid_holder)
        self.scroll.viewport().installEventFilter(self)

        middle = QVBoxLayout()
        middle.setSpacing(12)
        middle.addLayout(search_row)
        middle.addLayout(chips)
        middle.addWidget(self.message)
        middle.addWidget(self.scroll, 1)
        self.detail = DetailPanel(cache, root)
        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(14)
        root_layout.addLayout(middle, 1)
        root_layout.addWidget(self.detail)
        self._render()

    # --- данные -----------------------------------------------------------------
    def set_entries(self, entries):
        entries = list(entries)
        if self._loaded and entries == self._entries:
            return  # ничего не изменилось: не перестраиваем сетку и не мигаем при каждом открытии вкладки
        self._entries = entries
        self._loaded = True
        for card in self._cards.values():  # записи могли измениться: карточки строим заново
            card.setParent(None)
            card.deleteLater()
        self._cards = {}
        if self._selected is not None and self._entry(self._selected) is None:
            self._selected = None
        self._refilter()

    def show_failure(self):
        self.message.setText(TEXT_LOAD_FAILED)
        self.message.show()

    @property
    def selected_id(self):
        return self._selected

    @property
    def visible_ids(self):
        return [entry.id for entry in self._visible]

    def select(self, entry_id):
        self._selected = entry_id if self._entry(entry_id) is not None else None
        for card_id, card in self._cards.items():
            card.set_selected(card_id == self._selected)
        self._update_device_chip()
        self.detail.show_entry(self._entry(self._selected), self._entries)
        if self._device_only and self._selected is not None:
            self._refilter()

    def _entry(self, entry_id):
        return next((entry for entry in self._entries if entry.id == entry_id), None)

    # --- фильтры ----------------------------------------------------------------
    def _chip(self, text):
        button = QPushButton(text)
        button.setCheckable(True)
        button.setProperty("role", "chip")
        button.setFocusPolicy(Qt.NoFocus)
        return button

    def _set_kind(self, kind):
        self._kind = kind
        for key, button in self.kind_buttons.items():
            button.setChecked(key == kind)
        self._refilter()

    def _on_device_toggled(self):
        self._device_only = self.device_button.isChecked()
        self._refilter()

    def _update_device_chip(self):
        entry = self._entry(self._selected)
        if entry is None:
            self._device_only = False
            self.device_button.setChecked(False)
            self.device_button.hide()
            return
        self.device_button.setText("Устройство: {}".format(entry.device))
        self.device_button.show()

    def _refilter(self):
        entry = self._entry(self._selected)
        device_id = entry.device_id if self._device_only and entry is not None else None
        self._visible = logic.select(self._entries, self.search.text(), self._kind, device_id)
        self._render()

    # --- показ ------------------------------------------------------------------
    def _render(self):
        self._update_device_chip()
        shown = self._visible[:MAX_CARDS]
        keep = {entry.id for entry in shown}
        while self.grid.count():
            self.grid.takeAt(0)
        for card_id, card in self._cards.items():
            if card_id not in keep:
                card.hide()
        for entry in shown:
            card = self._cards.get(entry.id)
            if card is None:
                card = TypeCard(entry, self._cache, self._root, entry.id == self._selected, self.grid_holder)
                card.clicked.connect(self.select)
                self._cards[entry.id] = card
        self._place(shown)
        if not self._entries:
            self.message.setText(TEXT_EMPTY if self._loaded else "")
        elif not self._visible:
            self.message.setText(TEXT_NOTHING)
        else:
            self.message.setText("")
        self.message.setVisible(bool(self.message.text()))
        self.found.setText(_found_text(len(self._visible), len(shown)) if self._entries else "")
        self.detail.show_entry(self._entry(self._selected), self._entries)

    def _place(self, shown):
        width = max(1, self.scroll.viewport().width())
        columns = max(1, (width + GRID_SPACING) // (CARD_MIN_WIDTH + GRID_SPACING))
        self._columns = columns
        for number, entry in enumerate(shown):
            card = self._cards[entry.id]
            self.grid.addWidget(card, number // columns, number % columns)
            card.show()
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)

    def eventFilter(self, watched, event):
        if watched is self.scroll.viewport() and event.type() == QEvent.Resize:
            columns = max(1, (event.size().width() + GRID_SPACING) // (CARD_MIN_WIDTH + GRID_SPACING))
            if columns != self._columns:
                self._render()
        return False

    def showEvent(self, event):
        super().showEvent(event)
        self.shown.emit()
