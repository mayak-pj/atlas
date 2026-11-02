"""Доступ к таблицам комментариев. Вызывать не из GUI-потока."""
from __future__ import annotations

from atlas.core.domain.text import now_text
from atlas.features.comments import logic
from atlas.features.comments.logic import Comment

_COLUMNS = "id, author_id, to_user_id, body, part_id, folder_id, part_label, earlier_error, created_at, expires_at"


class Repo:
    def __init__(self, db):
        self.db = db

    def add(self, draft, author_id, photo_rels=()):
        """Сообщение и его фото одной транзакцией."""
        def work(conn):
            now = now_text()
            cur = conn.execute(
                "INSERT INTO comments (author_id, to_user_id, body, part_id, folder_id, part_label, earlier_error, "
                "created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (author_id, draft.to_user_id, draft.body, draft.part_id, draft.folder_id, draft.part_label,
                 1 if draft.earlier_error else 0, now, logic.expires_at(draft.days)),
            )
            for rel in photo_rels:
                conn.execute("INSERT INTO comment_photos (comment_id, rel) VALUES (?, ?)", (cur.lastrowid, rel))
            return cur.lastrowid

        return self.db.write(work)

    def all(self, user_id):
        """Живые сообщения, видимые этому пользователю, свежие первыми."""
        def work(conn):
            now = now_text()
            done = {row[0] for row in conn.execute("SELECT comment_id FROM comment_done WHERE user_id = ?", (user_id,))}
            rows = conn.execute(
                "SELECT {} FROM comments WHERE (expires_at IS NULL OR expires_at > ?) "
                "AND (to_user_id IS NULL OR to_user_id = ? OR author_id = ?) ORDER BY created_at DESC, id DESC".format(
                    _COLUMNS), (now, user_id, user_id)).fetchall()
            photos = {}
            for comment_id, rel in conn.execute("SELECT comment_id, rel FROM comment_photos ORDER BY id"):
                photos.setdefault(comment_id, []).append(rel)
            return [Comment(*row[:7], bool(row[7]), row[8], row[9], done=row[0] in done,
                            photos=tuple(photos.get(row[0], ()))) for row in rows]

        return self.db.read(work)

    def mark_done(self, comment_id, user_id):
        self.db.write(lambda conn: conn.execute(
            "INSERT OR IGNORE INTO comment_done (comment_id, user_id, done_at) VALUES (?, ?, ?)",
            (comment_id, user_id, now_text())))

    def purge_expired(self):
        """Удаляет истёкшие сообщения; возвращает пути их фото, чтобы стереть файлы."""
        def work(conn):
            ids = [row[0] for row in conn.execute(
                "SELECT id FROM comments WHERE expires_at IS NOT NULL AND expires_at <= ?", (now_text(),))]
            rels = []
            for comment_id in ids:
                rels += [row[0] for row in conn.execute(
                    "SELECT rel FROM comment_photos WHERE comment_id = ?", (comment_id,))]
                for table in ("comment_photos", "comment_done"):
                    conn.execute("DELETE FROM {} WHERE comment_id = ?".format(table), (comment_id,))
                conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
            return rels

        return self.db.write(work)
