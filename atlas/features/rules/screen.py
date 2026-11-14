"""Экран «Правила» и панель «Правила к детали». Только рисуют готовые данные, в базу не ходят."""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QEvent, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QImageReader, QPainter, QPalette, QPixmap
from PyQt5.QtWidgets import (
    QButtonGroup, QCompleter, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
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
TEXT_LEGACY = "Старое правило ({}): деталь и модель можно не вписывать — тогда область прежняя"
TEXT_DELETE_ASK = "Удалить правило «{}» насовсем? Фото правила тоже удалятся. Чтобы убрать, но сохранить, — «В архив»."
CARD_MIN_WIDTH = 360
GRID_SPACING = 12
TEXT_TITLE = "Заголовок"
TEXT_TITLE_HINT = "Коротко, что проверять"
TEXT_PART = "Деталь"
TEXT_PART_HINT = "Как в названии папки: по ней правило покажется в «Сравнении»"
TEXT_MODEL = "Модель"
TEXT_MODEL_HINT = "Для поиска"
TEXT_BODY = "Комментарий"
TEXT_BODY_HINT = "Что именно проверять; один комментарий ко всем приложенным фото"
TEXT_SEARCH_HINT = "Поиск: заголовок, текст, деталь, модель, кто добавил, дата (14.11.2026)"
TEXT_EMPTY_SEARCH = "Ничего не нашлось"
TEXT_ATTACH = "Приложить фото"
TEXT_PUBLISH = "Опубликовать"
TEXT_PUBLISHING = "Сохраняю…"
TEXT_NOTE = "После публикации у коллег вкладка «Правила» подсветится, а правило к детали покажется в сводке на экране сравнения."
TEXT_PANEL = "Правила к детали"
TEXT_PHOTOS = "Фото: {}"
TEXT_PHOTO_TITLE = "Фото правила"
TEXT_TO_COMPARE = "Открыть в сравнении"
TIP_TO_COMPARE = "Фото правила — в окна «Сравнения» как эталон: сравнить с проверяемой платой"
TILE_MAX_HEIGHT = 420
ATTACH_PREVIEW = 64
TEXT_DROP_PHOTOS = "Убрать фото"
FILTERS = ((logic.FILTER_ALL, "Все"), (logic.FILTER_GENERAL, "Общие"), (logic.FILTER_PART, "К детали"))
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
    """Одно фото: колесо — зум к курсору, мышь — сдвиг, двойной клик — вписать.

    moved — (зум относительно «целиком», сдвиг в долях фото): по нему соседние окна двигаются так же (14.11.2026).
    """

    moved = pyqtSignal(float, float, float)

    def __init__(self, parent=None, minimum=QSize(640, 480)):
        super().__init__(parent)
        self.pixmap = QPixmap()
        self.zoom = 1.0
        self.offset = QPointF(0, 0)
        self._drag = None
        self.setMinimumSize(minimum)
        self.setCursor(Qt.OpenHandCursor)

    def _fit_zoom(self):
        if self.pixmap.isNull():
            return 1.0
        return min(self.width() / float(self.pixmap.width()), self.height() / float(self.pixmap.height()))

    def _emit_moved(self):
        if self.pixmap.isNull():
            return
        shown_w, shown_h = self.pixmap.width() * self.zoom, self.pixmap.height() * self.zoom
        self.moved.emit(self.zoom / self._fit_zoom(), self.offset.x() / shown_w, self.offset.y() / shown_h)

    def follow(self, relative, dx, dy):
        """Встать так же, как соседнее окно: тот же зум от «целиком» и тот же сдвиг в долях фото."""
        if self.pixmap.isNull():
            return
        self.zoom = self._fit_zoom() * relative
        self.offset = QPointF(dx * self.pixmap.width() * self.zoom, dy * self.pixmap.height() * self.zoom)
        self.update()

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
        # Шаг колеса — 1,2, как в «Сравнении»; тачпад шлёт много мелких событий, и каждое — своя доля шага
        factor = 1.2 ** (event.angleDelta().y() / 120.0)
        new_zoom = max(0.05, min(self.zoom * factor, 8.0))
        factor = new_zoom / self.zoom
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        cursor = QPointF(event.pos()) - center
        self.offset = cursor - (cursor - self.offset) * factor  # точка под курсором остаётся на месте
        self.zoom = new_zoom
        self.update()
        self._emit_moved()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = (QPointF(event.pos()), QPointF(self.offset))
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            self.offset = self._drag[1] + (QPointF(event.pos()) - self._drag[0])
            self.update()
            self._emit_moved()

    def mouseReleaseEvent(self, event):
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self, event):
        self.fit()
        self._emit_moved()


ARRANGE_ONE = "one"
ARRANGE_SIDE = "side"
ARRANGE_STACK = "stack"
ARRANGES = ((ARRANGE_ONE, "По одному", "Одно фото, листать стрелками"),
            (ARRANGE_SIDE, "Рядом", "Все фото правила слева направо, вплотную"),
            (ARRANGE_STACK, "Друг под другом", "Все фото правила сверху вниз, вплотную — для длинных плат"))
MULTI_MINIMUM = QSize(160, 120)


class PhotoDialog(QDialog):
    """Просмотр фото правила: зум, сдвиг, листание стрелками.

    14.11.2026 (замечание с выезда: фото правила далеко друг от друга): «Рядом» и «Друг под другом» — все фото
    вплотную, зум и сдвиг у всех вместе. Выбор запоминается до закрытия программы.
    """

    arrange = None  # общий для всех окон фото: последний выбор

    def __init__(self, root, rels, index=0, parent=None, to_compare=None):
        super().__init__(parent)
        self.root, self.rels, self.index = Path(root), list(rels), 0
        self.to_compare = to_compare  # callable(список полных путей) или None, если «Сравнения» нет
        self.setWindowTitle(TEXT_PHOTO_TITLE)
        layout = QVBoxLayout(self)
        self.view = ZoomView()
        self.multi = QWidget()  # все фото вплотную
        self.multi_layout = QGridLayout(self.multi)
        self.multi_layout.setContentsMargins(0, 0, 0, 0)
        self.multi_layout.setSpacing(2)
        self.multi_views = []
        self._following = False
        layout.addWidget(self.view, 1)
        layout.addWidget(self.multi, 1)
        modes = QHBoxLayout()
        self.arrange_buttons = {}
        group = QButtonGroup(self)
        for key, text, tip in ARRANGES:
            button = QPushButton(text)
            button.setProperty("role", "chip")
            button.setCheckable(True)
            button.setToolTip(tip)
            button.setFocusPolicy(Qt.NoFocus)
            group.addButton(button)
            button.clicked.connect(lambda _=False, k=key: self.set_arrange(k))
            modes.addWidget(button)
            self.arrange_buttons[key] = button
        modes.addStretch(1)
        self.compare_button = QPushButton(TEXT_TO_COMPARE)
        self.compare_button.setFocusPolicy(Qt.NoFocus)
        self.compare_button.setToolTip(TIP_TO_COMPARE)
        set_icon(self.compare_button, "columns-2", "text")
        self.compare_button.clicked.connect(lambda _=False: self.open_in_compare())
        self.compare_button.setVisible(to_compare is not None)
        modes.addWidget(self.compare_button)
        layout.addLayout(modes)
        bar = QHBoxLayout()
        self.prev_button = QPushButton("Назад")
        self.next_button = QPushButton("Вперёд")
        self.fit_button = QPushButton("В кадр")
        set_icon(self.fit_button, "scan", "text")
        self.fit_button.setToolTip("Всё фото целиком")
        self.count_label = _label("", "muted", wrap=False)
        for button in (self.prev_button, self.next_button, self.fit_button):
            button.setFocusPolicy(Qt.NoFocus)
        self.prev_button.clicked.connect(lambda _=False: self.step(-1))
        self.next_button.clicked.connect(lambda _=False: self.step(1))
        self.fit_button.clicked.connect(lambda _=False: self.fit_all())
        bar.addWidget(self.prev_button)
        bar.addWidget(self.next_button)
        bar.addWidget(self.fit_button)
        bar.addWidget(self.count_label)
        bar.addStretch(1)
        bar.addWidget(_label("Колесо — приблизить, мышь — двигать, двойной клик — фото целиком", "muted", wrap=False))
        layout.addLayout(bar)
        self.resize(1000, 760)
        self.show_index(index)
        if len(self.rels) < 2:
            for button in self.arrange_buttons.values():
                button.hide()
        default = ARRANGE_SIDE if len(self.rels) > 1 else ARRANGE_ONE
        self.set_arrange(PhotoDialog.arrange if len(self.rels) > 1 and PhotoDialog.arrange else default)

    def open_in_compare(self):
        """Все фото правила — эталоном в «Сравнении»; окно закрывается."""
        if self.to_compare is None:
            return
        self.to_compare([self.root / rel for rel in self.rels])
        self.accept()

    def set_arrange(self, key):
        """По одному / рядом / друг под другом."""
        key = key if len(self.rels) > 1 else ARRANGE_ONE
        self.arrange_buttons[key].setChecked(True)
        if len(self.rels) > 1:
            PhotoDialog.arrange = key
        single = key == ARRANGE_ONE
        self.view.setVisible(single)
        self.multi.setVisible(not single)
        for button in (self.prev_button, self.next_button, self.count_label):
            button.setVisible(single)
        if single:
            return
        if not self.multi_views:
            for number, rel in enumerate(self.rels):
                view = ZoomView(minimum=MULTI_MINIMUM)
                view.set_pixmap(QPixmap(str(self.root / rel)))
                view.moved.connect(lambda relative, dx, dy, source=view: self._follow(source, relative, dx, dy))
                self.multi_views.append(view)
        for view in self.multi_views:
            self.multi_layout.removeWidget(view)
        for number, view in enumerate(self.multi_views):
            if key == ARRANGE_SIDE:
                self.multi_layout.addWidget(view, 0, number)
            else:
                self.multi_layout.addWidget(view, number, 0)
        self.fit_all()

    def _follow(self, source, relative, dx, dy):
        if self._following:
            return
        self._following = True
        try:
            for view in self.multi_views:
                if view is not source:
                    view.follow(relative, dx, dy)
        finally:
            self._following = False

    def fit_all(self):
        self.view.fit()
        for view in self.multi_views:
            view.fit()

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
    # правило, заголовок, текст, оставленные фото, новые, деталь, модель
    update_requested = pyqtSignal(int, str, str, tuple, tuple, str, str)

    def __init__(self, root, kinds, today=None, animations=True, parent=None, edit_days=logic.EDIT_DAYS):
        super().__init__(parent)
        self.edit_days = edit_days
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
        self.query = ""
        self.user_id, self.admin = 0, False
        self.to_compare = None  # «Открыть в сравнении» в окне фото; ставит функция, если есть «Сравнение»
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
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(TEXT_SEARCH_HINT)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._set_query)
        left.addWidget(self.search_edit)
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
        column.addWidget(_label(TEXT_PART, "muted"))
        self.part_edit = QLineEdit()
        self.part_edit.setPlaceholderText(TEXT_PART_HINT)
        self.part_edit.textEdited.connect(self._on_part_edited)
        column.addWidget(self.part_edit)
        column.addWidget(_label(TEXT_MODEL, "muted"))
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText(TEXT_MODEL_HINT)
        column.addWidget(self.model_edit)
        self._part_touched = False  # вписали деталь руками — открытая папка её больше не подставляет
        self.scope_note = _label("", "muted")
        self.scope_note.hide()
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

    def _on_part_edited(self, _text):
        self._part_touched = True

    def _fill_suggestions(self):
        """Подсказки: детали и модели из уже записанных правил плюс открытая деталь."""
        parts = {rule.part_name for rule in self.rules if rule.part_name}
        if self.part is not None:
            parts.add(self.part.name)
        models = {rule.model for rule in self.rules if rule.model}
        for edit, values in ((self.part_edit, parts), (self.model_edit, models)):
            completer = QCompleter(sorted(values, key=str.casefold), edit)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains)
            edit.setCompleter(completer)

    def _refresh_form(self):
        if self.editing is None and not self._part_touched:  # новая форма: деталь — открытая сейчас
            self.part_edit.setText(self.part.name if self.part is not None else "")
        if self.editing is not None:
            count = len(self.keep_rels) + len(self.photo_paths)
            self.photos_label.setText(TEXT_PHOTOS.format(count) if count else "")
            self.drop_button.setVisible(bool(count))
            self._render_previews()
            return
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
        part_name, model = self.part_edit.text(), self.model_edit.text()
        if self.editing is not None:
            full = bool(self.editing.part_name or part_name.strip() or model.strip())
            draft = logic.Draft(logic.SCOPE_GENERAL, self.title_edit.text(), self.body_edit.toPlainText(),
                                part_name=part_name, model=model, full=full)
            try:
                logic.checked(draft)
            except logic.RuleError as exc:
                self.show_error(str(exc))
                return
            self.show_error("")
            self.set_busy(True)
            self.update_requested.emit(self.editing.id, self.title_edit.text(), self.body_edit.toPlainText(),
                                       tuple(self.keep_rels), tuple(self.photo_paths), part_name, model)
            return
        draft = logic.draft_new(self.title_edit.text(), part_name, model, self.body_edit.toPlainText(), self.part,
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
        """Правило — в форму справа: заголовок, деталь, модель, текст, его фото (можно убрать и добавить)."""
        rule = next((item for item in self.rules if item.id == rule_id), None)
        if rule is None or not logic.can_edit(rule, self.admin, self.today, self.edit_days):
            return
        self.editing = rule
        self.keep_rels = list(rule.photos)
        self.photo_paths = []
        self.title_edit.setText(rule.title)
        self.part_edit.setText(rule.part_name or "")
        self.model_edit.setText(rule.model or "")
        legacy = not rule.part_name
        self.scope_note.setText(TEXT_LEGACY.format(logic.scope_text(rule)) if legacy else "")
        self.scope_note.setVisible(legacy)
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
        self.model_edit.clear()  # модель была от изменённого правила
        self.scope_note.hide()
        self.form_title.setText(TEXT_FORM)
        self.cancel_edit_button.hide()
        self.clear_form()
        self.set_busy(False)

    def show_error(self, text):
        self.error_label.setText(text)

    def clear_form(self):
        """После публикации: деталь снова — открытая, модель остаётся (часто следующее правило про неё же)."""
        self.title_edit.clear()
        self.body_edit.clear()
        self._part_touched = False
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
        self._fill_suggestions()
        self._refresh_form()
        self._render()

    def set_access(self, user_id, admin):
        """Кто смотрит: от этого зависят «вернуть из архива», «удалить» и срок правки."""
        changed = (user_id, bool(admin)) != (self.user_id, self.admin)
        self.user_id, self.admin = user_id, bool(admin)
        if changed and not self._animating:
            self._render()

    def _set_filter(self, key):
        self.filter_key = key
        self._render()

    def _set_query(self, text):
        self.query = text
        if not self._animating:
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
        shown = logic.search(logic.filtered(self.rules, self.filter_key), self.query, self.names)
        if not shown:
            self.empty_label.setText(TEXT_EMPTY if not self.rules else TEXT_EMPTY_SEARCH if self.query.strip()
                                     else TEXT_EMPTY_FILTER)
            self.grid.addWidget(self.empty_label, 0, 0)
            self.empty_label.show()
        else:
            self.empty_label.hide()
        columns = self._columns_for(self.scroll.viewport().width())
        self._columns = columns
        for number, rule in enumerate(shown):
            card = RuleTile(rule, self.names.get(rule.author_id, ""), self.colors.get(rule.author_id), self.root,
                            self.today, self.grid_holder, archiver=self.names.get(rule.archived_by, ""),
                            edit_days=self.edit_days, user_id=self.user_id, admin=self.admin)
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
        self.read_all_button.setEnabled(logic.has_news(self.rules))

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
        if rule is None or not logic.can_delete(self.admin) or not self.ask_delete(rule):
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
        PhotoDialog(self.root, rels, index, self, self.to_compare).exec_()


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
