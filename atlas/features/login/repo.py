"""Таблица login_users."""
from __future__ import annotations

from atlas.core.app_context import User
from atlas.features.login import logic


class UserRepo:
    def __init__(self, db):
        self.db = db

    def all(self):
        """[(User, last_login_at)] — по фамилии."""
        rows = self.db.read(
            lambda conn: conn.execute(
                "SELECT id, name, color, last_login_at FROM login_users ORDER BY name_key"
            ).fetchall()
        )
        return [(User(row[0], row[1], row[2]), row[3]) for row in rows]

    def add(self, name, colors):
        """Добавляет человека; при гонке двух машин (то же имя) возвращает уже созданного."""

        def work(conn):
            key = logic.name_key(name)
            row = conn.execute("SELECT id, name, color FROM login_users WHERE name_key = ?", (key,)).fetchone()
            if row is None:
                count = conn.execute("SELECT COUNT(*) FROM login_users").fetchone()[0]
                color = logic.pick_color(colors, count)
                cur = conn.execute(
                    "INSERT INTO login_users (name, name_key, color, created_at) VALUES (?, ?, ?, ?)",
                    (name, key, color, logic.now_text()),
                )
                return User(cur.lastrowid, name, color)
            return User(row[0], row[1], row[2])

        return self.db.write(work)

    def touch(self, user_id):
        self.db.write(
            lambda conn: conn.execute(
                "UPDATE login_users SET last_login_at = ? WHERE id = ?", (logic.now_text(), user_id)
            )
        )
