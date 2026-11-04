"""Пользователи для диалога входа: тонкая обёртка над сервисом ядра users."""
from __future__ import annotations

from atlas.features.login import logic


class UserRepo:
    def __init__(self, users):
        self.users = users

    def all(self):
        """[(User, last_login_at)] — по фамилии, без убранных из списка."""
        return self.users.active() if hasattr(self.users, "active") else self.users.all()

    def hide(self, user_id):
        self.users.hide(user_id)

    def add(self, name, colors):
        """Добавляет человека; при гонке двух машин (то же имя) возвращает уже созданного."""
        return self.users.add(name, lambda count: logic.pick_color(colors, count))

    def touch(self, user_id):
        self.users.touch(user_id)
