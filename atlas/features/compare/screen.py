"""Экран сравнения. Окна постоянные: views[0] — эталон, остальные — текущие; раскладка только показывает нужные."""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QPointF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QIcon, QKeySequence, QPainter, QPixmap, QPolygonF
from PyQt5.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from atlas.core import theme
from atlas.features.compare.logic import MAX_WINDOWS, CompareModel, grid_cells, mark_token, neighbor_indexes, position_text
from atlas.shared.viewer.filmstrip import FilmItem, Filmstrip
from atlas.shared.viewer.levels import L1, NEIGHBOR
from atlas.shared.viewer.photo_view import PhotoView
from atlas.shared.viewer.sync_group import SyncGroup

BUTTON_ZOOM = 1.4  # как в макете
LEFT_WIDTH = (240, 280)
RIGHT_WIDTH = (280, 320)
HINT = "Колесо — зум · перетаскивание — сдвиг · двойной клик — вписать · стрелки — листать · пробел — эталон"
STRIP_SETTLE_MS = 150  # миниатюры — после остановки: при удержании стрелки чтение нужно текущему фото
TEXT_NO_FOLDER = "Папка не открыта"
TEXT_NO_PHOTOS = "В папке нет фото"
TAG_REFERENCE = "ЭТАЛОН"
TAG_SINGLE = "ЛИСТАНИЕ"
TAG_CURRENT = "НОВОЕ"


class SlotColumn(QVBoxLayout):
    """Колонка слота: пока панелей нет, места не занимает. SlotRegistry работает только через эти два метода."""

    def __init__(self, holder):
        super().__init__(holder)
        self._holder = holder
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(10)
        holder.hide()

    def addWidget(self, widget, *args):
        super().addWidget(widget, *args)
        self._holder.show()

    def removeWidget(self, widget):
        super().removeWidget(widget)
        self._holder.setVisible(self.count() > 0)


def _arrow_icon(color, step, size=14):
    """Стрелка рисуется кодом: символы вроде треугольника на Windows 7 могут оказаться без шрифта."""
    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    tip, back = (size - 3, 3) if step > 0 else (3, size - 3)
    painter.drawPolygon(QPolygonF([QPointF(back, 2), QPointF(tip, size / 2), QPointF(back, size - 2)]))
    painter.end()
    return QIcon(pixmap)


def _key(text):
    sequence = QKeySequence(text)
    return sequence[0] if sequence.count() else 0


class CompareScreen(QWidget):
    photo_changed = pyqtSignal(object, int)  # PhotoItem, индекс в папке: пользователь перелистал активное окно

    def __init__(self, cache, hotkeys, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)  # стрелки и пробел приходят сюда, кнопки фокус не берут
        self.model = CompareModel()
        self.group = SyncGroup(cache, self)
        self._cache = cache
        self._keys = {_key(hotkeys["prev"]): -1, _key(hotkeys["next"]): 1}
        self._flicker_key = _key(hotkeys["flicker"])
        self._flicker = None  # (окно, его состояние), пока удерживается «мигалка»
        self._portrait = True  # фото Atlas обычно вертикальные; уточняется по первому показанному
        self._orientation_known = False
        self.views = [PhotoView(cache, self) for _ in range(MAX_WINDOWS)]
        for view in self.views:
            view.hide()
            view.installEventFilter(self)
            view.photo_shown.connect(lambda _path, source=view: self._learn_orientation(source))
        self._layout_buttons = {}
        tokens = theme.current()
        self.strip = Filmstrip(cache, {
            "border": tokens.qcolor("border"),
            "active": tokens.qcolor("accent"),
            "empty": tokens.qcolor("photo_bg"),
            "text": tokens.qcolor("text"),
            "text_bg": tokens.qcolor("bg"),
        })
        self.strip.clicked.connect(self.go)
        self._strip_timer = QTimer(self)
        self._strip_timer.setSingleShot(True)
        self._strip_timer.setInterval(STRIP_SETTLE_MS)
        self._strip_timer.timeout.connect(self._on_strip_settled)

        self.left = QWidget()
        self.left.setMinimumWidth(LEFT_WIDTH[0])
        self.left.setMaximumWidth(LEFT_WIDTH[1])
        self.left_layout = SlotColumn(self.left)
        self.right = QWidget()
        self.right.setMinimumWidth(RIGHT_WIDTH[0])
        self.right.setMaximumWidth(RIGHT_WIDTH[1])
        self.right_layout = SlotColumn(self.right)

        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(10)
        self.message = QLabel(TEXT_NO_FOLDER)
        self.message.setProperty("role", "muted")
        self.message.setAlignment(Qt.AlignCenter)
        hint = QLabel(HINT)
        hint.setProperty("role", "muted")

        middle = QVBoxLayout()
        middle.setSpacing(10)
        middle.addWidget(self._build_toolbar())
        middle.addWidget(self.message, 1)
        middle.addLayout(self.grid, 1)
        middle.addWidget(self._build_strip_panel())
        middle.addWidget(hint)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)
        root.addWidget(self.left)
        root.addLayout(middle, 1)
        root.addWidget(self.right)

        self.group.changed.connect(lambda zoom, cx, cy: self._show_zoom(zoom))
        self.set_layout(1)

    # --- сборка ---------------------------------------------------------------
    def _build_toolbar(self):
        bar = QFrame()
        bar.setProperty("role", "panel")
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 8, 8, 8)
        row.setSpacing(6)
        for count in range(1, MAX_WINDOWS + 1):
            button = self._button("{} фото".format(count), lambda _=False, n=count: self.set_layout(n), checkable=True)
            self._layout_buttons[count] = button
            row.addWidget(button)
        row.addWidget(self._separator())
        minus = self._button("−", lambda: self.group.zoom_by(1 / BUTTON_ZOOM))
        minus.setProperty("role", "square")
        row.addWidget(minus)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setProperty("role", "mono")
        self.zoom_label.setMinimumWidth(52)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        row.addWidget(self.zoom_label)
        plus = self._button("+", lambda: self.group.zoom_by(BUTTON_ZOOM))
        plus.setProperty("role", "square")
        row.addWidget(plus)
        row.addWidget(self._button("Вписать", self.fit))
        self.sync_button = self._button("Синхронно", self._on_sync_toggled, checkable=True)
        self.sync_button.setChecked(True)
        row.addWidget(self.sync_button)
        self.toolbar_layout = QHBoxLayout()  # слот compare.toolbar
        self.toolbar_layout.setSpacing(6)
        row.addLayout(self.toolbar_layout)
        row.addStretch(1)
        return bar

    def _build_strip_panel(self):
        self.strip_panel = QFrame()
        self.strip_panel.setProperty("role", "panel")
        row = QHBoxLayout(self.strip_panel)
        row.setContentsMargins(10, 10, 10, 10)
        row.setSpacing(10)
        color = theme.current().qcolor("text")
        self.prev_button = self._arrow_button(color, -1, "Предыдущее фото")
        self.next_button = self._arrow_button(color, 1, "Следующее фото")
        row.addWidget(self.prev_button)
        row.addWidget(self.strip, 1)
        row.addWidget(self.next_button)
        return self.strip_panel

    def _arrow_button(self, color, step, tip):
        button = self._button("", lambda: self.flip(step))
        button.setProperty("role", "square")
        button.setIcon(_arrow_icon(color, step))
        button.setIconSize(QSize(14, 14))
        button.setToolTip(tip)
        return button

    def _button(self, text, action, checkable=False):
        button = QPushButton(text)
        button.setFocusPolicy(Qt.NoFocus)
        button.setCheckable(checkable)
        button.clicked.connect(action)
        return button

    def _separator(self):
        line = QFrame()
        line.setProperty("role", "vsep")
        return line

    # --- содержимое -----------------------------------------------------------
    def set_photos(self, photos):
        """Новая папка: раскладка, зум и режим синхронности сохраняются."""
        self._end_flicker()
        self.model.set_photos(photos)
        self._orientation_known = False
        self.message.setText(TEXT_NO_PHOTOS)
        self.strip.set_items([FilmItem(photo.path, self._mark_color(photo.mark)) for photo in self.model.photos])
        self._apply_layout()
        self._cache.prefetch([photo.path for photo in self.model.photos])

    def show_failure(self, text):
        self._end_flicker()
        self.model.set_photos([])
        self.strip.set_items([])
        self.message.setText(text)
        self._apply_layout()

    def set_reference(self, photo):
        """Заменить эталон. На текущие окна и их индексы это не влияет."""
        self._end_flicker()
        self.model.reference = photo
        self._apply_layout()

    def set_layout(self, count):
        self._end_flicker()
        self.model.set_layout(count)
        for number, button in self._layout_buttons.items():
            button.setChecked(number == count)
        self.sync_button.setEnabled(count > 1)
        self._apply_layout()

    def _mark_color(self, mark):
        token = mark_token(mark)
        return theme.current().qcolor(token) if token else None

    def fit(self):
        self.group.fit()
        self._show_zoom(1.0)

    def _show_zoom(self, zoom):
        self.zoom_label.setText("{:.0f}%".format(zoom * 100))

    def _on_sync_toggled(self, checked):
        self.group.set_enabled(checked)

    def _visible_views(self):
        """Окна раскладки: при одном фото только первое текущее, эталона нет."""
        if self.model.count == 1:
            return [self.views[1]]
        return self.views[:self.model.count]

    def _view_of(self, window):
        return self.views[window + 1]

    def active_view(self):
        return self._view_of(self.model.active)

    def _apply_layout(self):
        has_photos = bool(self.model.photos)
        self.message.setVisible(not has_photos)
        self.strip_panel.setVisible(has_photos)
        visible = self._visible_views() if has_photos else []
        for view in self.views:
            self.grid.removeWidget(view)
            if view not in visible:
                self.group.remove(view)
                view.hide()
                view.clear()
        for view in visible:
            if view not in self.group.views:
                self.group.add(view)
        self.group.set_reference(self.views[0] if has_photos and self.model.count > 1 else None)
        self._place(visible)
        for view in visible:
            view.show()
            self._show_in(view)
        self._mark_active()
        self._sync_strip()

    def _sync_strip(self):
        self.strip.set_current(self.model.active_index)
        self.prev_button.setEnabled(self.model.active_index > 0)
        self.next_button.setEnabled(self.model.active_index < len(self.model.photos) - 1)

    def _after_show(self):
        """show_photo отменил очередь: соседей просим сразу, миниатюры — когда листание остановится."""
        self._request_neighbors()
        self._strip_timer.start()

    def _on_strip_settled(self):
        self.strip.request_visible()
        self._request_neighbors()  # последними: в очереди новые идут первыми, соседи важнее миниатюр

    def _request_neighbors(self):
        """Самое важное — последним, в очереди новые идут первыми. Эталон — для «мигалки», при 1 фото его нет на экране."""
        model = self.model
        wanted = [model.photos[number] for number in neighbor_indexes(model.active_index, len(model.photos), model.direction)]
        if model.reference is not None:
            wanted.append(model.reference)
        for photo in reversed(wanted):
            self._cache.get(photo.path, L1, NEIGHBOR)

    def _place(self, visible):
        for line in range(MAX_WINDOWS):
            self.grid.setRowStretch(line, 0)
            self.grid.setColumnStretch(line, 0)
        for view, (row, column, rows, columns) in zip(visible, grid_cells(len(visible), self._portrait)):
            self.grid.addWidget(view, row, column, rows, columns)
            self.grid.setRowStretch(row, 1)
            self.grid.setColumnStretch(column, 1)

    def _show_in(self, view):
        if view is self.views[0]:
            photo = self.model.reference
            self.group.show_photo(view, photo.path)
            view.set_caption(TAG_REFERENCE, photo.name, reference=True)
            self._after_show()
            return
        window = self.views.index(view) - 1
        photo = self.model.current(window)
        self.group.show_photo(view, photo.path)
        tag = TAG_SINGLE if self.model.count == 1 else TAG_CURRENT
        position = position_text(self.model.index(window), len(self.model.photos))
        view.set_caption(tag, "{}  {}".format(position, photo.name))
        self._after_show()

    def _mark_active(self):
        for view in self.views:
            active = self.model.count > 1 and view is self.active_view()
            if view.property("active") != active:
                view.setProperty("active", active)
                view.style().unpolish(view)
                view.style().polish(view)
                view.update()

    def _learn_orientation(self, view):
        """Один раз на папку: при листании сетка не должна прыгать, даже если попалось фото другой ориентации."""
        if self._orientation_known or view is self.views[0]:
            return
        size = view.shown_image_size
        if size is None:
            return
        self._orientation_known = True
        portrait = size[1] >= size[0]
        self.strip.set_portrait(portrait)
        if portrait != self._portrait:
            self._portrait = portrait
            visible = self._visible_views()
            for item in visible:
                self.grid.removeWidget(item)
            self._place(visible)

    # --- листание и «мигалка» -------------------------------------------------
    def flip(self, step):
        self.go(self.model.active_index + step)

    def go(self, index):
        """Перейти в активном окне к фото с этим номером: стрелки, кнопки, клик по ленте."""
        if self._flicker is not None or not self.model.go(index):
            return
        self._show_in(self.active_view())
        self._sync_strip()
        window = self.model.active
        self.photo_changed.emit(self.model.current(window), self.model.index(window))

    def _begin_flicker(self):
        if self._flicker is not None or self.model.reference is None:
            return
        view = self.active_view()
        self._flicker = (view, view.state())
        self.group.show_photo(view, self.model.reference.path)
        view.set_caption(TAG_REFERENCE, self.model.reference.name, reference=True)

    def _end_flicker(self):
        if self._flicker is None:
            return
        view, state = self._flicker
        self._flicker = None
        self._show_in(view)
        if not self.group.enabled:  # иначе место вернёт группа
            view.set_state(*state)

    @property
    def flickering(self):
        return self._flicker is not None

    def keyPressEvent(self, event):
        key = event.key()
        if key in self._keys:
            self.flip(self._keys[key])  # удержание — это автоповтор, он и листает
        elif key == self._flicker_key:
            if not event.isAutoRepeat():
                self._begin_flicker()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == self._flicker_key:
            if not event.isAutoRepeat():
                self._end_flicker()
        else:
            super().keyReleaseEvent(event)

    # --- мышь и служебное -----------------------------------------------------
    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress and watched in self.views:
            self._on_view_clicked(watched)
        return False

    def _on_view_clicked(self, view):
        self.setFocus()
        self.group.touch(view)
        if view is self.views[0] or self._flicker is not None:
            return  # эталон не листается: активным остаётся прежнее окно
        self.model.set_active(self.views.index(view) - 1)
        self._mark_active()
        self._sync_strip()
        self._after_show()

    def showEvent(self, event):
        super().showEvent(event)
        self.setFocus()

    # Отпускание пробела сюда уже не придёт, а эталон нельзя оставлять на экране под видом текущего фото
    def hideEvent(self, event):
        self._end_flicker()
        super().hideEvent(event)

    def focusOutEvent(self, event):
        self._end_flicker()
        super().focusOutEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.ActivationChange and not self.isActiveWindow():
            self._end_flicker()
        super().changeEvent(event)
