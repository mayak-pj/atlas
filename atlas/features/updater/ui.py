"""Сверка версии в фоне (сетевой диск) и вопрос пользователю, когда окно уже открыто."""
from __future__ import annotations

import logging
import threading

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication, QMessageBox

from atlas.core.feature import Feature
from atlas.core.release import current_version
from atlas.features.updater import logic

log = logging.getLogger("atlas.updater")

WAIT_WINDOW_MS = 500


class _Signals(QObject):
    found = pyqtSignal(object)  # из фонового потока приходит в GUI-поток очередью


class UpdaterFeature(Feature):
    def on_start(self):
        self.offer = None
        self.signals = _Signals()
        self.signals.found.connect(self._on_found)
        self.timer = QTimer()
        self.timer.setInterval(WAIT_WINDOW_MS)
        self.timer.timeout.connect(self._ask_when_ready)
        release_dir = self.ctx.paths.release_dir
        if release_dir is None:
            return  # обычная копия: сверять не с чем
        # Поток-демон: зависший сетевой диск не задержит ни запуск, ни выход
        threading.Thread(target=self._check, args=(release_dir,), name="atlas-updater", daemon=True).start()

    def on_stop(self):
        self.timer.stop()

    def _check(self, release_dir):
        try:
            offer = logic.find_offer(release_dir, current_version())
        except Exception:  # сверка версии не должна мешать работе
            log.exception("Не удалось сверить версию")
            return
        if offer is not None:
            self.signals.found.emit(offer)

    def _on_found(self, offer):
        self.offer = offer
        self.timer.start()

    def _ask_when_ready(self):
        """Ответ может прийти раньше, чем человек вошёл: ждём окно и не лезем поверх другого диалога."""
        if self.ctx.shell is None or not self.ctx.shell.isVisible() or QApplication.activeModalWidget() is not None:
            return
        self.timer.stop()
        if self._confirm():
            self.restart()

    def _confirm(self):
        box = QMessageBox(self.ctx.shell)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("Atlas")
        box.setText("Доступна версия {}, у вас {}.\nПерезапустить программу сейчас?".format(self.offer.version, current_version()))
        restart = box.addButton("Перезапустить", QMessageBox.AcceptRole)
        box.addButton("Позже", QMessageBox.RejectRole)
        box.exec_()
        return box.clickedButton() is restart

    def restart(self):
        try:
            logic.launch(self.offer.exe)
        except OSError as exc:
            log.exception("Не удалось запустить %s", self.offer.exe)
            self.ctx.shell.show_message("Не удалось запустить версию {}: {}".format(self.offer.version, exc))
            return
        log.info("Переход на версию %s", self.offer.version)
        QApplication.closeAllWindows()  # окна сохраняют своё при закрытии
        QApplication.quit()
