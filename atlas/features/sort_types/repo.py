"""Журнал раскладок. Вызывать не из GUI-потока."""
from __future__ import annotations

from atlas.core.domain.text import now_text


class Repo:
    def __init__(self, db):
        self.db = db

    def add_batch(self, folder_id, user_id, moves):
        """moves: [(photo_id, from_rel, to_rel)]. Возвращает номер раскладки."""
        def work(conn):
            cur = conn.execute(
                "INSERT INTO sort_batches (folder_id, user_id, created_at) VALUES (?, ?, ?)",
                (folder_id, user_id, now_text()),
            )
            conn.executemany(
                "INSERT INTO sort_moves (batch_id, photo_id, from_rel, to_rel) VALUES (?, ?, ?, ?)",
                [(cur.lastrowid,) + tuple(move) for move in moves],
            )
            return cur.lastrowid

        return self.db.write(work)

    def last_batch(self, folder_id):
        """(номер, [(photo_id, from_rel, to_rel)]) последней не отменённой раскладки папки или None."""
        def work(conn):
            row = conn.execute(
                "SELECT id FROM sort_batches WHERE folder_id = ? AND undone_at IS NULL ORDER BY id DESC LIMIT 1",
                (folder_id,),
            ).fetchone()
            if row is None:
                return None
            moves = conn.execute(
                "SELECT photo_id, from_rel, to_rel FROM sort_moves WHERE batch_id = ?", (row[0],)
            ).fetchall()
            return row[0], [tuple(move) for move in moves]

        return self.db.read(work)

    def finish_undo(self, batch_id, restored_photo_ids):
        """Возвращённые фото убираем из раскладки; не осталось ничего — раскладка отменена целиком."""
        ids = list(restored_photo_ids)

        def work(conn):
            conn.executemany("DELETE FROM sort_moves WHERE batch_id = ? AND photo_id = ?", [(batch_id, i) for i in ids])
            left = conn.execute("SELECT COUNT(*) FROM sort_moves WHERE batch_id = ?", (batch_id,)).fetchone()[0]
            if left == 0:
                conn.execute("UPDATE sort_batches SET undone_at = ? WHERE id = ?", (now_text(), batch_id))

        self.db.write(work)
