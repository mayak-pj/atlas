"""Таблица types. Вызывать не из GUI-потока."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from atlas.core.domain.text import now_text

_COLUMNS = (
    "id, part_id, kind, type_no, description, article, photo_rel, crop_rel, source_photo, source_sn, created_by, created_at, "
    "archived_at, archived_by"
)


@dataclass(frozen=True)
class TypeRecord:
    id: int
    part_id: int
    kind: str
    type_no: Optional[int]
    description: str
    article: Optional[str]
    photo_rel: str
    crop_rel: Optional[str]
    source_photo: Optional[str]
    source_sn: Optional[str]
    created_by: Optional[int]
    created_at: str
    archived_at: Optional[str] = None
    archived_by: Optional[int] = None


class Repo:
    def __init__(self, db):
        self.db = db

    def add(self, part_id, kind, type_no, description, article, photo_rel, crop_rel, source_photo, source_sn, user_id):
        def work(conn):
            cur = conn.execute(
                "INSERT INTO types (part_id, kind, type_no, description, article, photo_rel, crop_rel, source_photo, "
                "source_sn, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (part_id, kind, type_no, description, article or None, photo_rel, crop_rel, source_photo,
                 source_sn or None, user_id, now_text()),
            )
            return cur.lastrowid

        return self.db.write(work)

    def get(self, type_id):
        def work(conn):
            row = conn.execute("SELECT {} FROM types WHERE id = ?".format(_COLUMNS), (type_id,)).fetchone()
            return TypeRecord(*row) if row is not None else None

        return self.db.read(work)

    def numbers(self, part_id):
        """Номера типов детали, которые уже есть."""
        def work(conn):
            rows = conn.execute(
                "SELECT type_no FROM types WHERE part_id = ? AND kind = 'type' AND type_no IS NOT NULL", (part_id,)
            ).fetchall()
            return [row[0] for row in rows]

        return self.db.read(work)

    def set_archived(self, type_id, archived, user_id=None):
        """В архив или обратно. Возвращает (part_id, archived_at или None) или None, если такой записи нет.

        Повторное «в архив» время не меняет: два человека нажали одновременно — остаётся первое.
        """
        def work(conn):
            row = conn.execute("SELECT part_id, archived_at FROM types WHERE id = ?", (type_id,)).fetchone()
            if row is None:
                return None
            if archived:
                stamp = row["archived_at"] or now_text()
                conn.execute("UPDATE types SET archived_at = ?, archived_by = ? WHERE id = ? AND archived_at IS NULL",
                             (stamp, user_id, type_id))
                return row["part_id"], stamp
            conn.execute("UPDATE types SET archived_at = NULL, archived_by = NULL WHERE id = ?", (type_id,))
            return row["part_id"], None

        return self.db.write(work)

    def all(self):
        """Все записи, новые первыми. Базу типов читаем целиком: записей сотни, поиск идёт в памяти."""
        def work(conn):
            rows = conn.execute("SELECT {} FROM types ORDER BY created_at DESC, id DESC".format(_COLUMNS)).fetchall()
            return [TypeRecord(*row) for row in rows]

        return self.db.read(work)

    def for_part(self, part_id, include_archived=False):
        def work(conn):
            sql = "SELECT {} FROM types WHERE part_id = ?".format(_COLUMNS)
            if not include_archived:
                sql += " AND archived_at IS NULL"
            rows = conn.execute(sql + " ORDER BY kind DESC, type_no, id", (part_id,)).fetchall()
            return [TypeRecord(*row) for row in rows]

        return self.db.read(work)
