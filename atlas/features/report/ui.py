from __future__ import annotations

import logging
import sys
import threading
from datetime import datetime

from PyQt5.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QFrame, QLabel, QPushButton, QTextBrowser, QVBoxLayout

from atlas.core.feature import Feature
from atlas.features.report import logic, xlsx

log = logging.getLogger("atlas.report")

SLOT = "draft.actions"
PANEL_KEY = "report"
DEFAULT_EXCEL_DIR = "var/reports"  # TODO(OPEN_ITEMS №5): куда класть Excel
RELOAD_MS = 400
MESSAGE_MS = 8000
STOP_WAIT_S = 3.0
TEXT_TITLE = "Ответное письмо"
TEXT_EXCEL = "Записать в Excel"
TEXT_MAIL = "Открыть в Outlook как ответ"
TEXT_NO_FOLDER = "Откройте папку в «Сравнении»"
TEXT_EXCEL_OK = "Excel записан: {}"
TEXT_MAIL_OK = "Письмо открыто в Outlook, папка отмечена как готовая. Проверьте и отправьте сами"
TEXT_MAIL_FILE = "Письмо сохранено в файл (Outlook на этой машине не используется): {}"
TEXT_FAILED = "Не получилось: {}"


class _Signals(QObject):
    preview = pyqtSignal(int, str)
    excel_done = pyqtSignal(str)
    mail_done = pyqtSignal(int, str)  # папка, путь файла вместо Outlook или ""
    failed = pyqtSignal(str)


def _outlook():
    if sys.platform == "win32":
        from atlas.features.report import outlook_win as module
    else:
        from atlas.features.report import outlook_fake as module
    return module


class ReportPanel(QFrame):
    excel_requested = pyqtSignal()
    mail_requested = pyqtSignal()
    shown = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QLabel(TEXT_TITLE)
        title.setProperty("role", "label")
        layout.addWidget(title)
        self.subject = QLabel("")
        self.subject.setWordWrap(True)
        layout.addWidget(self.subject)
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.setMinimumHeight(180)
        layout.addWidget(self.view, 1)
        self.excel_button = QPushButton(TEXT_EXCEL)
        self.excel_button.clicked.connect(self.excel_requested)
        self.mail_button = QPushButton(TEXT_MAIL)
        self.mail_button.setProperty("tone", "primary")
        self.mail_button.clicked.connect(self.mail_requested)
        layout.addWidget(self.excel_button)
        layout.addWidget(self.mail_button)
        self.set_enabled(False)

    def set_enabled(self, enabled):
        self.excel_button.setEnabled(enabled)
        self.mail_button.setEnabled(enabled)

    def set_preview(self, subject, html):
        self.subject.setText(subject)
        self.view.setHtml(html)

    def showEvent(self, event):
        super().showEvent(event)
        self.shown.emit()


class ReportFeature(Feature):
    """Кнопки «Записать в Excel» и «Открыть в Outlook как ответ» + предпросмотр письма в слоте `draft.actions`.

    Данные — сервис `draft.snapshot`; нет `draft` — панели нет. Письмо только открывается (`Display`), не отправляется;
    после открытия папка получает статус «готово» и событие `folder.done`.
    """

    def on_start(self):
        self._stopped = False
        self._threads = []
        self._busy = False
        self.folder_id = None
        self.panel = None
        self.signals = _Signals()
        self.signals.preview.connect(self._on_preview)
        self.signals.excel_done.connect(self._on_excel)
        self.signals.mail_done.connect(self._on_mail)
        self.signals.failed.connect(self._on_failed)
        config = self.ctx.config
        self.excel_dir = self.ctx.paths.resolve(str(config.get("report.excel_dir", DEFAULT_EXCEL_DIR)))
        self.work_dir = self.ctx.paths.resolve(str(config.get("report.work_dir", "var/report")))
        self.subject_pattern = str(config.get("report.subject", logic.DEFAULT_SUBJECT))
        self.sheet, self.columns = logic.load_columns(self.ctx.paths.templates)
        self.template = logic.load_mail(self.ctx.paths.templates)
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.setInterval(RELOAD_MS)
        self.timer.timeout.connect(self.refresh)
        bus = self.ctx.bus
        self._unsubscribe = [bus.subscribe("folder.opened", self._on_opened)]
        for name in ("photo.marked", "folder.sorted", "draft.changed"):
            self._unsubscribe.append(bus.subscribe(name, lambda _p: self.timer.start()))
        if self.ctx.services.get_optional("draft") is not None and self.ctx.shell is not None:
            self.panel = ReportPanel()
            self.panel.excel_requested.connect(self.write_excel)
            self.panel.mail_requested.connect(self.open_mail)
            self.panel.shown.connect(self.refresh)
            self.ctx.shell.add_panel(SLOT, self.panel, key=PANEL_KEY, order=10)

    def on_stop(self):
        self._stopped = True
        self.timer.stop()
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        for thread in list(self._threads):
            thread.join(STOP_WAIT_S)

    # --- сбор ---------------------------------------------------------------------
    def _user(self):
        return self.ctx.user

    def _gather(self, folder_id):
        """(контекст, строки черновика, заметки). Не из GUI-потока."""
        services = self.ctx.services
        folders = services.get("folders")
        folder = folders.get(folder_id)
        part = services.get("parts").get(folder.part_id)
        user = self._user()
        snapshot = services.get("draft").snapshot(folder_id, user.id if user else None)
        context = {"part": part.name, "device": part.device, "project": part.project,
                   "date": logic.date_text(folder.folder_date), "photos_total": len(folders.photos(folder_id)),
                   "user": user.name if user else "", "folder_path": folder.path}
        return context, snapshot.entries, snapshot.notes

    def _spawn(self, target, *args):
        thread = threading.Thread(target=target, args=args, daemon=True)
        self._threads = [t for t in self._threads if t.is_alive()] + [thread]
        thread.start()

    def _on_opened(self, payload):
        self.folder_id = payload.get("folder_id")
        if self.panel is not None:
            self.panel.set_enabled(self.folder_id is not None)
        self.timer.start()

    def refresh(self):
        if self._stopped or self.panel is None or self.folder_id is None:
            return
        self._spawn(self._build_preview, self.folder_id)

    def _letter(self, context, entries, notes):
        html = logic.render(self.template, logic.mail_values(entries, context, notes))
        return logic.subject(self.subject_pattern, context), html

    def _build_preview(self, folder_id):
        try:
            subject, html = self._letter(*self._gather(folder_id))
        except Exception as exc:  # нет сети, база занята: остаётся прежнее
            log.warning("Не удалось собрать письмо: %s", exc)
            return
        self.signals.preview.emit(folder_id, "Тема: " + subject + "\n" + html)

    def _on_preview(self, folder_id, packed):
        if self._stopped or self.panel is None or folder_id != self.folder_id:
            return
        subject, _, html = packed.partition("\n")
        self.panel.set_preview(subject, html)

    # --- Excel ----------------------------------------------------------------------
    def write_excel(self):
        if self.folder_id is not None and not self._busy:
            self._set_busy(True)
            self._spawn(self._excel, self.folder_id)

    def _excel(self, folder_id):
        try:
            context, entries, _notes = self._gather(folder_id)
            self.excel_dir.mkdir(parents=True, exist_ok=True)
            path = self.excel_dir / logic.file_name(context, datetime.now().strftime("%H%M%S"))
            xlsx.write(path, self.sheet, [title for _k, title, _w in self.columns],
                       logic.rows(entries, context, self.columns), [w for _k, _t, w in self.columns])
        except Exception as exc:
            log.warning("Не удалось записать Excel: %s", exc)
            self.signals.failed.emit(str(exc))
            return
        self.signals.excel_done.emit(str(path))

    def _on_excel(self, path):
        self._set_busy(False)
        self._say(TEXT_EXCEL_OK.format(path))
        self._show_file(path)

    def _show_file(self, path):
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # --- Outlook --------------------------------------------------------------------
    def open_mail(self):
        if self.folder_id is not None and not self._busy:
            self._set_busy(True)
            self._spawn(self._mail, self.folder_id)

    def _mail(self, folder_id):
        try:
            subject, html = self._letter(*self._gather(folder_id))
            # TODO(6.1): ответом на исходное письмо — пока письма с папкой не связаны, создаётся новое
            saved = _outlook().open_mail(subject, html, self.work_dir)
            user = self._user()
            self.ctx.services.get("folders").set_status(folder_id, "done", user.id if user else None)
        except Exception as exc:
            log.warning("Не удалось открыть письмо: %s", exc)
            self.signals.failed.emit(str(exc))
            return
        self.signals.mail_done.emit(folder_id, str(saved) if saved else "")

    def _on_mail(self, folder_id, saved):
        self._set_busy(False)
        self.ctx.bus.publish("folder.done", {"folder_id": folder_id})
        self._say(TEXT_MAIL_FILE.format(saved) if saved else TEXT_MAIL_OK)

    def _on_failed(self, text):
        self._set_busy(False)
        self._say(TEXT_FAILED.format(text))

    def _set_busy(self, busy):
        self._busy = busy
        if self.panel is not None:
            self.panel.set_enabled(not busy and self.folder_id is not None)

    def _say(self, text):
        if not self._stopped and self.ctx.shell is not None:
            self.ctx.shell.show_message(text, MESSAGE_MS)
