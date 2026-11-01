"""Таблица types. Вызывать не из GUI-потока."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from atlas.core.domain.text import now_text

_COLUMNS = (
    "id, part_id, kind, type_no, description, article, photo_rel, crop_rel, source_photo, source_sn, created_by, created_at"
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
