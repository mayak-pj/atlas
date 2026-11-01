from __future__ import annotations

import json
import logging

from atlas.core.feature import Feature
from atlas.features.login import logic
from atlas.features.login.repo import UserRepo
from atlas.shared.widgets import NameTag

log = logging.getLogger("atlas.login")

EVENT_LOGGED_IN = "user.logged_in"
SLOT_USER = "shell.user"


class LoginFeature(Feature):
    """Сервис «login»: run(parent) — показать диалог; current(); users()."""

    def on_start(self):
        self.repo = UserRepo(self.ctx.services.get("users"))
        self.ctx.services.register("login", self)

    def on_stop(self):
        self.ctx.services.unregister("login")

    def _colors(self):
        path = self.ctx.paths.data / "user_colors.json"
        try:
            return list(json.loads(path.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError):
            log.warning("Нет списка цветов %s, взят стандартный", path)
            return list(logic.DEFAULT_COLORS)

    # --- сервис ---------------------------------------------------------------
    def current(self):
        return self.ctx.user

    def users(self):
        return [user for user, _ in self.repo.all()]

    def run(self, parent=None):
        """Показывает диалог. Возвращает User или None, если окно закрыли."""
        from PyQt5.QtWidgets import QDialog

        from atlas.features.login.dialog import LoginDialog

        dialog = LoginDialog(self.repo, self._colors(), getattr(self.ctx, "shell", None), parent)
        dialog.attach_slots()
        try:
            accepted = dialog.exec_() == QDialog.Accepted
            user = dialog.selected if accepted else None
        finally:
            dialog.detach_slots()
        if user is None:
            return None
        self.sign_in(user)
        return user

    def sign_in(self, user):
        """Запоминает вход, показывает тег в верхней полосе, сообщает остальным."""
        self.repo.touch(user.id)
        self.ctx.user = user
        shell = getattr(self.ctx, "shell", None)
        if shell is not None:
            shell.add_panel(SLOT_USER, NameTag(user.name, user.color, compact=True), key="login")
        self.ctx.bus.publish(EVENT_LOGGED_IN, {"user": user})
