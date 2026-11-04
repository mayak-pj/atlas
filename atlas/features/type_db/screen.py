"""Вкладка «БД»: внутри «База типов» и «Замечания», общий поиск, фильтры, сетка карточек, карточка типа справа.

Данные приходят готовыми (`set_entries`): записи таблицы types и замечания — отметки фото из «Сравнения».
"""
from __future__ import annotations

from dataclasses import replace

from PyQt5.QtCore import QEvent, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPainter
from PyQt5.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QTabBar, QVBoxLayout, QWidget,
)

from atlas.core import theme
from atlas.features.type_db import logic
from atlas.features.type_db.photo_window import PhotoWindow
from atlas.shared.viewer.levels import L1
from atlas.shared.widgets import StampAnimation
from atlas.shared.widgets import stamp as stamp_math
from atlas.shared.widgets.icons import set_icon

MAX_CARDS = 60  # больше виджетов сразу не строим: поиск уточняют, а не листают сотни карточек
CARD_MIN_WIDTH = 340
GRID_SPACING = 12
THUMB_HEIGHT = 240
DETAIL_PHOTO_HEIGHT = 260
DETAIL_CROP_HEIGHT = 150
PLACEHOLDER = "Поиск сразу по типам и замечаниям: деталь, артикул, устройство, SN, описание…"
TEXT_TAB_TYPES = "База типов"
TEXT_TAB_REMARKS = "Замечания"
TEXT_SEARCH_BOTH = "Ищу в обеих базах"
TEXT_EMPTY_REMARKS = "Замечаний пока нет: они появляются сами, когда фото отмечают «Замечание» на экране сравнения"
TEXT_KIND_NONE = "Вид не указан"
TEXT_DELETE = "Удалить из БД насовсем"
TEXT_ADD_FILE = "Добавить из файла…"
TIP_ADD_FILE = "Внести в базу типов фото с диска, без экрана сравнения: старые типы, накопленные раньше"
TEXT_ALL = "Все проекты"
TEXT_ARCHIVE_NOTE = "Архив — всегда внизу"
TEXT_EMPTY = "В базе типов пока ничего нет: добавьте тип кнопкой «+ В базу типов» на экране сравнения"
TEXT_NOTHING = "Ничего не найдено"
TEXT_PICK = "Выберите карточку слева"
TEXT_NO_FILE = "Нет фото"
TEXT_LOAD_FAILED = "Не удалось прочитать базу типов: показаны прежние данные"
TEXT_ARCHIVED = "В архиве"
TEXT_ACTIVE = "Действует"
TEXT_TO_ARCHIVE = "В архив"
TEXT_FROM_ARCHIVE = "Вернуть из архива"


def _found_text(count, shown):
    return "Найдено: {}".format(count) if count == shown else "Показано {} из {}".format(shown, count)


class ThumbView(QWidget):
    """Картинка по пути: уровень L1 из общего кэша, читается в фоне; рисуется по центру с сохранением пропорций."""
    open_requested = pyqtSignal(str)  # двойной клик: открыть это фото большим

    def __init__(self, cache, height, parent=None, fill=False):
        """fill — заполнить окно целиком, лишнее по краям обрезать (миниатюры в сетке); иначе фото целиком с полями."""
        super().__init__(parent)
        self.fill = fill
        self.setObjectName("PhotoView")  # тот же фон и скругление, что у окна просмотра
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(height)
        self._cache = cache
        self._path = None
        self._image = None
        self._failed = False
        self._frame = stamp_math.COLOR  # серый вид и печать архива
        self._gray = None
        self._gray_key = None
        cache.ready.connect(self._on_ready)
        cache.failed.connect(self._on_failed)

    def show_frame(self, frame):
        """Серость и печать архива: итоговый вид (`stamp.final_frame`) или кадр анимации."""
        self._frame = frame
        self.update()

    @property
    def frame(self):
        return self._frame

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

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self._path:
            self.open_requested.emit(self._path)
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self._image is None:
            painter.setPen(theme.current().qcolor("muted"))
            painter.drawText(self.rect(), Qt.AlignCenter, TEXT_NO_FILE if self._failed else "")
            return
        area = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        target, source = self._placement(area)
        painter.drawImage(target, self._image, source)
        frame = self._frame
        if frame.gray > 0:
            painter.setOpacity(frame.gray)
            painter.drawImage(target, self._gray_image(), source)
            painter.setOpacity(frame.gray * stamp_math.DIM)
            painter.fillRect(target, theme.current().qcolor("photo_bg"))
            painter.setOpacity(1.0)
        stamp_math.paint_stamp(painter, QRectF(self.rect()), frame, theme.current().qcolor("defect"))

    def _placement(self, area):
        """(куда рисовать, какую часть картинки). fill — без чёрных полос: середина фото на всё окно."""
        image_w, image_h = float(self._image.width()), float(self._image.height())
        if self.fill:
            scale = max(area.width() / image_w, area.height() / image_h)
            source_w, source_h = area.width() / scale, area.height() / scale
            source = QRectF((image_w - source_w) / 2, (image_h - source_h) / 2, source_w, source_h)
            return area, source
        scale = min(area.width() / image_w, area.height() / image_h)
        width, height = image_w * scale, image_h * scale
        target = QRectF(area.center().x() - width / 2, area.center().y() - height / 2, width, height)
        return target, QRectF(0, 0, image_w, image_h)

    def _gray_image(self):
        key = self._image.cacheKey()
        if self._gray_key != key:
            self._gray_key = key
            self._gray = self._image.convertToFormat(QImage.Format_Grayscale8).convertToFormat(QImage.Format_RGB32)
        return self._gray


class TypeCard(QFrame):
    clicked = pyqtSignal(int)
    archive_clicked = pyqtSignal(int)
    delete_clicked = pyqtSignal(int)
    animation_done = pyqtSignal(int)

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
        self.thumb = ThumbView(cache, THUMB_HEIGHT, fill=True)  # без полос по бокам; целиком — справа и по двойному клику
        self.thumb.set_path(root / (entry.crop_rel or entry.photo_rel))  # вырезка, если есть: так виден сам тип
        self.thumb.show_frame(stamp_math.final_frame(entry.archived))
        layout.addWidget(self.thumb)
        self._layout = layout
        self._animation = StampAnimation(self, self._on_frame, lambda: self.animation_done.emit(self.entry.id))
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
        self.delete_button = QPushButton("")
        self.delete_button.setProperty("role", "square")
        set_icon(self.delete_button, "x", "text_dim")
        self.delete_button.setToolTip(TEXT_DELETE)
        self.delete_button.setFocusPolicy(Qt.NoFocus)
        self.delete_button.clicked.connect(lambda _=False: self.delete_clicked.emit(self.entry.id))
        head.addWidget(self.delete_button)
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
        self.archive_button = QPushButton(TEXT_FROM_ARCHIVE if entry.archived else TEXT_TO_ARCHIVE)
        self.archive_button.setProperty("role", "restore" if entry.archived else "archive")
        set_icon(self.archive_button, "archive-restore" if entry.archived else "archive", "ok" if entry.archived else "defect")
        self.archive_button.setFocusPolicy(Qt.NoFocus)
        self.archive_button.clicked.connect(lambda _=False: self.archive_clicked.emit(self.entry.id))
        body.addWidget(self.archive_button)
        layout.addLayout(body)
        self.setToolTip("{} › {} › {}".format(entry.project, entry.device, entry.part_name))

    def set_selected(self, selected):
        self.setProperty("on", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)

    @property
    def animating(self):
        return self._animation.running

    def play(self, restoring):
        """Анимация «в архив» (серость, печать, «удар») или обратно; в конце — animation_done."""
        self.archive_button.setEnabled(False)
        self._animation.start(restoring)

    def stop_animation(self):
        self._animation.stop()

    def _on_frame(self, frame):
        self.thumb.show_frame(frame)
        self._layout.setContentsMargins(0, int(round(frame.thud)), 0, 0)  # «удар»: содержимое чуть сдвигается вниз

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.entry.id)
        super().mousePressEvent(event)


class RemarkCard(QFrame):
    """Замечание — отметка фото в «Сравнении»: само фото из папки проверки, деталь, вид, SN, кто и когда."""

    def __init__(self, entry, cache, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.setProperty("role", "type-card")
        self.setProperty("on", False)
        self.setProperty("archived", False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.thumb = ThumbView(cache, THUMB_HEIGHT, fill=True)  # без полос по бокам; целиком — справа и по двойному клику
        self.thumb.set_path(entry.path)
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
        self.pill.setProperty("tone", entry.tone)
        head.addWidget(self.pill)
        body.addLayout(head)
        self.description = QLabel(entry.defect_kind or TEXT_KIND_NONE)
        self.description.setWordWrap(True)
        self.description.setProperty("role", "dim")
        body.addWidget(self.description)
        meta = " · ".join(part for part in ("SN " + entry.sn if entry.sn else "", entry.date_text, entry.author) if part)
        self.meta = QLabel(meta)
        self.meta.setProperty("role", "mono")
        body.addWidget(self.meta)
        layout.addLayout(body)
        self.setToolTip("{} › {} › {}\n{}".format(entry.project, entry.device, entry.part_name, entry.path))

    def stop_animation(self):
        pass


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
        self.body.setProperty("role", "plain")  # без этого QSS красит обёртку в цвет фона, и она видна прямоугольником на панели
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
        self.photo.show_frame(stamp_math.final_frame(entry.archived))
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
        self.description.setText(entry.description or "—")
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
    archive_toggled = pyqtSignal(int, bool)  # запись, True — в архив / False — вернуть: записать в базу
    delete_requested = pyqtSignal(int)  # крестик на карточке: спросить и удалить
    add_file_requested = pyqtSignal()  # «+ Добавить из файла…»

    def __init__(self, cache, root, kinds, animations=True, parent=None):
        super().__init__(parent)
        self._animations = animations
        self._pending = None  # свежие данные, пришедшие во время анимации: сетка перестроится после неё
        self._animating = set()
        self._cache = cache
        self._root = root
        self._entries = []
        self._remarks = []
        self._tab = logic.TAB_TYPES
        self._visible = []
        self._cards = {}
        self._remark_cards = {}
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
        self.add_file_button = QPushButton(TEXT_ADD_FILE)
        self.add_file_button.setToolTip(TIP_ADD_FILE)
        set_icon(self.add_file_button, "folder-plus", "text")
        self.add_file_button.setFocusPolicy(Qt.NoFocus)
        self.add_file_button.clicked.connect(lambda _=False: self.add_file_requested.emit())
        search_row.addWidget(self.add_file_button)

        # Две базы внутри «БД»: по умолчанию «База типов». С запросом вкладки прячутся: ищется сразу в обеих
        self.tabs = QTabBar()
        self.tabs.addTab(TEXT_TAB_TYPES)
        self.tabs.addTab(TEXT_TAB_REMARKS)
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.setFocusPolicy(Qt.NoFocus)
        self.tabs.currentChanged.connect(self._on_tab)
        self.both_note = QLabel(TEXT_SEARCH_BOTH)
        self.both_note.setProperty("role", "muted")
        self.both_note.hide()
        tabs_row = QHBoxLayout()
        tabs_row.addWidget(self.tabs)
        tabs_row.addWidget(self.both_note)
        tabs_row.addStretch(1)

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
        middle.addLayout(tabs_row)
        middle.addLayout(chips)
        middle.addWidget(self.message)
        middle.addWidget(self.scroll, 1)
        self.detail = DetailPanel(cache, root)
        self.detail.photo.open_requested.connect(self.open_photo)
        self.detail.crop.open_requested.connect(self.open_photo)
        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(14)
        root_layout.addLayout(middle, 1)
        root_layout.addWidget(self.detail)
        self._render()

    # --- данные -----------------------------------------------------------------
    def set_entries(self, entries, remarks=()):
        entries, remarks = list(entries), list(remarks)
        if self._animating:
            self._pending = (entries, remarks)  # карточка играет анимацию: перестройка её оборвала бы
            return
        if self._loaded and entries == self._entries and remarks == self._remarks:
            return  # ничего не изменилось: не перестраиваем сетку и не мигаем при каждом открытии вкладки
        self._entries = entries
        self._remarks = remarks
        self._loaded = True
        self._drop_cards()  # записи могли измениться: карточки строим заново
        if self._selected is not None and self._entry(self._selected) is None:
            self._selected = None
        self._refilter()

    def _drop_cards(self):
        for card in list(self._cards.values()) + list(self._remark_cards.values()):
            card.stop_animation()
            card.setParent(None)
            card.deleteLater()
        self._cards = {}
        self._remark_cards = {}

    # --- архив ----------------------------------------------------------------------
    def apply_archive(self, entry_id, archived, archived_at):
        """База подтвердила: запись в архиве (archived_at — время из базы) или возвращена. Играет анимацию карточки."""
        entry = self._entry(entry_id)
        if entry is None:
            return
        self._entries = [replace(item, archived_at=archived_at if archived else None) if item.id == entry_id else item
                         for item in self._entries]
        if self._selected == entry_id:
            self.detail.show_entry(self._entry(entry_id), self._entries)
        card = self._cards.get(entry_id)
        if card is None or not self._animations or not card.isVisible():
            self._reorder()
            return
        self._animating.add(entry_id)
        card.play(restoring=not archived)

    def archive_failed(self, entry_id):
        card = self._cards.get(entry_id)
        if card is not None:
            card.archive_button.setEnabled(True)

    def _on_archive_clicked(self, entry_id):
        entry = self._entry(entry_id)
        card = self._cards.get(entry_id)
        if entry is None or card is None or entry_id in self._animating:
            return
        card.archive_button.setEnabled(False)  # пока база отвечает, второй раз нажать нельзя
        self.archive_toggled.emit(entry_id, not entry.archived)

    def _on_animation_done(self, entry_id):
        self._animating.discard(entry_id)
        if not self._animating:
            self._reorder()

    def _reorder(self):
        """Карточки заново: архивная уходит вниз, у остальных обновляются кнопки и пометки."""
        pending, self._pending = self._pending, None
        self._drop_cards()
        if pending is not None:
            self._entries, self._remarks = pending
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
        """Записи types в порядке выдачи (замечания — отметки фото — сюда не входят)."""
        return [entry.id for entry in self._visible if not logic.is_remark(entry)]

    @property
    def visible(self):
        return list(self._visible)

    @property
    def tab(self):
        return self._tab

    def set_tab(self, tab):
        self.tabs.setCurrentIndex(0 if tab == logic.TAB_TYPES else 1)

    def _on_tab(self, index):
        self._tab = logic.TAB_TYPES if index == 0 else logic.TAB_REMARKS
        self._refilter()

    def known_names(self):
        """Уже известные проекты, устройства и детали — подсказки в окне «Добавить из файла»."""
        items = list(self._entries) + list(self._remarks)
        return {"project": [item.project for item in items], "device": [item.device for item in items],
                "part": [item.part_name for item in items]}

    def entry(self, entry_id):
        """Запись types по id или None."""
        return self._entry(entry_id)

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
        self._visible = logic.select_db(self._entries, self._remarks, self.search.text(), self._kind, device_id, self._tab)
        searching = bool(self.search.text().strip())
        self.tabs.setVisible(not searching)
        self.both_note.setVisible(searching)
        self._render()

    # --- показ ------------------------------------------------------------------
    def _render(self):
        self._update_device_chip()
        shown = self._visible[:MAX_CARDS]
        keep = {entry.id for entry in shown if not logic.is_remark(entry)}
        keep_remarks = {entry.photo_id for entry in shown if logic.is_remark(entry)}
        while self.grid.count():
            self.grid.takeAt(0)
        for card_id, card in self._cards.items():
            if card_id not in keep:
                card.hide()
        for photo_id, card in self._remark_cards.items():
            if photo_id not in keep_remarks:
                card.hide()
        for entry in shown:
            if logic.is_remark(entry):
                if entry.photo_id not in self._remark_cards:
                    card = RemarkCard(entry, self._cache, self.grid_holder)
                    card.thumb.open_requested.connect(self.open_photo)
                    self._remark_cards[entry.photo_id] = card
                continue
            card = self._cards.get(entry.id)
            if card is None:
                card = TypeCard(entry, self._cache, self._root, entry.id == self._selected, self.grid_holder)
                card.clicked.connect(self.select)
                card.thumb.open_requested.connect(self.open_photo)
                card.archive_clicked.connect(self._on_archive_clicked)
                card.delete_clicked.connect(self.delete_requested.emit)
                card.animation_done.connect(self._on_animation_done)
                self._cards[entry.id] = card
        self._place(shown)
        searching = bool(self.search.text().strip())
        if not searching and self._tab == logic.TAB_REMARKS and not self._visible and self._loaded and not self._kind:
            self.message.setText(TEXT_EMPTY_REMARKS)
        elif not self._entries and not self._remarks:
            self.message.setText(TEXT_EMPTY if self._loaded else "")
        elif not self._visible:
            self.message.setText(TEXT_NOTHING)
        else:
            self.message.setText("")
        self.message.setVisible(bool(self.message.text()))
        self.found.setText(_found_text(len(self._visible), len(shown)) if self._entries or self._remarks else "")
        self.detail.show_entry(self._entry(self._selected), self._entries)

    def open_photo(self, path):
        """Двойной клик по фото: большое окно с зумом и сдвигом."""
        self.photo_window = PhotoWindow(self._cache, path, self)
        self.photo_window.show()

    def _place(self, shown):
        width = max(1, self.scroll.viewport().width())
        columns = max(1, (width + GRID_SPACING) // (CARD_MIN_WIDTH + GRID_SPACING))
        self._columns = columns
        for number, entry in enumerate(shown):
            card = self._remark_cards[entry.photo_id] if logic.is_remark(entry) else self._cards[entry.id]
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
