"""Экран «Правила» и панель «Правила к детали». Только рисуют готовые данные, в базу не ходят."""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QEvent, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QImageReader, QPainter, QPalette, QPixmap
from PyQt5.QtWidgets import (
    QButtonGroup, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QGridLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from atlas.features.rules import logic
from atlas.features.rules.cards import RuleTile
from atlas.shared.widgets.flow import FlowLayout
from atlas.shared.widgets.icons import set_icon

TEXT_NEW = "НОВОЕ"
TEXT_READ = "Прочитано"
TEXT_READ_ALL = "Отметить все прочитанными"
TEXT_EMPTY = "Правил пока нет"
TEXT_EMPTY_FILTER = "По этому фильтру правил нет"
TEXT_FORM = "Новое правило"
TEXT_FORM_EDIT = "Изменить правило"
TEXT_SAVE_EDIT = "Сохранить изменения"
TEXT_CANCEL_EDIT = "Отмена"
TEXT_EDIT_SCOPE = "Область не меняется: {}"
TEXT_DELETE_ASK = "Удалить правило «{}» насовсем? Фото правила тоже удалятся. Чтобы убрать, но сохранить, — «В архив»."
CARD_MIN_WIDTH = 360
GRID_SPACING = 12
TEXT_TITLE = "Заголовок"
TEXT_TITLE_HINT = "Коротко, что проверять"
TEXT_SCOPE = "Относится к"
TEXT_BODY = "Общий комментарий"
TEXT_BODY_HINT = "Один комментарий ко всем приложенным фото"
TEXT_ATTACH = "Приложить фото"
TEXT_PUBLISH = "Опубликовать"
TEXT_PUBLISHING = "Сохраняю…"
TEXT_NOTE = "После публикации у коллег вкладка «Правила» подсветится, а правило к детали покажется в сводке на экране сравнения."
TEXT_NO_PART = "Откройте папку — тогда правило можно привязать к виду, проекту, устройству или детали"
TEXT_PANEL = "Правила к детали"
TEXT_PHOTOS = "Фото: {}"
TEXT_PHOTO_TITLE = "Фото правила"
TILE_MAX_HEIGHT = 420
ATTACH_PREVIEW = 64
TEXT_DROP_PHOTOS = "Убрать фото"
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


class _Tile(QWidget):
    """Фото правила крупной плиткой: по ширине ячейки, высота по пропорциям. Клик — открыть в окне просмотра."""

    clicked = pyqtSignal(int)

    def __init__(self, index, path):
        super().__init__()
        self.index = index
        self.pixmap = QPixmap(str(path))
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)

    def _ratio(self):
        if self.pixmap.isNull() or self.pixmap.width() == 0:
            return 0.75
        return self.pixmap.height() / float(self.pixmap.width())

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return min(int(width * self._ratio()), TILE_MAX_HEIGHT)

    def sizeHint(self):
        return QSize(120, self.heightForWidth(120))

    def minimumSizeHint(self):
        return QSize(60, 40)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.pixmap.isNull():
            painter.setPen(self.palette().color(QPalette.Mid))
            painter.drawText(self.rect(), Qt.AlignCenter, "нет файла")
            return
        scaled = self.pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawPixmap((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.index)


class ZoomView(QWidget):
    """Одно фото: колесо — зум к курсору, мышь — сдвиг, двойной клик — вписать."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap = QPixmap()
        self.zoom = 1.0
        self.offset = QPointF(0, 0)
        self._drag = None
        self.setMinimumSize(640, 480)
        self.setCursor(Qt.OpenHandCursor)

    def set_pixmap(self, pixmap):
        self.pixmap = pixmap
        self.fit()

    def fit(self):
        if self.pixmap.isNull():
            self.zoom = 1.0
        else:
            self.zoom = min(self.width() / float(self.pixmap.width()), self.height() / float(self.pixmap.height()))
        self.offset = QPointF(0, 0)
        self.update()

    def _origin(self):
        return QPointF((self.width() - self.pixmap.width() * self.zoom) / 2.0 + self.offset.x(),
                       (self.height() - self.pixmap.height() * self.zoom) / 2.0 + self.offset.y())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().color(QPalette.Window))
        if self.pixmap.isNull():
            painter.drawText(self.rect(), Qt.AlignCenter, "Не удалось открыть фото")
            return
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        origin = self._origin()
        painter.drawPixmap(QRectF(origin.x(), origin.y(), self.pixmap.width() * self.zoom, self.pixmap.height() * self.zoom),
                           self.pixmap, QRectF(self.pixmap.rect()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._drag is None:
            self.fit()

    def wheelEvent(self, event):
        if self.pixmap.isNull():
            return
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        new_zoom = max(0.05, min(self.zoom * factor, 8.0))
        factor = new_zoom / self.zoom
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        cursor = QPointF(event.pos()) - center
        self.offset = cursor - (cursor - self.offset) * factor  # точка под курсором остаётся на месте
        self.zoom = new_zoom
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = (QPointF(event.pos()), QPointF(self.offset))
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            self.offset = self._drag[1] + (QPointF(event.pos()) - self._drag[0])
            self.update()

    def mouseReleaseEvent(self, event):
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self, event):
        self.fit()


class PhotoDialog(QDialog):
    """Просмотр фото правила: зум, сдвиг, листание стрелками, полоса миниатюр внизу."""

    def __init__(self, root, rels, index=0, parent=None):
        super().__init__(parent)
        self.root, self.rels, self.index = Path(root), list(rels), 0
        self.setWindowTitle(TEXT_PHOTO_TITLE)
        layout = QVBoxLayout(self)
        self.view = ZoomView()
        layout.addWidget(self.view, 1)
        bar = QHBoxLayout()
        self.prev_button = QPushButton("Назад")
        self.next_button = QPushButton("Вперёд")
        self.fit_button = QPushButton("Сбросить")
        set_icon(self.fit_button, "scan", "text")
        self.fit_button.setToolTip("Всё фото целиком")
        self.count_label = _label("", "muted", wrap=False)
        for button in (self.prev_button, self.next_button, self.fit_button):
            button.setFocusPolicy(Qt.NoFocus)
        self.prev_button.clicked.connect(lambda _=False: self.step(-1))
        self.next_button.clicked.connect(lambda _=False: self.step(1))
        self.fit_button.clicked.connect(lambda _=False: self.view.fit())
        bar.addWidget(self.prev_button)
        bar.addWidget(self.next_button)
        bar.addWidget(self.fit_button)
        bar.addWidget(self.count_label)
        bar.addStretch(1)
        bar.addWidget(_label("Колесо — приблизить, мышь — двигать, двойной клик — фото целиком", "muted", wrap=False))
        layout.addLayout(bar)
        self.resize(1000, 760)
        self.show_index(index)

    def show_index(self, index):
        if not self.rels:
            return
        self.index = max(0, min(index, len(self.rels) - 1))
        self.view.set_pixmap(QPixmap(str(self.root / self.rels[self.index])))
        self.count_label.setText("{} из {}".format(self.index + 1, len(self.rels)))
        self.prev_button.setEnabled(self.index > 0)
        self.next_button.setEnabled(self.index < len(self.rels) - 1)

    def step(self, delta):
        self.show_index(self.index + delta)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Left, Qt.Key_Up):
            self.step(-1)
        elif event.key() in (Qt.Key_Right, Qt.Key_Down, Qt.Key_Space):
            self.step(1)
        else:
            super().keyPressEvent(event)


def photo_columns(count, compact=False):
    """Сколько плиток в ряду: 2 и 4 фото — по две (крупнее), 3 — в ряд, в узкой панели — по две."""
    if count <= 1:
        return 1
    if compact or count in (2, 4):
        return 2
    return 3


class RuleCard(QFrame):
    read_clicked = pyqtSignal(int)
    photo_clicked = pyqtSignal(object, int)  # все фото правила (относительные пути), номер нажатого

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
            column.addWidget(_photos_widget(self, rule.photos, root, compact))
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


def _photos_widget(self, rels, root, compact):
    holder = QWidget()
    holder.setProperty("role", "plain")
    grid = QGridLayout(holder)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(6)
    columns = photo_columns(len(rels), compact)
    for number, rel in enumerate(rels):
        tile = _Tile(number, Path(root) / logic.thumb_rel(rel))
        tile.clicked.connect(lambda index, all_rels=tuple(rels): self.photo_clicked.emit(all_rels, index))
        grid.addWidget(tile, number // columns, number % columns)
    for column in range(columns):
        grid.setColumnStretch(column, 1)
    return holder


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
    archive_requested = pyqtSignal(int, bool)  # правило, True — в архив
    delete_requested = pyqtSignal(int)
    update_requested = pyqtSignal(int, str, str, tuple, tuple)  # правило, заголовок, текст, оставленные фото, новые

    def __init__(self, root, kinds, today=None, animations=True, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.today = today
        self.animations = animations
        self.rules, self.names, self.part, self.colors = [], {}, None, {}
        self.cards = {}
        self._columns = 0
        self._animating = set()
        self._pending = None  # данные, пришедшие во время анимации
        self.editing = None  # правило, которое сейчас меняют в форме
        self.keep_rels = []  # его фото, которые оставляем
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
        self.grid = QGridLayout(body)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(GRID_SPACING)
        self.grid.setAlignment(Qt.AlignTop)
        self.grid_holder = body
        self.empty_label = _label("", "muted")
        self.scroll.setWidget(body)
        self.scroll.viewport().installEventFilter(self)
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
        self.form_title = _label(TEXT_FORM, "caption")
        column.addWidget(self.form_title)
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
        self.previews = QWidget()
        self.previews.setProperty("role", "plain")
        self.previews_layout = FlowLayout(self.previews, spacing=4)
        column.addWidget(self.previews)
        self.drop_button = QPushButton(TEXT_DROP_PHOTOS)
        self.drop_button.setFocusPolicy(Qt.NoFocus)
        self.drop_button.clicked.connect(lambda _=False: self.drop_photos())
        column.addWidget(self.drop_button)
        self.publish_button = QPushButton(TEXT_PUBLISH)
        self.publish_button.setProperty("role", "primary")
        self.publish_button.setFocusPolicy(Qt.NoFocus)
        self.publish_button.clicked.connect(lambda _=False: self.publish())
        column.addWidget(self.publish_button)
        self.cancel_edit_button = QPushButton(TEXT_CANCEL_EDIT)
        self.cancel_edit_button.setFocusPolicy(Qt.NoFocus)
        self.cancel_edit_button.clicked.connect(lambda _=False: self.finish_edit())
        self.cancel_edit_button.hide()
        column.addWidget(self.cancel_edit_button)
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
        if self.editing is not None:  # область правила не меняется: она привязана к детали, открытой при создании
            for scope, button in self.scope_buttons.items():
                button.setEnabled(False)
                button.setChecked(scope == self.editing.scope)
            self.scope_note.setText(TEXT_EDIT_SCOPE.format(logic.scope_text(self.editing)))
            count = len(self.keep_rels) + len(self.photo_paths)
            self.photos_label.setText(TEXT_PHOTOS.format(count) if count else "")
            self.drop_button.setVisible(bool(count))
            self._render_previews()
            return
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
        self.drop_button.setVisible(bool(self.photo_paths))
        self._render_previews()

    def _render_previews(self):
        while self.previews_layout.count():
            item = self.previews_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        paths = [str(self.root / logic.thumb_rel(rel)) for rel in self.keep_rels] if self.editing is not None else []
        for path in paths + list(self.photo_paths):
            reader = QImageReader(path)  # JPEG читается сразу уменьшенным: GUI не ждёт полного декодирования
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():
                size.scale(ATTACH_PREVIEW * 2, ATTACH_PREVIEW * 2, Qt.KeepAspectRatio)
                reader.setScaledSize(size)
            image = reader.read()
            label = QLabel()
            label.setProperty("role", "thumb")
            if image.isNull():
                label.setText("?")
            else:
                label.setPixmap(QPixmap.fromImage(image).scaledToHeight(ATTACH_PREVIEW, Qt.SmoothTransformation))
            self.previews_layout.addWidget(label)

    def drop_photos(self):
        self.photo_paths = []
        self.keep_rels = []
        self._refresh_form()

    def attach(self, paths=None):
        if paths is None:
            paths, _ = QFileDialog.getOpenFileNames(self, TEXT_ATTACH, "", IMAGE_FILTER)
        for path in paths:
            if path not in self.photo_paths and len(self.photo_paths) + len(self.keep_rels) < logic.MAX_PHOTOS:
                self.photo_paths.append(path)
        self._refresh_form()

    def publish(self):
        if self.editing is not None:
            draft = logic.Draft(logic.SCOPE_GENERAL, self.title_edit.text(), self.body_edit.toPlainText())
            try:
                logic.checked(draft)
            except logic.RuleError as exc:
                self.show_error(str(exc))
                return
            self.show_error("")
            self.set_busy(True)
            self.update_requested.emit(self.editing.id, self.title_edit.text(), self.body_edit.toPlainText(),
                                       tuple(self.keep_rels), tuple(self.photo_paths))
            return
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
        idle = TEXT_SAVE_EDIT if self.editing is not None else TEXT_PUBLISH
        self.publish_button.setText(TEXT_PUBLISHING if busy else idle)

    def edit_rule(self, rule_id):
        """Правило — в форму справа: заголовок, текст, его фото (можно убрать и добавить). Область — прежняя."""
        rule = next((item for item in self.rules if item.id == rule_id), None)
        if rule is None:
            return
        self.editing = rule
        self.keep_rels = list(rule.photos)
        self.photo_paths = []
        self.title_edit.setText(rule.title)
        self.body_edit.setPlainText(rule.body)
        self.form_title.setText(TEXT_FORM_EDIT)
        self.cancel_edit_button.show()
        self.show_error("")
        self.set_busy(False)
        self._refresh_form()
        self.title_edit.setFocus()

    def finish_edit(self):
        """Изменение сохранено или отменено: форма снова для нового правила."""
        self.editing = None
        self.keep_rels = []
        self.form_title.setText(TEXT_FORM)
        self.cancel_edit_button.hide()
        self.clear_form()
        self.set_busy(False)

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

    def set_data(self, rules, names, part, colors=None):
        if self._animating:
            self._pending = (rules, names, part, colors)  # перестройка оборвала бы печать или «сгорание»
            return
        self.rules, self.names, self.part, self.colors = rules, names, part, dict(colors or {})
        self._refresh_form()
        self._render()

    def _set_filter(self, key):
        self.filter_key = key
        self._render()

    def _render(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self.empty_label:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.cards = {}
        shown = logic.filtered(self.rules, self.filter_key)
        if not shown:
            self.empty_label.setText(TEXT_EMPTY if not self.rules else TEXT_EMPTY_FILTER)
            self.grid.addWidget(self.empty_label, 0, 0)
            self.empty_label.show()
        else:
            self.empty_label.hide()
        columns = self._columns_for(self.scroll.viewport().width())
        self._columns = columns
        for number, rule in enumerate(shown):
            card = RuleTile(rule, self.names.get(rule.author_id, ""), self.colors.get(rule.author_id), self.root,
                            self.today, self.grid_holder)
            card.read_clicked.connect(lambda rule_id: self.read_requested.emit([rule_id]))
            card.photo_clicked.connect(self.open_photo)
            card.edit_clicked.connect(self.edit_rule)
            card.archive_clicked.connect(self._on_archive_clicked)
            card.delete_clicked.connect(self._on_delete_clicked)
            card.animation_done.connect(self._on_animation_done)
            self.cards[rule.id] = card
            self.grid.addWidget(card, number // columns, number % columns, Qt.AlignTop)
        for column in range(max(columns, 1)):
            self.grid.setColumnStretch(column, 1)
        self.read_all_button.setEnabled(logic.unread_count(self.rules) > 0)

    @staticmethod
    def _columns_for(width):
        return max(1, (max(1, width) + GRID_SPACING) // (CARD_MIN_WIDTH + GRID_SPACING))

    def eventFilter(self, watched, event):
        if watched is self.scroll.viewport() and event.type() == QEvent.Resize and not self._animating:
            if self._columns_for(event.size().width()) != self._columns:
                self._render()
        return False

    def _on_archive_clicked(self, rule_id, archived):
        card = self.cards.get(rule_id)
        if card is not None:
            card.set_buttons_enabled(False)  # пока база отвечает, второй раз нажать нельзя
        self.archive_requested.emit(rule_id, archived)

    def _on_delete_clicked(self, rule_id):
        rule = next((item for item in self.rules if item.id == rule_id), None)
        if rule is None or not self.ask_delete(rule):
            return
        card = self.cards.get(rule_id)
        if card is not None:
            card.set_buttons_enabled(False)
        self.delete_requested.emit(rule_id)

    def ask_delete(self, rule):
        """Подтверждение. Подменяется в тестах."""
        from PyQt5.QtWidgets import QMessageBox

        return QMessageBox.question(self, "Atlas", TEXT_DELETE_ASK.format(rule.title),
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def play_archive(self, rule_id, archived):
        """База подтвердила архив: печать на карточке, по её концу — перечитать (`shown`)."""
        self._play(rule_id, lambda card: card.play_archive(archived))

    def play_delete(self, rule_id):
        if self.editing is not None and self.editing.id == rule_id:
            self.finish_edit()
        self._play(rule_id, lambda card: card.play_delete())

    def _play(self, rule_id, start):
        card = self.cards.get(rule_id)
        if card is None or not self.animations or not card.isVisible():
            self.shown.emit()
            return
        self._animating.add(rule_id)
        start(card)

    def _on_animation_done(self, rule_id):
        self._animating.discard(rule_id)
        if self._animating:
            return
        pending, self._pending = self._pending, None
        if pending is not None:
            self.set_data(*pending)
        self.shown.emit()  # перечитать: архивная уходит вниз, удалённая пропадает

    def action_failed(self, rule_id, text):
        card = self.cards.get(rule_id)
        if card is not None:
            card.set_buttons_enabled(True)
        if self.editing is not None:
            self.set_busy(False)
        self.show_error(text)

    def open_photo(self, rels, index):
        PhotoDialog(self.root, rels, index, self).exec_()


class RulesPanel(QFrame):
    """Правила к открытой детали в правой колонке экрана сравнения. Пустая — скрыта."""

    read_requested = pyqtSignal(list)
    photo_clicked = pyqtSignal(object, int)

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
