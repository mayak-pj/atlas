"""Доступ к таблицам правил. Вызывать не из GUI-потока."""
from __future__ import annotations

from atlas.core.domain.text import now_text
from atlas.features.rules.logic import Rule

_COLUMNS = ("id, scope, kind, project_id, device_id, part_id, name_key, scope_label, title, body, author_id, created_at")


class Repo:
    def __init__(self, db):
        self.db = db

    def add(self, draft, author_id, photo_rels=()):
        """Правило и его фото одной транзакцией; автор своё правило уже «прочитал»."""
        def work(conn):
            now = now_text()
            cur = conn.execute(
                "INSERT INTO rules (scope, kind, project_id, device_id, part_id, name_key, scope_label, title, body, "
                "author_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (draft.scope, draft.kind, draft.project_id, draft.device_id, draft.part_id, draft.name_key,
                 draft.scope_label, draft.title, draft.body, author_id, now),
            )
            rule_id = cur.lastrowid
            for rel in photo_rels:
                conn.execute("INSERT INTO rule_photos (rule_id, rel) VALUES (?, ?)", (rule_id, rel))
            if author_id is not None:
                conn.execute("INSERT OR IGNORE INTO rule_reads (rule_id, user_id, read_at) VALUES (?, ?, ?)",
                             (rule_id, author_id, now))
            return rule_id

        return self.db.write(work)

    def all(self, user_id):
        """Все правила, свежие первыми; read — прочитал ли их этот пользователь."""
        def work(conn):
            reads = {row[0] for row in conn.execute("SELECT rule_id FROM rule_reads WHERE user_id = ?", (user_id,))}
            photos = {}
            for rule_id, rel in conn.execute("SELECT rule_id, rel FROM rule_photos ORDER BY id"):
                photos.setdefault(rule_id, []).append(rel)
            rows = conn.execute("SELECT {} FROM rules ORDER BY created_at DESC, id DESC".format(_COLUMNS)).fetchall()
            return [Rule(*row, read=row[0] in reads, photos=tuple(photos.get(row[0], ()))) for row in rows]

        return self.db.read(work)

    def unread_count(self, user_id):
        return self.db.read(lambda conn: conn.execute(
            "SELECT COUNT(*) FROM rules r WHERE NOT EXISTS "
            "(SELECT 1 FROM rule_reads x WHERE x.rule_id = r.id AND x.user_id = ?)", (user_id,)).fetchone()[0])

    def mark_read(self, rule_ids, user_id):
        def work(conn):
            now = now_text()
            for rule_id in rule_ids:
                conn.execute("INSERT OR IGNORE INTO rule_reads (rule_id, user_id, read_at) VALUES (?, ?, ?)",
                             (rule_id, user_id, now))

        self.db.write(work)

    def mark_all_read(self, user_id):
        self.db.write(lambda conn: conn.execute(
            "INSERT OR IGNORE INTO rule_reads (rule_id, user_id, read_at) SELECT id, ?, ? FROM rules",
            (user_id, now_text())))
