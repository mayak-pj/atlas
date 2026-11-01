"""Сервис «parts»: справочник проект (A/B) → устройство → деталь."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from atlas.core.domain.text import clean_name, normalize_name, required_key

DEFAULT_KINDS = ("A", "B")  # условные названия; настоящие — project_kinds в config/local.json (не в git)

_SELECT = (
    "SELECT p.id, p.name, p.name_key, p.article, d.id AS device_id, d.name AS device, "
    "r.id AS project_id, r.name AS project, r.kind "
    "FROM parts p JOIN devices d ON d.id = p.device_id JOIN projects r ON r.id = d.project_id "
)
_ORDER = " ORDER BY r.kind, r.name_key, d.name_key, p.name_key"


@dataclass(frozen=True)
class Part:
    id: int
    name: str
    name_key: str
    article: Optional[str]
    device_id: int
    device: str
    project_id: int
    project: str
    kind: str


def _part(row):
    return Part(*row)


def _ensure(conn, table, owner_column, owner_value, name, key):
    row = conn.execute(
        "SELECT id FROM {} WHERE {} = ? AND name_key = ?".format(table, owner_column), (owner_value, key)
    ).fetchone()
    if row is not None:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO {} ({}, name, name_key) VALUES (?, ?, ?)".format(table, owner_column), (owner_value, name, key)
    )
    return cur.lastrowid


class PartsService:
    def __init__(self, db, kinds=None):
        self.db = db
        self.kinds = tuple(str(kind) for kind in kinds) if kinds else DEFAULT_KINDS

    def ensure(self, kind, project, device, part, article=None):
        """Деталь с её проектом и устройством: чего нет — создаёт. Всё одной транзакцией.

        У существующей детали имя не меняется, артикул дописывается, только если его ещё не было.
        """
        if kind not in self.kinds:
            raise ValueError("Неизвестный вид проекта: {}".format(kind))
        keys = [required_key(project, "проект"), required_key(device, "устройство"), required_key(part, "деталь")]
        article = clean_name(article) if article else None

        def work(conn):
            project_id = _ensure(conn, "projects", "kind", kind, clean_name(project), keys[0])
            device_id = _ensure(conn, "devices", "project_id", project_id, clean_name(device), keys[1])
            part_id = _ensure(conn, "parts", "device_id", device_id, clean_name(part), keys[2])
            if article:
                conn.execute("UPDATE parts SET article = ? WHERE id = ? AND article IS NULL", (article, part_id))
            return _part(conn.execute(_SELECT + "WHERE p.id = ?", (part_id,)).fetchone())

        return self.db.write(work)

    def get(self, part_id):
        """Part или None."""
        row = self.db.read(lambda conn: conn.execute(_SELECT + "WHERE p.id = ?", (part_id,)).fetchone())
        return _part(row) if row is not None else None

    def find(self, name):
        """Детали с таким же нормализованным именем во всех устройствах."""
        key = normalize_name(name)
        rows = self.db.read(lambda conn: conn.execute(_SELECT + "WHERE p.name_key = ?" + _ORDER, (key,)).fetchall())
        return [_part(row) for row in rows]

    def all(self):
        rows = self.db.read(lambda conn: conn.execute(_SELECT + _ORDER).fetchall())
        return [_part(row) for row in rows]
