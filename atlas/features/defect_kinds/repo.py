"""Таблица defect_kinds. Методы ходят в базу: не из GUI-потока."""
from __future__ import annotations

import sqlite3

from atlas.core.domain.text import now_text
from atlas.features.defect_kinds.logic import KindError, clean, key


class KindsRepo:
    def __init__(self, db, seed=()):
        self.db = db
        self._seed = list(seed)

    def names(self):
        """Живые виды по порядку. Таблица совсем пустая (первый запуск) — заполняется начальным списком."""
        empty = self.db.read(lambda conn: conn.execute("SELECT COUNT(*) FROM defect_kinds").fetchone()[0] == 0)
        if not empty:  # обычный случай — только чтение, без блокировки базы на запись
            return self.db.read(lambda conn: [row[0] for row in conn.execute(
                "SELECT name FROM defect_kinds WHERE removed_at IS NULL ORDER BY position, id")])

        def work(conn):  # два ПК при первом запуске: внутри транзакции проверяем ещё раз
            if conn.execute("SELECT COUNT(*) FROM defect_kinds").fetchone()[0] == 0 and self._seed:
                now = now_text()
                conn.executemany(
                    "INSERT INTO defect_kinds (name, name_key, position, created_at) VALUES (?, ?, ?, ?)",
                    [(name, key(name), number, now) for number, name in enumerate(self._seed)])
            return [row[0] for row in conn.execute(
                "SELECT name FROM defect_kinds WHERE removed_at IS NULL ORDER BY position, id")]
        return self.db.write(work)

    def add(self, name, user_id=None):
        text = clean(name)

        def work(conn):
            position = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM defect_kinds").fetchone()[0]
            conn.execute(
                "INSERT INTO defect_kinds (name, name_key, position, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                (text, key(text), position, user_id, now_text()))
        try:
            self.db.write(work)
        except sqlite3.IntegrityError:
            raise KindError("Такой вид уже есть: {}".format(text))
        return text

    def rename(self, old, new):
        """→ новое имя. Только список; отметки фото правит владелец таблицы фото (сервис folders)."""
        text = clean(new)

        def work(conn):
            cur = conn.execute(
                "UPDATE defect_kinds SET name = ?, name_key = ? WHERE name_key = ? AND removed_at IS NULL",
                (text, key(text), key(old)))
            if cur.rowcount == 0:
                raise KindError("Вида «{}» уже нет: обновите список".format(old))
        try:
            self.db.write(work)
        except sqlite3.IntegrityError:
            raise KindError("Такой вид уже есть: {}".format(text))
        return text

    def remove(self, name):
        def work(conn):
            conn.execute("UPDATE defect_kinds SET removed_at = ? WHERE name_key = ? AND removed_at IS NULL",
                         (now_text(), key(name)))
        self.db.write(work)
