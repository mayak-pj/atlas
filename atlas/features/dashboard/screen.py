"""Экран «Дашборд». Только рисует готовую Stats, в базу не ходит."""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from atlas.features.dashboard import logic
from atlas.features.dashboard.charts import BarChart
from atlas.shared.widgets.flow import FlowLayout

TEXT_ALL_KINDS = "Все проекты"
TEXT_TOP = "Детали с наибольшим числом замечаний"
TEXT_KINDS = "Вид замечаний"
TEXT_CLEAN = "Детали без проблем за {} дн."
TEXT_CLEAN_EMPTY = "Таких деталей пока нет: проверенные детали все с замечаниями или проверок не было"
TEXT_MORE = "и ещё {}"
TEXT_LOAD_FAILED = "Не удалось прочитать данные: цифры могут быть устаревшими"
TEXT_FOLDERS = "Проверено папок"
TEXT_PHOTOS = "Фото в проверенных папках"
TEXT_PROBLEMS = "Замечания"
TEXT_TYPES = "Новые типы"
TEXT_TYPES_NOTE = "добавлено в базу"


def _label(text, role=None, wrap=False):
    label = QLabel(text)
    if role:
        label.setProperty("role", role)
    label.setWordWrap(wrap)
    label.setTextInteractionFlags(Qt.NoTextInteraction)
    return label


def _panel():
    frame = QFrame()
    frame.setProperty("role", "panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    return frame, layout


class Kpi(QFrame):
    def __init__(self, caption, tone=None, parent=None):
        super().__init__(parent)
        self.setProperty("role", "panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)
        layout.addWidget(_label(caption, "caption"))
        self.value = _label("–", "kpi")
        if tone:
            self.value.setProperty("tone", tone)
        layout.addWidget(self.value)
        self.note = _label("", "muted")
        layout.addWidget(self.note)

    def set_value(self, value, note):
        self.value.setText(str(value))
        self.note.setText(note)


class DashboardScreen(QWidget):
    period_changed = pyqtSignal(str)
    kind_changed = pyqtSignal(str)
    shown = pyqtSignal()

    def __init__(self, kinds=(), parent=None):
        super().__init__(parent)
        self.period = logic.MONTH
        self.kind = logic.ALL_KINDS
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setProperty("role", "plain")
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        body.setProperty("role", "plain")
        scroll.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        head = QHBoxLayout()
        self.title = _label("", "heading")
        head.addWidget(self.title)
        self.error = _label("", "warn")
        head.addWidget(self.error)
        head.addStretch(1)
        self.period_buttons = self._chips(head, [(key, text) for key, text in logic.PERIODS], logic.MONTH,
                                          self._on_period)
        self.kind_buttons = {}
        if len(kinds) > 1:
            head.addSpacing(12)
            self.kind_buttons = self._chips(head, [(logic.ALL_KINDS, TEXT_ALL_KINDS)] + [(k, k) for k in kinds],
                                            logic.ALL_KINDS, self._on_kind)
        root.addLayout(head)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.kpi_folders = Kpi(TEXT_FOLDERS)
        self.kpi_photos = Kpi(TEXT_PHOTOS)
        self.kpi_problems = Kpi(TEXT_PROBLEMS, "defect")
        self.kpi_types = Kpi(TEXT_TYPES, "type2")
        for column, kpi in enumerate((self.kpi_folders, self.kpi_photos, self.kpi_problems, self.kpi_types)):
            grid.addWidget(kpi, 0, column)
            grid.setColumnStretch(column, 1)
        root.addLayout(grid)

        charts = QHBoxLayout()
        charts.setSpacing(12)
        top_panel, top_layout = _panel()
        top_layout.addWidget(_label(TEXT_TOP, "caption"))
        self.top_chart = BarChart("accent")
        top_layout.addWidget(self.top_chart)
        top_layout.addStretch(1)
        kinds_panel, kinds_layout = _panel()
        kinds_layout.addWidget(_label(TEXT_KINDS, "caption"))
        self.kinds_chart = BarChart("remark")
        kinds_layout.addWidget(self.kinds_chart)
        kinds_layout.addStretch(1)
        charts.addWidget(top_panel, 3)
        charts.addWidget(kinds_panel, 2)
        root.addLayout(charts)

        clean_panel, clean_layout = _panel()
        self.clean_title = _label(TEXT_CLEAN.format(logic.CLEAN_DAYS), "caption")
        clean_layout.addWidget(self.clean_title)
        self.clean_box = QWidget()
        self.clean_box.setProperty("role", "plain")
        self.clean_flow = FlowLayout(self.clean_box, spacing=8)
        clean_layout.addWidget(self.clean_box)
        self.clean_empty = _label(TEXT_CLEAN_EMPTY, "muted", wrap=True)
        clean_layout.addWidget(self.clean_empty)
        root.addWidget(clean_panel)
        root.addStretch(1)

    def _chips(self, layout, items, current, slot):
        group = QButtonGroup(self)
        group.setExclusive(True)
        buttons = {}
        for key, text in items:
            button = QPushButton(text)
            button.setProperty("role", "chip")
            button.setCheckable(True)
            button.setChecked(key == current)
            button.clicked.connect(lambda _checked, k=key: slot(k))
            group.addButton(button)
            layout.addWidget(button)
            buttons[key] = button
        return buttons

    def _on_period(self, key):
        self.period = key
        self.period_changed.emit(key)

    def _on_kind(self, key):
        self.kind = key
        self.kind_changed.emit(key)

    def showEvent(self, event):
        super().showEvent(event)
        self.shown.emit()

    def show_error(self, text):
        self.error.setText(text)

    def set_stats(self, stats):
        self.error.setText("")
        self.title.setText(stats.label)
        self.kpi_folders.set_value(stats.folders, stats.note)
        self.kpi_photos.set_value(stats.photos, stats.note)
        self.kpi_problems.set_value(stats.problems, "на {} деталях".format(stats.problem_parts))
        self.kpi_types.set_value(stats.new_types, TEXT_TYPES_NOTE)
        self.top_chart.set_rows(stats.top_parts)
        self.kinds_chart.set_rows(stats.kinds)
        while self.clean_flow.count():
            item = self.clean_flow.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
                item.widget().deleteLater()
        for name in stats.clean_parts:
            pill = _label(name, "pill")
            pill.setProperty("tone", "ok")
            self.clean_flow.addWidget(pill)
        if stats.clean_more:
            self.clean_flow.addWidget(_label(TEXT_MORE.format(stats.clean_more), "muted"))
        self.clean_empty.setVisible(not stats.clean_parts)
