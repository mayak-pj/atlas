"""Доступ к таблицам правил. Вызывать не из GUI-потока."""
from __future__ import annotations

from atlas.core.domain.text import now_text
from atlas.features.rules.logic import Rule

_COLUMNS = ("id, scope, kind, project_id, device_id, part_id, name_key, scope_label, title, body, author_id, created_at, "
            "archived_at, updated_at")


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
            "SELECT COUNT(*) FROM rules r WHERE r.archived_at IS NULL AND NOT EXISTS "
            "(SELECT 1 FROM rule_reads x WHERE x.rule_id = r.id AND x.user_id = ?)", (user_id,)).fetchone()[0])

    def set_archived(self, rule_id, archived, user_id=None):
        """В архив или обратно → время архивации (или None) или LookupError, если правила нет."""
        def work(conn):
            row = conn.execute("SELECT archived_at FROM rules WHERE id = ?", (rule_id,)).fetchone()
            if row is None:
                raise LookupError("Нет правила {}".format(rule_id))
            if not archived:
                conn.execute("UPDATE rules SET archived_at = NULL, archived_by = NULL WHERE id = ?", (rule_id,))
                return None
            stamp = row[0] or now_text()
            conn.execute("UPDATE rules SET archived_at = ?, archived_by = ? WHERE id = ?", (stamp, user_id, rule_id))
            return stamp

        return self.db.write(work)

    def delete(self, rule_id):
        """Правило, его фото и «прочитано» одной транзакцией → пути фото (файлы убирает вызывающий)."""
        def work(conn):
            rels = [row[0] for row in conn.execute("SELECT rel FROM rule_photos WHERE rule_id = ?", (rule_id,))]
            conn.execute("DELETE FROM rule_photos WHERE rule_id = ?", (rule_id,))
            conn.execute("DELETE FROM rule_reads WHERE rule_id = ?", (rule_id,))
            conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
            return rels

        return self.db.write(work)

    def update(self, rule_id, title, body, keep_rels, new_rels, user_id=None):
        """Новые заголовок и текст; фото — оставленные плюс новые. → пути убранных фото (файлы убирает вызывающий).

        Область не меняется: она привязана к детали, открытой при создании.
        """
        def work(conn):
            if conn.execute("SELECT 1 FROM rules WHERE id = ?", (rule_id,)).fetchone() is None:
                raise LookupError("Нет правила {}".format(rule_id))
            old = [row[0] for row in conn.execute("SELECT rel FROM rule_photos WHERE rule_id = ? ORDER BY id", (rule_id,))]
            removed = [rel for rel in old if rel not in keep_rels]
            for rel in removed:
                conn.execute("DELETE FROM rule_photos WHERE rule_id = ? AND rel = ?", (rule_id, rel))
            for rel in new_rels:
                conn.execute("INSERT INTO rule_photos (rule_id, rel) VALUES (?, ?)", (rule_id, rel))
            conn.execute("UPDATE rules SET title = ?, body = ?, updated_at = ?, updated_by = ? WHERE id = ?",
                         (title, body, now_text(), user_id, rule_id))
            return removed

        return self.db.write(work)

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
