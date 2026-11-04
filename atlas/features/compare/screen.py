"""Экран сравнения. Окна постоянные: views[0] — эталон (если он есть), текущие — views[1], views[2]…; раскладка только показывает нужные."""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QPoint, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from atlas.core import theme
from atlas.core.domain.photo_names import parse_photo_name
from atlas.features.compare.angles import AnglesModel, notes as angle_notes, set_mark as angle_set_mark
from atlas.features.compare.logic import (
    DEFAULT_HOTKEYS, DEFAULT_MARK_KEYS, MAX_WINDOWS, ROTATE_STEP, CompareModel, counts_text, default_sn, grid_cells, mark_label, mark_token,
    neighbor_indexes, position_text, reference_angles, toggle_mark,
)
from atlas.shared.widgets import FlowLayout
from atlas.shared.widgets.icons import set_icon
from atlas.shared.viewer.filmstrip import FilmItem, Filmstrip
from atlas.shared.viewer.levels import L1, NEIGHBOR
from atlas.shared.viewer.photo_view import PhotoView
from atlas.shared.viewer.sync_group import SyncGroup

BUTTON_ZOOM = 1.4  # как в макете
LEFT_WIDTH = (240, 280)
RIGHT_WIDTH = (280, 320)
PANEL_BUTTONS = (
    ("left", "Папки", "Показать или скрыть список папок слева"),
    ("top", "Инструменты", "Показать или скрыть панель кнопок над фото"),
    ("bottom", "Лента", "Показать или скрыть ленту фото, отметки и подсказку внизу"),
    ("right", "Сводка", "Показать или скрыть панель справа (сводка по детали)"),
)
PANEL_ICONS = {"left": "panel-left", "top": "wrench", "bottom": "gallery-horizontal", "right": "panel-right"}
MARK_ICONS = {"remark": ("circle-alert", "remark")}  # значок, токен цвета при включении
TEXT_HIDE_UI = "Скрыть всё"
TEXT_SHOW_UI = "Показать всё"
HINT = "Колесо — зум · перетаскивание — сдвиг · двойной клик — фото целиком · стрелки — листать · пробел — эталон"
HINT_ANGLES = "Колесо — зум · перетаскивание — сдвиг · двойной клик — фото целиком · стрелки — следующий SN · клик — активное окно"
STRIP_SETTLE_MS = 150  # миниатюры — после остановки: при удержании стрелки чтение нужно текущему фото
TEXT_NO_FOLDER = "Папка не открыта"
TEXT_NO_PHOTOS = "В папке нет фото"
TAG_REFERENCE = "ЭТАЛОН"
TAG_SINGLE = "ЛИСТАНИЕ"
TAG_CURRENT = "НОВОЕ"
TEXT_KIND_NONE = "Вид не выбран"
TEXT_SIZES_PENDING = "Читаю размеры фото: поворот применится сам"
SN_WIDTH = 120
KIND_CHARS = 18  # ширина списка видов в знаках; длинные названия видны в раскрытом списке
TEXT_REFERENCE_MARKS = "Эталон из другой папки — отметки недоступны"
TAG_OTHER_PROJECT = "ЭТАЛОН · ДРУГОЙ ПРОЕКТ"
TAG_ANGLE = "РАКУРС {}"
TEXT_NO_ANGLE = "Нет ракурса {}"
TEXT_NO_CURRENT_ANGLE = "В текущей папке нет ракурса {}"
TEXT_CLEAR_REFERENCE = "Убрать эталон"
TIP_CLEAR_REFERENCE = "Сравнил — эталон больше не нужен: его окно снова показывает фото этой папки"
TIP_RESET = ("Всё фото целиком во всех окнах; подгонка окон друг к другу снимается.\n"
             "Двойной клик по фото — целиком только это окно")
TIP_KINDS_EDIT = "Виды замечаний: добавить, исправить, удалить"
TIP_ANGLE_TOGGLE = "Ракурс {}: показать или убрать окно"
TEXT_ANGLE_LIMIT = "Окон не больше 4: сначала выключите другой ракурс"
TEXT_ANGLE_LAST = "Хотя бы один ракурс должен остаться"
TEXT_NO_ANGLES = "Ни одно имя фото не разобрано: ракурсы показать нельзя. Фото видны в «Сравнении»"
FIT_STATE = (1.0, 0.5, 0.5)


class SlotColumn(QVBoxLayout):
    """Колонка слота: пока панелей нет, места не занимает. SlotRegistry работает только через эти два метода."""

    def __init__(self, holder):
        super().__init__(holder)
        self._holder = holder
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(10)
        self.changed = None  # вызывается, когда колонка стала пустой или непустой: экран прячет или показывает свой контейнер
        holder.hide()

    def addWidget(self, widget, *args):
        super().addWidget(widget, *args)
        self._holder.show()
        if self.changed is not None:
            self.changed()

    def removeWidget(self, widget):
        super().removeWidget(widget)
        self._holder.setVisible(self.count() > 0)
        if self.changed is not None:
            self.changed()


def _shift_held():
    """Кнопку поворота нажали с Shift: тогда, как и с клавишей, весь ракурс окна."""
    return bool(QApplication.keyboardModifiers() & Qt.ShiftModifier)


def _key(text):
    sequence = QKeySequence(text)
    return sequence[0] if sequence.count() else 0


class UpwardComboBox(QComboBox):
    """Панель отметок внизу окна: список открывается вверх, поверх фото, а не за край экрана."""

    def showPopup(self):
        super().showPopup()
        popup = self.view().window()
        top = self.mapToGlobal(QPoint(0, 0)).y() - popup.height()
        popup.move(popup.x(), max(top, 0))


class CompareScreen(QWidget):
    photo_changed = pyqtSignal(object, int)  # PhotoItem, индекс в папке: пользователь перелистал активное окно
    mark_requested = pyqtSignal(object, object, object, object)  # PhotoItem, отметка или None, SN (None — не менять), вид
    find_requested = pyqtSignal()  # кнопка «Найти такую же деталь»
    kinds_edit_requested = pyqtSignal()  # кнопка правки списка видов замечаний
    panels_changed = pyqtSignal(object)  # {панель: видна}: пользователь спрятал или показал панель
    rotation_changed = pyqtSignal(object, int)  # [id фото папки], новый поворот: записать в базу

    def __init__(self, cache, hotkeys, name_pattern=None, defect_kinds=(), parent=None):
        super().__init__(parent)
        self._name_pattern = name_pattern
        self._defect_kinds = list(defect_kinds)
        mark_keys = hotkeys.get("marks") or DEFAULT_MARK_KEYS
        self._mark_keys = {mark: _key(text) for mark, text in mark_keys.items()}
        self._mark_by_key = {key: mark for mark, key in self._mark_keys.items() if key}
        self._index_by_id = {}
        self._panel_photo = None  # фото, для которого сейчас заполнена панель отметок
        self._strip_source = None  # что сейчас на ленте: folder, reference, angles
        self._angles_on = False
        self.angles = AnglesModel()
        self._angle_states = {}  # окно → (зум, x, y) в «Ракурсах»; у каждого окна своё
        self._compare_states = {}  # то же в «Сравнении»: при выключенной синхронности окна тоже стоят по-разному
        self._compare_group_state = FIT_STATE
        self._angle_group_state = FIT_STATE
        self._compare_offsets = {}  # подгонка окон друг к другу (SyncGroup.offsets) — у каждого режима своя
        self._angle_offsets = {}
        self._sync_by_mode = {False: True, True: False}  # «Синхронно» у каждого режима своя: стороны платы по месту не совпадают
        self._reference_note = ""  # подпись найденной папки: проект, дата
        self._reference_tag = TAG_REFERENCE
        self.setFocusPolicy(Qt.StrongFocus)  # стрелки и пробел приходят сюда, кнопки фокус не берут
        self.model = CompareModel()
        self.group = SyncGroup(cache, self)
        self._cache = cache
        self._keys = {_key(hotkeys["prev"]): -1, _key(hotkeys["next"]): 1}
        self._flicker_key = _key(hotkeys["flicker"])
        self._toggle_ui_key = _key(hotkeys.get("toggle_ui", DEFAULT_HOTKEYS["toggle_ui"]))
        self._rotate_keys = {
            _key(hotkeys.get("rotate_left", DEFAULT_HOTKEYS["rotate_left"])): -ROTATE_STEP,
            _key(hotkeys.get("rotate_right", DEFAULT_HOTKEYS["rotate_right"])): ROTATE_STEP,
        }
        self._flicker = None  # (окно, его состояние), пока удерживается «мигалка»
        self._sizes_pending = False  # размеры фото ещё читаются: поворот группы ждёт их
        self._deferred_turns = []
        self._portrait = True  # фото Atlas обычно вертикальные; уточняется по первому показанному
        self._orientation_known = False
        self.views = [PhotoView(cache, self) for _ in range(MAX_WINDOWS)]
        for view in self.views:
            view.hide()
            view.installEventFilter(self)
            view.photo_shown.connect(lambda _path, source=view: self._on_view_shown(source))
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
        self.hint = QLabel(HINT)
        self.hint.setProperty("role", "muted")

        # Группы панелей лежат в своих контейнерах: прячется контейнер, а показ самих панелей (эталон, ракурсы, слоты) решает прежний код
        self.top_box = self._box(self._build_toolbar(), self._build_reference_bar(), self._build_angles_bar())
        self.bottom_box = self._box(self._build_strip_panel(), self._build_marks_panel(), self.hint)
        self.left_box = self._box(self.left)
        self.right_box = self._box(self.right)
        # пустая колонка слота скрыта, и контейнер тоже, иначе остаётся пустой промежуток; Show-событий до показа окна нет, поэтому через колонку
        self.left_layout.changed = lambda: self._apply_side("left", self.left)
        self.right_layout.changed = lambda: self._apply_side("right", self.right)

        middle = QVBoxLayout()
        middle.setSpacing(10)
        middle.addLayout(self._build_visibility_bar())
        middle.addWidget(self.top_box)
        middle.addWidget(self.message, 1)
        middle.addLayout(self.grid, 1)
        middle.addWidget(self.bottom_box)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)
        root.addWidget(self.left_box)
        root.addLayout(middle, 1)
        root.addWidget(self.right_box)

        self.group.changed.connect(lambda zoom, cx, cy: self._show_zoom(zoom))
        self.set_layout(1)
        self._apply_side("left", self.left)
        self._apply_side("right", self.right)

    # --- сборка ---------------------------------------------------------------
    def _box(self, *widgets):
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)
        for widget in widgets:
            column.addWidget(widget)
        return box

    def _build_visibility_bar(self):
        """Узкая строка над фото: какие панели видны. Для больших деталей панели прячутся, место отдаётся фото."""
        row = QHBoxLayout()
        row.setSpacing(6)
        self._panel_boxes = {"left": self.left_box, "top": self.top_box, "bottom": self.bottom_box, "right": self.right_box}
        self._panel_buttons = {}
        for key, text, tip in PANEL_BUTTONS:
            button = self._button(text, lambda _=False, k=key: self._on_panel_clicked(k), checkable=True)
            button.setProperty("role", "mini")
            set_icon(button, PANEL_ICONS[key], size=12)
            button.setChecked(True)
            button.setToolTip(tip)
            self._panel_buttons[key] = button
            row.addWidget(button)
        row.addStretch(1)
        self.hide_all_button = self._button(TEXT_HIDE_UI, self.toggle_interface)
        self.hide_all_button.setProperty("role", "mini")
        set_icon(self.hide_all_button, "eye-off", size=12)
        row.addWidget(self.hide_all_button)
        return row

    def _apply_side(self, key, holder):
        if not hasattr(self, "_panel_buttons"):
            return
        wanted = self._panel_buttons[key].isChecked() and not holder.isHidden()
        self._panel_boxes[key].setVisible(wanted)

    def _on_panel_clicked(self, key):
        self.set_panel_visible(key, self._panel_buttons[key].isChecked())
        self.panels_changed.emit(self.panels_state())

    def panels_state(self):
        return {key: button.isChecked() for key, button in self._panel_buttons.items()}

    def restore_panels(self, state):
        """Вернуть сохранённый выбор; неизвестные ключи и не-булевы значения пропускаются."""
        if not isinstance(state, dict):
            return
        for key in self._panel_boxes:
            if isinstance(state.get(key), bool):
                self.set_panel_visible(key, state[key])

    def set_panel_visible(self, key, visible):
        self._panel_buttons[key].setChecked(bool(visible))
        if key in ("left", "right"):
            self._apply_side(key, self.left if key == "left" else self.right)
        else:
            self._panel_boxes[key].setVisible(bool(visible))
        self._panel_buttons[key].setChecked(bool(visible))
        shown = any(button.isChecked() for button in self._panel_buttons.values())
        self.hide_all_button.setText(TEXT_HIDE_UI if shown else TEXT_SHOW_UI)
        set_icon(self.hide_all_button, "eye-off" if shown else "eye", size=12)

    def toggle_interface(self):
        """Скрыть все панели, оставив фото; повторно — вернуть все."""
        show = not any(button.isChecked() for button in self._panel_buttons.values())
        for key in self._panel_boxes:
            self.set_panel_visible(key, show)
        self.panels_changed.emit(self.panels_state())

    def _build_toolbar(self):
        bar = QFrame()
        bar.setProperty("role", "panel")
        rows = QVBoxLayout(bar)
        rows.setContentsMargins(8, 8, 8, 8)
        rows.setSpacing(6)
        row = QHBoxLayout()  # первый ряд — как смотреть, второй — действия: вместе в окно шириной 1024 они не помещаются
        row.setSpacing(6)
        rows.addLayout(row)
        self.compare_mode_button = self._button("Сравнение", lambda _=False: self.set_angles_mode(False), checkable=True)
        self.compare_mode_button.setChecked(True)
        row.addWidget(self.compare_mode_button)
        self.angles_mode_button = self._button("Ракурсы", lambda _=False: self.set_angles_mode(True), checkable=True)
        self.angles_mode_button.setToolTip("Все стороны одного SN: листаются вместе; зум и поворот вместе — кнопкой «Синхронно»")
        row.addWidget(self.angles_mode_button)
        row.addWidget(self._separator())
        # Кнопки ракурсов стоят на месте кнопок раскладки: в «Ракурсах» тех нет, ряд не становится шире
        self.angle_toggles = QWidget()
        self.angle_toggles.setProperty("role", "plain")
        self._angle_toggle_row = QHBoxLayout(self.angle_toggles)
        self._angle_toggle_row.setContentsMargins(0, 0, 0, 0)
        self._angle_toggle_row.setSpacing(6)
        self._angle_toggle_buttons = {}
        self.angle_toggles.hide()
        row.addWidget(self.angle_toggles)
        self._compare_only = []  # в «Ракурсах» этого нет: окон столько, сколько ракурсов, эталона нет
        for count in range(1, MAX_WINDOWS + 1):
            # Цифры, а не «1 фото»: с панелью папок ряд иначе не помещается в окно шириной 1024
            button = self._button(str(count), lambda _=False, n=count: self.set_layout(n), checkable=True)
            button.setProperty("role", "square")
            button.setToolTip("{} фото".format(count))
            self._layout_buttons[count] = button
            self._compare_only.append(button)
            row.addWidget(button)
        separator = self._separator()
        self._compare_only.append(separator)
        row.addWidget(separator)
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
        self.reset_button = self._button("В кадр", self.fit)
        set_icon(self.reset_button, "scan", "text")
        self.reset_button.setToolTip(TIP_RESET)
        row.addWidget(self.reset_button)
        self.sync_button = self._button("Синхронно", self._on_sync_toggled, checkable=True)
        self.sync_button.setChecked(True)
        self.sync_button.setToolTip(
            "Включено: зум, сдвиг и поворот у всех окон вместе. Выключено: у каждого окна свои, поворот — одного фото")
        row.addWidget(self.sync_button)
        row.addStretch(1)
        row = QHBoxLayout()
        row.setSpacing(6)
        rows.addLayout(row)
        keys = {delta: QKeySequence(key).toString() for key, delta in self._rotate_keys.items()}
        for delta, tip in ((-ROTATE_STEP, "Повернуть против часовой стрелки"), (ROTATE_STEP, "Повернуть по часовой стрелке")):
            button = self._button("", lambda _=False, d=delta: self.rotate(d, whole_angle=_shift_held()))
            button.setProperty("role", "square")
            set_icon(button, "rotate-cw" if delta > 0 else "rotate-ccw", "text")
            button.setToolTip("{} (клавиша {}; с Shift — весь ракурс этого окна)".format(tip, keys.get(delta, "")))
            if delta > 0:
                self.rotate_right_button = button
            else:
                self.rotate_left_button = button
            row.addWidget(button)
        self.find_button = self._button("Найти такую же деталь", self.find_requested.emit)
        set_icon(self.find_button, "search")
        self.find_button.setToolTip("Открыть эталоном последнюю проверку такой же детали")
        self.find_button.setEnabled(False)
        row.addWidget(self.find_button)
        self._compare_only.append(self.find_button)
        row.addStretch(1)
        self.toolbar_layout = FlowLayout(spacing=6)  # кнопки функций переносятся на вторую строку, а не сжимаются
        rows.addLayout(self.toolbar_layout)
        return bar

    def _build_reference_bar(self):
        """Строка про эталон из найденной папки и кнопки его ракурсов; без найденной папки скрыта."""
        self.reference_bar = QFrame()
        self.reference_bar.setProperty("role", "panel")
        row = QHBoxLayout(self.reference_bar)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(6)
        self.reference_label = QLabel("")
        self.reference_label.setProperty("role", "caption")
        row.addWidget(self.reference_label)
        self._angle_row = QHBoxLayout()
        self._angle_row.setSpacing(6)
        row.addLayout(self._angle_row)
        row.addStretch(1)
        self.clear_reference_button = self._button(TEXT_CLEAR_REFERENCE, self.clear_reference)
        set_icon(self.clear_reference_button, "x", "text")
        self.clear_reference_button.setToolTip(TIP_CLEAR_REFERENCE)
        row.addWidget(self.clear_reference_button)
        self._angle_buttons = {}
        self.reference_bar.hide()
        return self.reference_bar

    def _build_angles_bar(self):
        """Строка «Ракурсов»: лишние ракурсы, неразобранные имена, ошибки в именах. Нечего сказать — скрыта."""
        self.angles_bar = QFrame()
        self.angles_bar.setProperty("role", "panel")
        row = QHBoxLayout(self.angles_bar)
        row.setContentsMargins(10, 6, 10, 6)
        self.angles_label = QLabel("")
        self.angles_label.setProperty("role", "warn")
        self.angles_label.setWordWrap(True)
        row.addWidget(self.angles_label, 1)
        self.angles_bar.hide()
        return self.angles_bar

    def _build_strip_panel(self):
        self.strip_panel = QFrame()
        self.strip_panel.setProperty("role", "panel")
        row = QHBoxLayout(self.strip_panel)
        row.setContentsMargins(10, 10, 10, 10)
        row.setSpacing(10)
        self.prev_button = self._arrow_button(-1, "Предыдущее фото")
        self.next_button = self._arrow_button(1, "Следующее фото")
        row.addWidget(self.prev_button)
        row.addWidget(self.strip, 1)
        row.addWidget(self.next_button)
        return self.strip_panel

    def _build_marks_panel(self):
        self.marks_panel = QFrame()
        self.marks_panel.setProperty("role", "panel")
        outer = QVBoxLayout(self.marks_panel)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)
        row = QHBoxLayout()  # отметки, справа от них SN и вид замечания, потом счётчик
        row.setSpacing(8)
        outer.addLayout(row)
        self.marks_title = QLabel("")
        self.marks_title.setProperty("role", "caption")
        row.addWidget(self.marks_title)
        self.mark_buttons = {}
        for mark, key in self._mark_keys.items():
            button = self._button(mark_label(mark), lambda _=False, m=mark: self.request_mark(m), checkable=True)
            button.setProperty("tone", mark_token(mark))
            if mark in MARK_ICONS:
                set_icon(button, MARK_ICONS[mark][0], on=MARK_ICONS[mark][1])
            button.setToolTip("Клавиша {}".format(QKeySequence(key).toString()) if key else "")
            self.mark_buttons[mark] = button
            row.addWidget(button)
        self.defect_box = QWidget()
        self.defect_box.setProperty("role", "plain")
        box = QHBoxLayout(self.defect_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        box.addWidget(QLabel("SN"))
        self.sn_edit = QLineEdit()
        self.sn_edit.setFixedWidth(SN_WIDTH)
        self.sn_edit.editingFinished.connect(self._on_defect_edited)
        self.sn_edit.returnPressed.connect(self.setFocus)  # иначе стрелки останутся в поле
        box.addWidget(self.sn_edit)
        box.addWidget(QLabel("Вид"))
        self.kind_box = UpwardComboBox()
        self.kind_box.setFocusPolicy(Qt.NoFocus)
        self.kind_box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.kind_box.setMinimumContentsLength(KIND_CHARS)
        self._fill_kinds()
        self.kind_box.activated.connect(lambda _=0: self._on_defect_edited())
        box.addWidget(self.kind_box)
        self.kinds_button = self._button("", self.kinds_edit_requested.emit)
        self.kinds_button.setProperty("role", "square")
        set_icon(self.kinds_button, "list-checks", "text")
        self.kinds_button.setToolTip(TIP_KINDS_EDIT)
        self.kinds_button.hide()  # только когда есть функция defect_kinds
        box.addWidget(self.kinds_button)
        row.addWidget(self.defect_box)
        self.defect_box.hide()
        self.counts_label = QLabel("")
        self.counts_label.setProperty("role", "muted")
        self.counts_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        # Счётчик занимает остаток ряда и не раздвигает окно: в узком окне обрезается, целиком — в подсказке
        self.counts_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.addWidget(self.counts_label, 1)
        self.extra_box = QWidget()  # второй ряд: пока в нём нечего показать, скрыт и места не занимает
        self.extra_box.setProperty("role", "plain")
        extra = QHBoxLayout(self.extra_box)
        extra.setContentsMargins(0, 0, 0, 0)
        extra.setSpacing(8)
        outer.addWidget(self.extra_box)
        self.extra_box.hide()
        self.marks_status = QLabel("")
        self.marks_status.setProperty("role", "warn")
        extra.addWidget(self.marks_status)
        extra.addStretch(1)
        return self.marks_panel

    def _sync_extra(self):
        self.extra_box.setVisible(bool(self.marks_status.text()))

    def _arrow_button(self, step, tip):
        button = self._button("", lambda: self.flip(step))
        button.setProperty("role", "square")
        set_icon(button, "chevron-right" if step > 0 else "chevron-left", "text", size=14)
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
        self.group.reset_offsets()  # подгонка была под фото прошлой папки
        self._compare_offsets, self._angle_offsets = {}, {}
        self.angles.set_photos(self.model.photos, self._name_pattern)
        self._fill_angle_toggles()
        self._orientation_known = False
        self._sizes_pending = False
        self._deferred_turns = []
        self.message.setText(TEXT_NO_PHOTOS)
        self._index_by_id = {photo.id: number for number, photo in enumerate(self.model.photos)}
        self.marks_status.setText("")
        self._sync_extra()
        self._strip_source = None
        self._fill_reference_bar()
        self.find_button.setEnabled(bool(self.model.photos))
        self._apply_layout()
        self._cache.prefetch([photo.path for photo in self.model.photos])

    def show_failure(self, text):
        self._end_flicker()
        self.model.set_photos([])
        self.angles.set_photos([])
        self._index_by_id = {}
        self._strip_source = None
        self._fill_reference_bar()
        self.find_button.setEnabled(False)
        self.message.setText(text)
        self._apply_layout()

    def set_reference(self, photo):
        """Заменить эталон. На текущие окна и их индексы это не влияет. Эталон есть только в «Сравнении»."""
        self.set_angles_mode(False)
        self._end_flicker()
        self.model.set_reference(photo)
        self._fill_reference_bar()
        self._apply_layout()

    def set_reference_folder(self, photos, note="", other_project=False):
        """Эталон — фото другой папки (первое), листается стрелками, когда его окно активно.

        При одном окне раскладка становится «2 фото»: эталону нужно место. Текущая папка остаётся открытой.
        Эталон есть только в «Сравнении»: его попросили показать, поэтому режим переключается.
        """
        self.set_angles_mode(False)
        self._end_flicker()
        if self.model.count == 1:
            self.set_layout(2)
        self.model.set_reference_folder(photos)
        self._strip_source = None
        self._reference_note = note
        self._reference_tag = TAG_OTHER_PROJECT if other_project else TAG_REFERENCE
        self._fill_reference_bar()
        self._apply_layout()

    def clear_reference(self):
        """«Убрать эталон»: найденная деталь больше не нужна; окно эталона снова — фото этой папки."""
        if not self.model.has_reference_folder and self.model.reference is None:
            return
        self._end_flicker()
        self.model.set_reference(None)
        self._strip_source = None  # лента снова показывает эту папку
        self.marks_status.setText("")
        self._sync_extra()
        self._fill_reference_bar()
        self._apply_layout()
        self.group.touch(self.active_view())

    def _fill_reference_bar(self):
        for button in self._angle_buttons.values():
            self._angle_row.removeWidget(button)
            button.deleteLater()
        self._angle_buttons = {}
        model = self.model
        if not model.has_reference_folder:
            self._reference_tag = TAG_REFERENCE
            self._reference_note = ""
            return
        self.reference_label.setText("Эталон: {}".format(self._reference_note))
        angles = reference_angles(model.ref_photos, self._name_pattern)
        if len(angles) < 2:
            return  # выбирать нечего
        for angle, index in angles.items():
            button = self._button("Ракурс {}".format(angle), lambda _=False, a=angle: self.choose_angle(a), checkable=True)
            self._angle_buttons[angle] = button
            self._angle_row.addWidget(button)
        self._check_angle()

    def _check_angle(self):
        """Кнопка ракурса нажата у того, чьё фото сейчас эталон."""
        shown = self._angle_of(self.model.reference)
        for angle, button in self._angle_buttons.items():
            button.setChecked(angle == shown)

    def _angle_of(self, photo):
        parsed = parse_photo_name(photo.name, self._name_pattern) if photo else None
        return parsed.view if parsed else None

    def choose_angle(self, angle):
        """Кнопка ракурса: этот ракурс и в эталоне, и в текущих окнах: сравнивать нужно одну и ту же сторону."""
        if self._flicker is not None or not self.model.has_reference_folder:
            return
        index = reference_angles(self.model.ref_photos, self._name_pattern).get(angle)
        if index is None:
            return
        self.go_reference(index)
        before = self.model.active_index
        changed = self.model.show_angle(angle, self._name_pattern)
        for window in changed:
            self._show_in(self._view_of(window))
        has_angle = any(self._angle_of(photo) == angle for photo in self.model.photos)
        self.marks_status.setText("" if has_angle else TEXT_NO_CURRENT_ANGLE.format(angle))
        self._sync_extra()
        self._sync_strip()
        if self.model.active_index != before and not self.model.reference_active:
            self.photo_changed.emit(self.model.photos[self.model.active_index], self.model.active_index)

    def go_reference(self, index):
        """Кнопка ракурса: показать это фото найденной папки эталоном. Активным окном остаётся прежнее."""
        if self._flicker is not None or not self.model.has_reference_folder:
            return
        self.model.go_reference(index)
        self._check_angle()
        if not self.model.reference_window:
            return  # эталона на экране нет: он покажется при раскладке «2 фото»
        self._show_in(self.views[0])
        if self.model.reference_active:
            self._sync_strip()

    def set_layout(self, count):
        self._end_flicker()
        self.model.set_layout(count)
        for number, button in self._layout_buttons.items():
            button.setChecked(number == count)
        self._apply_layout()

    def set_angles_mode(self, on):
        """Переключить режим. Человек продолжает смотреть то же фото; зум и место у каждого режима свои."""
        on = bool(on)
        self.compare_mode_button.setChecked(not on)
        self.angles_mode_button.setChecked(on)
        if on == self._angles_on:
            return
        self._end_flicker()
        states = {view: view.state() for view in self.views}
        if on:
            self._compare_states = states
            self._compare_group_state = self.group.state
            self._compare_offsets = self.group.offsets
            self.model.set_reference_active(False)
            self.angles.show_all()  # «нажимаю «Ракурсы» — включены все»
            self._fill_angle_toggles()
            if self.model.photos:
                self.angles.show_photo(self.model.active_index)
        else:
            self._angle_states = states
            self._angle_group_state = self.group.state
            self._angle_offsets = self.group.offsets
            number = self.angles.active_photo()
            if number is not None:
                self.model.go(number)
        self._angles_on = on
        for widget in self._compare_only:
            widget.setVisible(not on)
        self.angle_toggles.setVisible(on and len(self.angles.plan.available) > 1)
        self.hint.setText(HINT_ANGLES if on else HINT)
        sync = self._sync_by_mode[on]
        self.sync_button.blockSignals(True)
        self.sync_button.setChecked(sync)
        self.sync_button.blockSignals(False)
        self.group.set_enabled(sync, measure=False)
        self.group.set_offsets(self._angle_offsets if on else self._compare_offsets)
        if sync:
            self.group.set_state(*(self._angle_group_state if on else self._compare_group_state))
        self._apply_layout()
        if not sync:
            saved = self._angle_states if on else self._compare_states
            for view in self.views:
                view.set_state(*saved.get(view, FIT_STATE))
        self.group.touch(self.active_view())
        self._show_zoom(self.active_view().state()[0])

    def _fill_angle_toggles(self):
        """Кнопка на каждый ракурс папки; нажата — у ракурса есть окно."""
        for button in self._angle_toggle_buttons.values():
            self._angle_toggle_row.removeWidget(button)
            button.setParent(None)  # иначе до deleteLater старые кнопки ещё видны рядом с новыми
            button.deleteLater()
        self._angle_toggle_buttons = {}
        plan = self.angles.plan
        for view in plan.available:
            button = self._button(str(view), lambda checked, v=view: self._toggle_angle(v, checked), checkable=True)
            button.setProperty("role", "square")
            button.setToolTip(TIP_ANGLE_TOGGLE.format(view))
            button.setChecked(view in plan.views)
            self._angle_toggle_buttons[view] = button
            self._angle_toggle_row.addWidget(button)
        self.angle_toggles.setVisible(self._angles_on and len(plan.available) > 1)

    def _toggle_angle(self, view, shown):
        if not self.angles.set_view_shown(view, shown):
            button = self._angle_toggle_buttons[view]
            button.blockSignals(True)
            button.setChecked(not shown)
            button.blockSignals(False)
            self.marks_status.setText(TEXT_ANGLE_LIMIT if shown else TEXT_ANGLE_LAST)
            return
        self.marks_status.setText("")
        self._end_flicker()
        self._strip_source = None  # цвет точки на ленте — по включённым ракурсам
        self._apply_layout()
        self.group.touch(self.active_view())

    def _fill_kinds(self):
        self.kind_box.clear()
        self.kind_box.addItem(TEXT_KIND_NONE, None)
        for kind in self._defect_kinds:
            self.kind_box.addItem(kind, kind)

    def set_defect_kinds(self, kinds):
        """Новый список видов (правка в программе, другой ПК). Выбранный у текущего фото вид остаётся на экране."""
        kinds = list(kinds)
        if kinds == self._defect_kinds:
            return
        self._defect_kinds = kinds
        current = self.kind_box.currentData()
        self._fill_kinds()
        self._select_kind(current)

    def set_kinds_editable(self, editable):
        self.kinds_button.setVisible(bool(editable))

    def _select_kind(self, kind):
        """Вид, которого уже нет в списке (удалили, другой ПК), всё равно показывается у старого замечания."""
        index = self.kind_box.findData(kind) if kind else 0
        if index < 0:
            self.kind_box.addItem(kind, kind)
            index = self.kind_box.count() - 1
        self.kind_box.setCurrentIndex(index)

    @property
    def angles_mode(self):
        return self._angles_on

    def _mark_color(self, mark):
        token = mark_token(mark)
        return theme.current().qcolor(token) if token else None

    def fit(self):
        self.group.fit()
        self._show_zoom(1.0)

    def _show_zoom(self, zoom):
        self.zoom_label.setText("{:.0f}%".format(zoom * 100))

    def _on_sync_toggled(self, checked):
        self._sync_by_mode[self._angles_on] = bool(checked)
        self.group.set_enabled(checked)

    def _visible_views(self):
        """Окна раскладки: эталон (если есть) первым, затем текущие. В «Ракурсах» окно N — всегда ракурс N."""
        if self._angles_on:
            return self.views[:len(self.angles.plan.views)]
        currents = [self._view_of(window) for window in range(self.model.currents_count)]
        return [self.views[0]] + currents if self.model.reference_window else currents

    def _view_of(self, window):
        """Текущие окна — views[1], views[2], views[3], четвёртое без эталона — views[0]: при появлении эталона
        первые три окна остаются теми же виджетами и не перечитывают фото."""
        return self.views[(window + 1) % MAX_WINDOWS]

    def _window_of(self, view):
        return (self.views.index(view) - 1) % MAX_WINDOWS

    def _is_reference_view(self, view):
        return self.model.reference_window and view is self.views[0] and not self._angles_on

    def active_view(self):
        if self._angles_on:
            return self.views[self.angles.active]
        return self.views[0] if self.model.reference_active else self._view_of(self.model.active)

    def _apply_layout(self):
        has_photos = bool(self.model.photos)
        angles = self._angles_on
        has_content = bool(self.angles.plan.sets) if angles else has_photos
        # И при одном окне: эталон там в «мигалке», а убрать его нужно уметь всегда
        self.reference_bar.setVisible(not angles and has_photos and self.model.has_reference_folder)
        texts = angle_notes(self.angles.plan) if angles else []
        self.angles_label.setText(" · ".join(texts))
        self.angles_bar.setVisible(bool(texts))
        if angles and has_photos and not has_content:
            self.message.setText(TEXT_NO_ANGLES)
        self.message.setVisible(not has_content)
        self.strip_panel.setVisible(has_content)
        self.marks_panel.setVisible(has_content)
        visible = self._visible_views() if has_content else []
        for view in self.views:
            self.grid.removeWidget(view)
            if view not in visible:
                self.group.remove(view)
                view.hide()
                view.clear()
        for view in visible:
            if view not in self.group.views:
                self.group.add(view)
        self.group.set_reference(self.views[0] if not angles and has_photos and self.model.reference_window else None)
        self._place(visible)
        for view in visible:
            view.show()
            if not angles:
                self._show_in(view)
        if angles and visible:
            self._show_angles()
        self._mark_active()
        self._sync_strip()

    def _position(self):
        """(номер, всего) в том, что листается: SN в «Ракурсах», иначе фото активного окна."""
        if self._angles_on:
            return self.angles.index, self.angles.total
        return self.model.shown_index, len(self.model.shown_photos)

    def _sync_strip(self):
        model = self.model
        source = "angles" if self._angles_on else ("reference" if model.reference_active else "folder")
        if source != self._strip_source:  # лента показывает то, что листается
            self._strip_source = source
            self.strip.set_items(self._angle_film_items() if self._angles_on else [
                FilmItem(photo.path, self._mark_color(photo.mark), photo.rotation) for photo in model.shown_photos
            ])
        self._update_marks()
        index, total = self._position()
        self.strip.set_current(index)
        self.prev_button.setEnabled(index > 0)
        self.next_button.setEnabled(index < total - 1)

    def _angle_film_items(self):
        """В «Ракурсах» одна миниатюра на SN: листание идёт по SN."""
        photos = self.model.photos
        return [
            FilmItem(photos[item.first_photo].path, self._angle_set_color(item), photos[item.first_photo].rotation)
            for item in self.angles.plan.sets
        ]

    def _angle_set_color(self, angle_set):
        return self._mark_color(angle_set_mark(angle_set, self.model.photos, self.angles.plan.views))

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
        if self._angles_on:
            numbers = self.angles.neighbor_photos()
            for number in reversed(numbers):
                self._cache.get(model.photos[number].path, L1, NEIGHBOR)
            self._request_sharp_ahead([model.photos[number] for number in numbers[: len(self.group.views)]])
            return
        shown = model.shown_photos
        wanted = [shown[number] for number in neighbor_indexes(model.shown_index, len(shown), model.direction)]
        if model.reference is not None and not model.reference_active:
            wanted.append(model.reference)
        for photo in reversed(wanted):
            self._cache.get(photo.path, L1, NEIGHBOR)
        self._request_sharp_ahead(wanted[:1])

    def _request_sharp_ahead(self, photos):
        """При увеличении L1 размыт: следующее фото готовим сразу в нужном уровне, чтобы оно открылось чётким."""
        level = max([view.needed_level for view in self.group.views] or [L1])
        if level > L1:
            for photo in photos:
                self._cache.get(photo.path, level, NEIGHBOR, exact=True)

    def _place(self, visible):
        for line in range(MAX_WINDOWS):
            self.grid.setRowStretch(line, 0)
            self.grid.setColumnStretch(line, 0)
        for view, (row, column, rows, columns) in zip(visible, grid_cells(len(visible), self._portrait)):
            self.grid.addWidget(view, row, column, rows, columns)
            self.grid.setRowStretch(row, 1)
            self.grid.setColumnStretch(column, 1)

    def _show_in(self, view):
        if self._is_reference_view(view):
            photo = self.model.reference
            self.group.show_photo(view, photo.path, photo.rotation)
            view.set_caption(self._reference_tag, self._reference_text(photo), reference=True)
            self._after_show()
            return
        window = self._window_of(view)
        photo = self.model.current(window)
        self.group.show_photo(view, photo.path, photo.rotation)
        tag = TAG_SINGLE if self.model.count == 1 else TAG_CURRENT
        position = position_text(self.model.index(window), len(self.model.photos))
        view.set_caption(tag, "{}  {}".format(position, photo.name))
        self._after_show()

    def _show_angles(self):
        """Текущий SN во всех окнах сразу: за одну отмену очереди. Нет ракурса — пустое окно с подписью."""
        angles = self.angles
        current = angles.current
        position = position_text(angles.index, angles.total)
        shown = []
        for window, number in enumerate(angles.plan.views):
            view = self.views[window]
            index = angles.photo_in(window)
            if index is None:
                view.show_missing(TEXT_NO_ANGLE.format(number))
                view.set_caption(TAG_ANGLE.format(number), "{}  {}".format(position, current.sn))
                continue
            photo = self.model.photos[index]
            shown.append((view, photo.path, photo.rotation))
            view.set_caption(TAG_ANGLE.format(number), "{}  {}".format(position, photo.name))
        self.group.show_photos(shown)
        self._after_show()

    def _reference_text(self, photo):
        model = self.model
        if not model.has_reference_folder:
            return photo.name
        return "{}  {}".format(position_text(model.ref_index, len(model.ref_photos)), photo.name)

    def _mark_active(self):
        for view in self.views:
            active = len(self._visible_views()) > 1 and view is self.active_view()
            if view.property("active") != active:
                view.setProperty("active", active)
                view.style().unpolish(view)
                view.style().polish(view)
                view.update()

    def _on_view_shown(self, view):
        self._learn_orientation(view)
        if self.model.photos and view is self.active_view():
            self._update_marks()  # фото дошло: отмечать можно

    def _learn_orientation(self, view):
        """Один раз на папку: при листании сетка не должна прыгать, даже если попалось фото другой ориентации."""
        if self._orientation_known or self._is_reference_view(view):
            return
        size = view.shown_image_size
        if size is None:
            return
        self._orientation_known = True
        self._apply_orientation(size)

    def _apply_orientation(self, size):
        portrait = size[1] >= size[0]
        self.strip.set_portrait(portrait)
        if portrait != self._portrait:
            self._portrait = portrait
            visible = self._visible_views()
            for item in visible:
                self.grid.removeWidget(item)
            self._place(visible)

    # --- отметки --------------------------------------------------------------
    @property
    def can_mark(self):
        """Отмечать можно, только пока на экране именно то фото, на которое смотрит человек."""
        model = self.model
        if not model.photos or self._flicker is not None or model.reference_active:
            return False
        number = self._marked_number()
        if number is None:
            return False
        return model.photos[number].id is not None and self.active_view().is_current_shown

    def active_photo(self):
        """Фото текущей папки в активном окне (с отметкой) или None: эталон, «мигалка», пустое окно."""
        if not self.model.photos or self.model.reference_active or self._flicker is not None:
            return None
        number = self._marked_number()
        return self.model.photos[number] if number is not None else None

    def _marked_number(self):
        """Номер фото активного окна в папке; None — в окне нет фото (у SN нет этого ракурса)."""
        return self.angles.active_photo() if self._angles_on else self.model.active_index

    def request_mark(self, mark):
        """Кнопка или клавиша: отметить фото активного окна (то же ещё раз — снять). Запись — в `mark_requested`.

        Пока запись не подтверждена, кнопки показывают старую отметку: сбой не оставляет их в неверном положении.
        """
        if self.can_mark:
            photo = self.model.photos[self._marked_number()]
            new = toggle_mark(photo.mark, mark)
            if new == "remark":
                self.mark_requested.emit(photo, new, default_sn(photo, self._name_pattern), photo.defect_kind)
            else:
                self.mark_requested.emit(photo, new, None, None)  # SN остаётся у фото
        self._update_marks()

    def _on_defect_edited(self):
        photo = self._panel_photo
        if photo is None or photo.mark != "remark" or not self.can_mark:
            return
        sn = self.sn_edit.text().strip()
        kind = self.kind_box.currentData()
        if sn != (photo.sn or "") or kind != photo.defect_kind:
            self.mark_requested.emit(photo, "remark", sn, kind)

    def apply_mark(self, photo_id, mark, sn, defect_kind):
        """Отметка записана в базу: точка на ленте, счётчики и панель обновляются сразу."""
        index = self._index_by_id.get(photo_id)
        if index is None:
            return  # папку успели сменить
        self.model.set_mark(index, mark, sn, defect_kind)
        if self._angles_on:
            place = self.angles.set_of_photo(index)
            if place is not None:
                self.strip.set_mark(place, self._angle_set_color(self.angles.plan.sets[place]))
        else:
            self.strip.set_mark(index, self._mark_color(mark))
        self.marks_status.setText("")
        self._sync_extra()
        self._update_marks()

    def show_mark_failure(self, text):
        self.marks_status.setText(text)
        self._sync_extra()

    def _update_marks(self):
        """Кнопки по фото активного окна; SN и вид — только у замечания."""
        model = self.model
        if not model.photos:
            self._panel_photo = None
            return
        number = self._marked_number()
        photo = model.photos[number] if number is not None else None
        same = photo is not None and self._panel_photo is not None and self._panel_photo.id == photo.id
        self._panel_photo = photo
        enabled = self.can_mark
        if model.reference_active:  # чужая папка: отметки не ставятся
            self.marks_title.setText(TEXT_REFERENCE_MARKS)
        elif self._angles_on:
            self.marks_title.setText(self._angles_marks_title())
        else:
            self.marks_title.setText("Фото {} —".format(position_text(model.active_index, len(model.photos))))
        for mark, button in self.mark_buttons.items():
            button.setEnabled(enabled)
            button.setChecked(photo is not None and photo.mark == mark)
        is_remark = photo is not None and photo.mark == "remark" and not model.reference_active
        self.defect_box.setVisible(is_remark)
        self._sync_extra()
        if is_remark and not (same and self.sn_edit.hasFocus()):  # пока человек печатает, поле не трогаем
            self.sn_edit.setText(default_sn(photo, self._name_pattern))
            self._select_kind(photo.defect_kind)
        self.defect_box.setEnabled(enabled)
        self.counts_label.setText(counts_text(model.photos, self._mark_keys))
        self.counts_label.setToolTip(self.counts_label.text())

    def _angles_marks_title(self):
        angles = self.angles
        current = angles.current
        if current is None:
            return ""
        return "SN {}, ракурс {} —".format(current.sn, angles.active_view_number)

    # --- поворот --------------------------------------------------------------
    def expect_sizes(self):
        """Размеры фото папки читаются в фоне: повороты группы подождут `set_sizes`."""
        self._sizes_pending = True
        self._deferred_turns = []

    def set_sizes(self, by_path):
        """{путь: (ширина, высота)}: теперь поворот знает, какие фото стоят так же, как текущее. Нажатое раньше применяется сейчас."""
        self.model.sizes = {number: by_path.get(photo.path) for number, photo in enumerate(self.model.photos)}
        self._sizes_pending = False
        turns, self._deferred_turns = self._deferred_turns, []
        if turns:
            self.marks_status.setText("")
            self._sync_extra()
        for delta, whole_angle in turns:
            self.rotate(delta, whole_angle)

    def rotate(self, delta, whole_angle=False):
        """Кнопка или клавиша поворота. Пока идёт «мигалка» — нельзя.

        «Синхронно» включена — все окна вместе, у каждого весь его ракурс (фото, стоящие так же, как в окне).
        Выключена — одно фото активного окна: так исправляют неверно повёрнутое. whole_angle (Shift) — весь ракурс
        активного окна, остальные окна не трогаются: так выравнивают окна между собой или один ракурс во всех SN.
        """
        if self._flicker is not None or not self.model.photos:
            return
        if self._sizes_pending and (whole_angle or self.sync_button.isChecked()):
            self._deferred_turns.append((delta, whole_angle))  # одному фото размеры не нужны
            self.marks_status.setText(TEXT_SIZES_PENDING)
            self._sync_extra()
            return
        if whole_angle:
            self._rotate_angle(delta) if self._angles_on else self._rotate_active(delta)
        elif not self.sync_button.isChecked():
            self._rotate_one(delta)
        elif self._angles_on:
            self._rotate_angle_windows(delta)
        else:
            self._rotate_windows(delta)

    def _rotate_one(self, delta):
        """Только фото активного окна. Эталон чужой: поворачивается в памяти."""
        if self.model.reference_active:
            changed = self.model.rotate_reference_one(delta)
        else:
            number = self._marked_number()
            if number is None:
                return  # в «Ракурсах» у SN нет этого ракурса
            changed = self.model.rotate_one(number, delta)
        if self._angles_on:
            self.active_view().set_rotation(self.model.photos[number].rotation)
            self._after_angle_rotate(changed)
            return
        for view, rotation in self._window_rotations():
            view.set_rotation(rotation)
        self._after_rotate(changed)

    def _rotate_angle_windows(self, delta):
        """«Ракурсы» с синхронностью: все окна вместе, у каждого весь его ракурс. Место — общее, как в «Сравнении»."""
        windows = [(self.views[window], self.angles.photo_in(window)) for window in range(len(self.angles.plan.views))]
        changed = {}
        for _, number in windows:
            if number is not None and number not in changed:
                changed.update(self.model.rotate_angle(number, delta, self._name_pattern))
        photos = self.model.photos
        self.group.rotate(delta, [(view, photos[number].rotation) for view, number in windows if number is not None])
        self._after_angle_rotate(changed)

    def _rotate_windows(self, delta):
        model = self.model
        changed = model.rotate_windows(delta, self._name_pattern)
        self.group.rotate(delta, self._window_rotations())
        self._after_rotate(changed)

    def _rotate_active(self, delta):
        """Группу не трогаем: у окон свои места. Другое текущее окно с тем же ракурсом повернётся вместе с активным."""
        changed = self.model.rotate_active(delta, self._name_pattern)
        for view, rotation in self._window_rotations():
            view.set_rotation(rotation)
        self._after_rotate(changed)

    def _window_rotations(self):
        model = self.model
        result = []
        for view in self._visible_views():
            photo = model.reference if self._is_reference_view(view) else model.current(self._window_of(view))
            result.append((view, photo.rotation))
        return result

    def _after_rotate(self, changed):
        self.strip.set_rotations([photo.rotation for photo in self.model.shown_photos])
        size = self.active_view().shown_image_size
        if size is not None:  # сетка и лента — по новой ориентации; при листании они по-прежнему не прыгают
            self._orientation_known = True
            self._apply_orientation(size)
        self._save_rotations(changed)

    def _rotate_angle(self, delta):
        """Окно ракурса поворачивается само по себе. Сетка не меняется: ракурс N всегда на одном месте."""
        number = self.angles.active_photo()
        if number is None:
            return  # у SN нет этого ракурса
        changed = self.model.rotate_angle(number, delta, self._name_pattern)
        self.active_view().set_rotation(changed[number])
        self._after_angle_rotate(changed)

    def _after_angle_rotate(self, changed):
        photos = self.model.photos
        self.strip.set_rotations([photos[item.first_photo].rotation for item in self.angles.plan.sets])
        self._save_rotations(changed)

    def _save_rotations(self, changed):
        """{номер фото: поворот} в базу, по одной записи на каждый поворот: окна разных ракурсов могут стоять по-разному."""
        grouped = {}
        for index, rotation in changed.items():
            photo_id = self.model.photos[index].id
            if photo_id is not None:
                grouped.setdefault(rotation, []).append(photo_id)
        for rotation, photo_ids in grouped.items():
            self.rotation_changed.emit(photo_ids, rotation)

    # --- листание и «мигалка» -------------------------------------------------
    def flip(self, step):
        self.go(self._position()[0] + step)

    def go(self, index):
        """Перейти в активном окне к фото с этим номером: стрелки, кнопки, клик по ленте. В «Ракурсах» — все окна к SN."""
        if self._angles_on:
            self._go_angles(index)
            return
        if self._flicker is not None or not self.model.go(index):
            return
        self._show_in(self.active_view())
        self._sync_strip()
        if self.model.reference_active:
            self._check_angle()
            return  # чужая папка: событие photo.changed только про текущую
        window = self.model.active
        self.photo_changed.emit(self.model.current(window), self.model.index(window))

    def _go_angles(self, index):
        if not self.angles.go(index):
            return
        self._show_angles()
        self._sync_strip()
        number = self.angles.active_photo()
        if number is not None:  # у SN нет ракурса активного окна: сообщать не о чем
            self.photo_changed.emit(self.model.photos[number], number)

    def _begin_flicker(self):
        if self._angles_on:
            return  # эталона здесь нет
        if self._flicker is not None or self.model.reference is None or self.model.reference_active:
            return
        view = self.active_view()
        self._flicker = (view, view.state())
        self.group.show_photo(view, self.model.reference.path, self.model.reference.rotation)
        view.set_caption(self._reference_tag, self._reference_text(self.model.reference), reference=True)
        self._update_marks()

    def _end_flicker(self):
        if self._flicker is None:
            return
        view, state = self._flicker
        self._flicker = None
        self._show_in(view)
        if not self.group.enabled:  # иначе место вернёт группа
            view.set_state(*state)
        self._update_marks()

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
        elif key == self._toggle_ui_key:
            if not event.isAutoRepeat():
                self.toggle_interface()
        elif key in self._rotate_keys:
            if not event.isAutoRepeat():  # удержание крутило бы фото и писало в базу без остановки
                self.rotate(self._rotate_keys[key], whole_angle=bool(event.modifiers() & Qt.ShiftModifier))
        elif key in self._mark_by_key:
            if not event.isAutoRepeat():
                self.request_mark(self._mark_by_key[key])
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
        if self._flicker is not None:
            return
        if self._angles_on:
            self.angles.set_active(self.views.index(view))
            self._show_zoom(view.state()[0])
        elif self._is_reference_view(view):
            if not self.model.has_reference_folder:
                return  # одиночный эталон не листается: активным остаётся прежнее окно
            self.model.set_reference_active(True)
        else:
            self.model.set_active(self._window_of(view))
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
