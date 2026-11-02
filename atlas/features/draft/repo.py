"""Доступ к таблицам черновика. Вызывать не из GUI-потока."""
from __future__ import annotations

from atlas.core.domain.text import now_text


class Repo:
    def __init__(self, db):
        self.db = db

    def load(self, folder_id, user_id):
        """(заметки, {ключ: пояснение}, [строки вручную])."""
        def work(conn):
            row = conn.execute("SELECT body FROM draft_notes WHERE folder_id = ? AND user_id = ?",
                               (folder_id, user_id)).fetchone()
            comments = dict(conn.execute("SELECT key, body FROM draft_comments WHERE folder_id = ?", (folder_id,)))
            manual = conn.execute("SELECT id, kind, type_no, sn, body FROM draft_items WHERE folder_id = ? ORDER BY id",
                                  (folder_id,)).fetchall()
            return (row[0] if row else ""), comments, [tuple(r) for r in manual]

        return self.db.read(work)

    def save_notes(self, folder_id, user_id, body):
        self.db.write(lambda conn: conn.execute(
            "INSERT OR REPLACE INTO draft_notes (folder_id, user_id, body, updated_at) VALUES (?, ?, ?, ?)",
            (folder_id, user_id, body, now_text())))

    def save_comment(self, folder_id, key, body):
        def work(conn):
            if body:
                conn.execute("INSERT OR REPLACE INTO draft_comments (folder_id, key, body) VALUES (?, ?, ?)",
                             (folder_id, key, body))
            else:
                conn.execute("DELETE FROM draft_comments WHERE folder_id = ? AND key = ?", (folder_id, key))

        self.db.write(work)

    def save_manual_text(self, item_id, body):
        self.db.write(lambda conn: conn.execute("UPDATE draft_items SET body = ? WHERE id = ?", (body, item_id)))

    def add_manual(self, folder_id, kind, type_no, sn, body, user_id):
        return self.db.write(lambda conn: conn.execute(
            "INSERT INTO draft_items (folder_id, kind, type_no, sn, body, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", (folder_id, kind, type_no, sn, body, user_id, now_text())).lastrowid)

    def delete_manual(self, item_id):
        self.db.write(lambda conn: conn.execute("DELETE FROM draft_items WHERE id = ?", (item_id,)))
