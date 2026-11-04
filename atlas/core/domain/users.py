"""Сервис «users»: таблица users."""
from __future__ import annotations

from atlas.core.app_context import User
from atlas.core.domain.text import clean_name, name_key, now_text


class UsersService:
    def __init__(self, db):
        self.db = db

    def active(self):
        """[(User, last_login_at)] — кого показывать в списке входа и выбора: без убранных."""
        rows = self.db.read(lambda conn: conn.execute(
            "SELECT id, name, color, last_login_at FROM users WHERE hidden_at IS NULL ORDER BY name_key").fetchall())
        return [(User(row["id"], row["name"], row["color"]), row["last_login_at"]) for row in rows]

    def hide(self, user_id):
        """Убрать из списка. Отметки, правила и типы человека остаются с его фамилией."""
        self.db.write(lambda conn: conn.execute(
            "UPDATE users SET hidden_at = ? WHERE id = ? AND hidden_at IS NULL", (now_text(), user_id)))

    def all(self):
        """[(User, last_login_at)] — по фамилии, все, в том числе убранные из списка: для подписей «кто сделал»."""
        rows = self.db.read(
            lambda conn: conn.execute("SELECT id, name, color, last_login_at FROM users ORDER BY name_key").fetchall()
        )
        return [(User(row["id"], row["name"], row["color"]), row["last_login_at"]) for row in rows]

    def add(self, name, color_for):
        """Добавляет человека; то же имя (и гонка двух машин) — вернёт уже созданного.

        color_for(сколько_уже_людей) — выбор цвета, вызывается внутри транзакции.
        """
        name = clean_name(name)
        if not name:
            raise ValueError("Пустое имя пользователя")
        key = name_key(name)

        def work(conn):
            row = conn.execute("SELECT id, name, color FROM users WHERE name_key = ?", (key,)).fetchone()
            if row is not None:
                conn.execute("UPDATE users SET hidden_at = NULL WHERE id = ?", (row["id"],))  # убранного — вернуть
                return User(row["id"], row["name"], row["color"])
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            color = color_for(count)
            cur = conn.execute(
                "INSERT INTO users (name, name_key, color, created_at) VALUES (?, ?, ?, ?)",
                (name, key, color, now_text()),
            )
            return User(cur.lastrowid, name, color)

        return self.db.write(work)

    def touch(self, user_id):
        """Запоминает время входа."""
        self.db.write(
            lambda conn: conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_text(), user_id))
        )
