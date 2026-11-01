from __future__ import annotations

import logging
import threading
from datetime import datetime

from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from atlas.core import theme
from atlas.core.feature import Feature
from atlas.features.folders import logic

log = logging.getLogger("atlas.folders")

SLOT_LEFT = "compare.left"
PANEL_KEY = "folders"
DEFAULT_REFRESH_S = 60  # чужие папки появляются без событий: ходим в базу сами
STOP_WAIT_S = 2.0  # сеть могла пропасть: дольше не держим закрытие программы
TITLE_NEW = "Новые — не проверены"
TITLE_DONE = "Проверено на этой неделе"
TEXT_EMPTY_NEW = "Новых папок нет"
TEXT_EMPTY_DONE = "На этой неделе ничего не проверено"
TEXT_COMPARE_OFF = "Экран сравнения выключен"
REFRESH_EVENTS = ("folder.copied", "folder.opened", "folder.done", "photo.marked")


class _Signals(QObject):
    loaded = pyqtSignal(object)  # Snapshot или None, если база недоступна


class FolderCard(QFrame):
    """Карточка папки; клик открывает её. Состояния — свойства Qt для QSS."""

    clicked = pyqtSignal(int)

    def __init__(self, entry, selected, worker_text, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.setProperty("role", "folder")
        self.setProperty("on", bool(selected))
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(entry.title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(6)
        title = QLabel(entry.title)
        title.setProperty("role", "folder-title")
        title.setWordWrap(True)  # без переноса длинное название распирало карточку шире колонки и обрезалось
        head.addWidget(title, 1)
        if entry.pill:
            pill = QLabel(entry.pill)
            pill.setProperty("role", "pill")
            pill.setProperty("tone", entry.pill_token)
            head.addWidget(pill)
        layout.addLayout(head)
        for text, role in ((entry.subtitle, "dim"), (entry.note, "muted")):
            if text:
                label = QLabel(text)
                label.setProperty("role", role)
                label.setWordWrap(True)
                layout.addWidget(label)
        if worker_text:
            label = QLabel(worker_text)
            label.setProperty("role", "ok")
            layout.addWidget(label)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.entry.folder_id)
        super().mousePressEvent(event)


class FoldersPanel(QFrame):
    folder_chosen = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "panel")
        self.cards = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setProperty("role", "plain")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll)
        self.body = QWidget()
        self.body.setProperty("role", "plain")
        self.scroll.setWidget(self.body)
        self.column = QVBoxLayout(self.body)
        self.column.setContentsMargins(12, 12, 12, 12)
        self.column.setSpacing(8)
        self.column.addStretch(1)

    def show_snapshot(self, snapshot, selected_id, workers):
        """workers: {folder_id: текст «Кузнецова работает»}. Перестраивает список, прокрутка сохраняется."""
        bar = self.scroll.verticalScrollBar()
        position = bar.value()
        while self.column.count() > 1:
            item = self.column.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.cards = []
        self._header(TITLE_NEW, snapshot.new_total)
        self._cards(snapshot.new, selected_id, workers, TEXT_EMPTY_NEW)
        separator = QFrame()
        separator.setProperty("role", "hsep")
        self.column.insertWidget(self.column.count() - 1, separator)
        self._header(TITLE_DONE, None)
        self._cards(snapshot.done, selected_id, workers, TEXT_EMPTY_DONE)
        QTimer.singleShot(0, lambda: bar.setValue(position))

    def _add(self, widget):
        self.column.insertWidget(self.column.count() - 1, widget)

    def _header(self, text, count):
        row = QWidget()
        row.setProperty("role", "plain")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel(text)
        title.setProperty("role", "caption")
        layout.addWidget(title, 1)
        if count:
            pill = QLabel(str(count))
            pill.setProperty("role", "pill")
            pill.setProperty("tone", "type2")
            pill.setMinimumWidth(30)
            pill.setAlignment(Qt.AlignCenter)
            layout.addWidget(pill)
        self._add(row)

    def _cards(self, entries, selected_id, workers, empty_text):
        if not entries:
            label = QLabel(empty_text)
            label.setProperty("role", "muted")
            label.setWordWrap(True)
            self._add(label)
        for entry in entries:
            card = FolderCard(entry, entry.folder_id == selected_id, workers.get(entry.folder_id, ""))
            card.clicked.connect(self.folder_chosen)
            self.cards.append(card)
            self._add(card)


class FoldersFeature(Feature):
    """Левая панель экрана сравнения. Данные — сервис ядра «folders», открытие — сервис «compare»."""

    def on_start(self):
        self.snapshot = logic.Snapshot([], 0, [])
        self.selected_id = None
        self._stopped = False
        self._thread = None
        self._again = False
        self.signals = _Signals()
        self.signals.loaded.connect(self._on_loaded)
        self.panel = FoldersPanel()
        self.panel.folder_chosen.connect(self._on_chosen)
        self.timer = QTimer()
        self.timer.setInterval(int(self.ctx.config.get("folders.refresh_s", DEFAULT_REFRESH_S) * 1000))
        self.timer.timeout.connect(self.refresh)
        bus = self.ctx.bus
        self._unsubscribe = [bus.subscribe(name, self._on_event) for name in REFRESH_EVENTS]
        self._unsubscribe.append(bus.subscribe("folder.opened", self._on_opened))
        self._unsubscribe.append(bus.subscribe("presence.changed", self._on_presence))
        if self.ctx.shell is not None:
            self.ctx.shell.add_panel(SLOT_LEFT, self.panel, key=PANEL_KEY)
        self.timer.start()
        self.refresh()

    def on_stop(self):
        self._stopped = True
        self.timer.stop()
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        if self._thread is not None:
            self._thread.join(STOP_WAIT_S)

    # --- события --------------------------------------------------------------
    def _on_event(self, _payload):
        self.refresh()

    def _on_opened(self, payload):
        self.selected_id = payload.get("folder_id")
        self._render()

    def _on_presence(self, _payload):
        self._render()

    def _on_chosen(self, folder_id):
        compare = self.ctx.services.get_optional("compare")
        if compare is None:
            if self.ctx.shell is not None:
                self.ctx.shell.show_message(TEXT_COMPARE_OFF, 5000)
            return
        compare.open_folder(folder_id)

    # --- чтение базы: в фоне и по одному запросу ------------------------------
    def refresh(self):
        if self._stopped:
            return
        if self._thread is not None:
            self._again = True
            return
        self._thread = threading.Thread(target=self._work, daemon=True)
        self._thread.start()

    def _work(self):
        try:
            snapshot = self._read()
        except Exception as exc:  # нет сети, база занята: остаётся прежний список, следующее обновление — по таймеру
            log.warning("Не удалось прочитать папки: %s", exc)
            snapshot = None
        self.signals.loaded.emit(snapshot)

    def _read(self):
        services = self.ctx.services
        folders, parts = services.get("folders"), services.get("parts")
        limit = self.ctx.config.get("folders.limit", logic.DEFAULT_LIMIT)
        days = self.ctx.config.get("folders.done_days", logic.DEFAULT_DONE_DAYS)
        now = datetime.now()
        new = folders.recent(limit, status="new")
        done = [item for item in folders.recent(limit, status="done") if logic.is_recent(item.status_at, now, days)]
        counts = folders.counts([item.id for item in new + done])
        names = {user.id: user.name for user, _ in services.get("users").all()}
        cache = {}

        def part_of(folder):
            if folder.part_id not in cache:
                cache[folder.part_id] = parts.get(folder.part_id)
            return cache[folder.part_id]

        return logic.Snapshot(
            [logic.new_entry(item, part_of(item), counts.get(item.id)) for item in new],
            len(new),
            [logic.done_entry(item, part_of(item), counts.get(item.id), names.get(item.status_by, "")) for item in done],
        )

    def _on_loaded(self, snapshot):
        self._thread = None
        if self._stopped:
            return
        if snapshot is not None:  # база недоступна — держим прежний список
            self.snapshot = snapshot
            self._render()
        if self._again:
            self._again = False
            self.refresh()

    def _render(self):
        self.panel.show_snapshot(self.snapshot, self.selected_id, self._workers())

    def _workers(self):
        """{folder_id: «Кузнецова работает»} — без себя."""
        presence = self.ctx.services.get_optional("presence")
        if presence is None:
            return {}
        me = self.ctx.user.id if self.ctx.user is not None else None
        names = {}
        for item in presence.online():
            if item.folder_id is not None and item.user_id != me:
                names.setdefault(item.folder_id, []).append(item.name)
        return {folder_id: logic.workers_text(people) for folder_id, people in names.items()}
