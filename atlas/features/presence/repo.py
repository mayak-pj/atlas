"""Таблица presence."""
from __future__ import annotations

from atlas.core.domain.text import now_text
from atlas.features.presence.logic import PresenceRow


class PresenceRepo:
    def __init__(self, db):
        self.db = db

    def beat(self, user_id, folder_id):
        """Сигнал «я здесь». Без UPSERT: версия SQLite на целевой машине не проверена."""

        def work(conn):
            now = now_text()
            cur = conn.execute(
                "UPDATE presence SET folder_id = ?, beat = beat + 1, seen_at = ? WHERE user_id = ?",
                (folder_id, now, user_id),
            )
            if cur.rowcount == 0:
                conn.execute(
                    "INSERT INTO presence (user_id, folder_id, beat, seen_at) VALUES (?, ?, 1, ?)",
                    (user_id, folder_id, now),
                )

        self.db.write(work)

    def rows(self):
        found = self.db.read(lambda conn: conn.execute("SELECT user_id, folder_id, beat, seen_at FROM presence").fetchall())
        return [PresenceRow(*row) for row in found]

    def leave(self, user_id):
        self.db.write(lambda conn: conn.execute("DELETE FROM presence WHERE user_id = ?", (user_id,)))
