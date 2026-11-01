"""Главное окно: верхняя полоса (ATLAS · вкладки · онлайн · пользователь · настройки), строка контекста, страницы вкладок.

Функции получают окно как ctx.shell:
    ctx.shell.add_panel("shell.user", widget, key="login")      # положить панель в слот
    ctx.shell.register_slot("compare.right", layout)            # создать слот в своём экране
    ctx.shell.set_context(kind="A", project="Орион-24", ...)   # строка контекста
"""
from __future__ import annotations

import logging

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget, QTabBar, QVBoxLayout, QWidget,
)

from atlas.core import theme
from atlas.core.shell.slots import SlotRegistry
from atlas.shared.widgets import ContextBar, LogoMark
from atlas.shared.widgets.icons import set_icon

log = logging.getLogger("atlas.shell")

SLOT_USER = "shell.user"
SLOT_ONLINE = "shell.online"


class ShellWindow(QMainWindow):
    settings_requested = pyqtSignal()
    theme_chosen = pyqtSignal(str)  # "dark" | "light": выбор из меню настроек; применяет тот, кто владеет запуском

    def __init__(self, ctx=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.current_theme = theme.DEFAULT_THEME
        self.slots = SlotRegistry()
        self._items = []
        self.setWindowTitle("Atlas")
        self.resize(1280, 800)
        self.setMinimumSize(QSize(1024, 640))

        root = QWidget()
        column = QVBoxLayout(root)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._build_top_bar())
        show_kind = bool(ctx.config.get("ui.show_project_kind", True)) if ctx is not None else True
        self.context_bar = ContextBar(show_kind=show_kind)
        column.addWidget(self.context_bar)
        self.pages = QStackedWidget()
        column.addWidget(self.pages, 1)
        self.setCentralWidget(root)

        self._empty = QLabel("Нет включённых функций с вкладками")
        self._empty.setProperty("role", "muted")
        self._empty.setAlignment(Qt.AlignCenter)
        self.pages.addWidget(self._empty)
        self.tab_bar.currentChanged.connect(self._on_tab_changed)

    # --- сборка ---------------------------------------------------------------
    def _build_top_bar(self):
        bar = QFrame()
        bar.setObjectName("TopBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 6, 16, 6)
        row.setSpacing(12)
        row.addWidget(LogoMark(28))
        brand = QLabel("ATLAS")
        brand.setObjectName("Brand")
        row.addWidget(brand)
        row.addSpacing(8)
        self.tab_bar = QTabBar()
        self.tab_bar.setExpanding(False)
        self.tab_bar.setDrawBase(False)
        self.tab_bar.setFocusPolicy(Qt.NoFocus)
        row.addWidget(self.tab_bar)
        row.addStretch(1)
        for name in (SLOT_ONLINE, SLOT_USER):
            holder = QHBoxLayout()
            holder.setSpacing(8)
            row.addLayout(holder)
            self.slots.register_slot(name, holder)
        self.settings_button = QPushButton()
        self.settings_button.setProperty("role", "icon")
        self.settings_button.setToolTip("Настройки")
        set_icon(self.settings_button, "settings", size=18)
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.clicked.connect(self._show_settings_menu)
        row.addWidget(self.settings_button)
        return bar

    def _show_settings_menu(self):
        from PyQt5.QtWidgets import QActionGroup, QMenu

        self.settings_requested.emit()
        menu = QMenu(self)
        title = menu.addAction("Тема оформления")
        title.setEnabled(False)
        group = QActionGroup(menu)
        current = self.current_theme
        for name, text in theme.THEME_TITLES.items():
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(name == current)
            action.setActionGroup(group)
            action.triggered.connect(lambda _=False, n=name: self.theme_chosen.emit(n))
        menu.exec_(self.settings_button.mapToGlobal(self.settings_button.rect().bottomLeft()))
        menu.deleteLater()

    # --- вкладки --------------------------------------------------------------
    def set_tabs(self, items):
        """items — LoadedFeature с вкладкой, уже в нужном порядке (registry.tabs())."""
        self.tab_bar.blockSignals(True)
        while self.tab_bar.count():
            self.tab_bar.removeTab(0)
        while self.pages.count() > 1:
            self.pages.removeWidget(self.pages.widget(1))
        self._items = list(items)
        for item in self._items:
            self.tab_bar.addTab(item.spec.title)
            self.pages.addWidget(item.tab)
        self.tab_bar.blockSignals(False)
        self.refresh_badges()
        if self._items:
            self.tab_bar.setCurrentIndex(0)
            self._on_tab_changed(0)
        else:
            self.pages.setCurrentWidget(self._empty)

    def refresh_badges(self):
        """Счётчик на вкладке: Feature.badge() вернул число/текст — показываем, None/0 — нет."""
        for index, item in enumerate(self._items):
            try:
                value = item.instance.badge()
            except Exception:
                log.exception("Ошибка badge() функции %s", item.spec.id)
                value = None
            old = self.tab_bar.tabButton(index, QTabBar.RightSide)
            if old is not None:
                self.tab_bar.setTabButton(index, QTabBar.RightSide, None)
                old.deleteLater()
            if value:
                label = QLabel(str(value))
                label.setObjectName("TabBadge")
                self.tab_bar.setTabButton(index, QTabBar.RightSide, label)

    def current_tab_id(self):
        index = self.tab_bar.currentIndex()
        return self._items[index].spec.id if 0 <= index < len(self._items) else None

    def select_tab(self, feature_id):
        for index, item in enumerate(self._items):
            if item.spec.id == feature_id:
                self.tab_bar.setCurrentIndex(index)
                return True
        return False

    def tab_titles(self):
        return [self.tab_bar.tabText(i) for i in range(self.tab_bar.count())]

    def _on_tab_changed(self, index):
        if 0 <= index < len(self._items):
            self.pages.setCurrentWidget(self._items[index].tab)

    # --- слоты и контекст (API для функций) -----------------------------------
    def register_slot(self, name, layout):
        self.slots.register_slot(name, layout)

    def add_panel(self, slot, widget, key=None, order=0):
        return self.slots.add_panel(slot, widget, key, order)

    def remove_panel(self, slot, key):
        self.slots.remove_panel(slot, key)

    def set_context(self, kind=None, project=None, device=None, part=None, path=None):
        self.context_bar.set_context(kind, project, device, part, path)

    def show_message(self, text, timeout_ms=0):
        self.statusBar().showMessage(text, timeout_ms)
