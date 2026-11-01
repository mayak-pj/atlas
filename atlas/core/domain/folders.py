"""Сервис «folders»: папки с фото, их статусы, фото и отметки."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from atlas.core.domain.text import normalize_name, now_text

STATUSES = ("new", "in_work", "done")
MARK_DEFECT = "defect"
MARK_REMARK = "remark"
_MARK_TYPE = re.compile(r"^type:\d+$")
_SQL_VARIABLES_LIMIT = 900  # в сборках SQLite под Windows предел 999

_FOLDER_COLUMNS = (
    "id, part_id, path, folder_date, status, created_by, created_at, status_by, status_at"
)
_PHOTO_COLUMNS = "id, folder_id, rel_path, sn, mark, marked_by, marked_at, defect_kind, rotation"
ROTATIONS = (0, 90, 180, 270)


@dataclass(frozen=True)
class Folder:
    id: int
    part_id: int
    path: str
    folder_date: str
    status: str
    created_by: Optional[int]
    created_at: str
    status_by: Optional[int]
    status_at: Optional[str]


@dataclass(frozen=True)
class Photo:
    id: int
    folder_id: int
    rel_path: str
    sn: Optional[str]
    mark: Optional[str]
    marked_by: Optional[int]
    marked_at: Optional[str]
    defect_kind: Optional[str] = None
    rotation: int = 0  # градусы по часовой стрелке; файл на диске не меняется


def path_key(path):
    """Один и тот же сетевой путь: регистр, вид косой черты и хвостовая черта не важны."""
    text = str(path).strip().replace("/", "\\").rstrip("\\")
    if not text:
        raise ValueError("Пустой путь папки")
    return text.casefold()


def clean_rel_path(rel_path):
    """Путь внутри папки через «/». Выйти за пределы папки нельзя."""
    parts = str(rel_path).strip().replace("\\", "/").split("/")
    bad = str(rel_path).strip()[:1] in ("/", "\\") or ":" in parts[0]
    if bad or ".." in parts or not all(parts):
        raise ValueError("Недопустимый путь внутри папки: {}".format(rel_path))
    return "/".join(parts)


def valid_mark(mark):
    return mark is None or mark in (MARK_DEFECT, MARK_REMARK) or bool(_MARK_TYPE.match(str(mark)))


class FoldersService:
    def __init__(self, db):
        self.db = db

    # --- папки ----------------------------------------------------------------
    def add(self, part_id, path, folder_date, created_by=None):
        """Регистрирует папку. Этот путь уже есть (в том числе с другого ПК) — вернёт существующую."""
        datetime.strptime(folder_date, "%Y-%m-%d")  # ValueError, если дата не ГГГГ-ММ-ДД
        text = str(path).strip()
        key = path_key(text)

        def work(conn):
            conn.execute(
                "INSERT OR IGNORE INTO folders (part_id, path, path_key, folder_date, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (part_id, text, key, folder_date, created_by, now_text()),
            )
            return Folder(
                *conn.execute("SELECT {} FROM folders WHERE path_key = ?".format(_FOLDER_COLUMNS), (key,)).fetchone()
            )

        return self.db.write(work)

    def get(self, folder_id):
        """Folder или None."""
        row = self.db.read(
            lambda conn: conn.execute(
                "SELECT {} FROM folders WHERE id = ?".format(_FOLDER_COLUMNS), (folder_id,)
            ).fetchone()
        )
        return Folder(*row) if row is not None else None

    def recent(self, limit=50, status=None):
        """Сначала самые свежие; status — только папки с этим статусом."""
        where = "WHERE status = ? " if status is not None else ""
        args = ((status,) if status is not None else ()) + (int(limit),)
        sql = "SELECT {} FROM folders {}ORDER BY folder_date DESC, id DESC LIMIT ?".format(_FOLDER_COLUMNS, where)
        return [Folder(*row) for row in self.db.read(lambda conn: conn.execute(sql, args).fetchall())]

    def latest_for_part(self, name, project_id=None, kind=None, exclude_project_id=None, exclude_folder_id=None,
                        since=None):
        """Последняя по дате папка детали с таким названием (регистр и разделители не важны) или None.

        project_id — только этот проект; kind и exclude_project_id — проекты этого вида, кроме одного;
        since — «ГГГГ-ММ-ДД», не старше. Пустые папки (без фото) пропускаются: показывать в них нечего.
        """
        conditions = ["p.name_key = ?", "EXISTS (SELECT 1 FROM photos WHERE folder_id = f.id)"]
        args = [normalize_name(name)]
        for sql, value in (
            ("r.id = ?", project_id), ("r.kind = ?", kind), ("r.id <> ?", exclude_project_id),
            ("f.id <> ?", exclude_folder_id), ("f.folder_date >= ?", since),
        ):
            if value is not None:
                conditions.append(sql)
                args.append(value)
        sql = (
            "SELECT {} FROM folders f JOIN parts p ON p.id = f.part_id JOIN devices d ON d.id = p.device_id "
            "JOIN projects r ON r.id = d.project_id WHERE {} ORDER BY f.folder_date DESC, f.id DESC LIMIT 1"
        ).format(", ".join("f." + column.strip() for column in _FOLDER_COLUMNS.split(",")), " AND ".join(conditions))
        row = self.db.read(lambda conn: conn.execute(sql, args).fetchone())
        return Folder(*row) if row is not None else None

    def set_status(self, folder_id, status, user_id=None):
        if status not in STATUSES:
            raise ValueError("Неизвестный статус папки: {}".format(status))

        def work(conn):
            cur = conn.execute(
                "UPDATE folders SET status = ?, status_by = ?, status_at = ? WHERE id = ?",
                (status, user_id, now_text(), folder_id),
            )
            if cur.rowcount == 0:
                raise LookupError("Нет папки {}".format(folder_id))

        self.db.write(work)

    # --- фото -----------------------------------------------------------------
    def add_photos(self, folder_id, rel_paths):
        """Добавляет фото одной транзакцией, уже известные пропускает. Возвращает, сколько добавлено."""
        rows = []
        for rel_path in rel_paths:
            clean = clean_rel_path(rel_path)
            rows.append((folder_id, clean, clean.casefold()))

        def work(conn):
            before = conn.total_changes
            conn.executemany("INSERT OR IGNORE INTO photos (folder_id, rel_path, rel_key) VALUES (?, ?, ?)", rows)
            return conn.total_changes - before

        return self.db.write(work)

    def photos(self, folder_id):
        rows = self.db.read(
            lambda conn: conn.execute(
                "SELECT {} FROM photos WHERE folder_id = ? ORDER BY rel_key".format(_PHOTO_COLUMNS), (folder_id,)
            ).fetchall()
        )
        return [Photo(*row) for row in rows]

    def mark_photo(self, photo_id, mark, sn=None, user_id=None, defect_kind=None):
        """mark: "type:N", "defect", "remark" или None (снять отметку).

        sn: None — оставить как есть, пустая строка — стереть.
        defect_kind: только для дефекта; None или пустая строка — вид не выбран. Любая другая отметка вид стирает.
        """
        if not valid_mark(mark):
            raise ValueError("Неизвестная отметка: {}".format(mark))
        new_sn = sn.strip() if sn is not None else None
        clear_sn = new_sn == ""
        kind = (defect_kind or "").strip() or None if mark == MARK_DEFECT else None

        def work(conn):
            cur = conn.execute(
                "UPDATE photos SET mark = ?, marked_by = ?, marked_at = ?, defect_kind = ?, "
                "sn = CASE WHEN ? THEN NULL ELSE COALESCE(?, sn) END WHERE id = ?",
                (mark, user_id if mark else None, now_text() if mark else None, kind,
                 clear_sn, new_sn or None, photo_id),
            )
            if cur.rowcount == 0:
                raise LookupError("Нет фото {}".format(photo_id))

        self.db.write(work)

    def set_rotation(self, photo_id, rotation):
        """Запомнить поворот фото: 0, 90, 180 или 270 градусов по часовой стрелке. Отметку и статус папки не трогает."""
        if rotation not in ROTATIONS:
            raise ValueError("Недопустимый поворот: {}".format(rotation))

        def work(conn):
            cur = conn.execute("UPDATE photos SET rotation = ? WHERE id = ?", (rotation, photo_id))
            if cur.rowcount == 0:
                raise LookupError("Нет фото {}".format(photo_id))

        self.db.write(work)

    def move_photos(self, moves):
        """moves: [(photo_id, новый_rel_path)]. Одна транзакция: или все пути сменились, или ни один.

        Файлы переносит вызывающий; сюда — только запись нового места. Занятое имя в той же папке — sqlite3.IntegrityError.
        """
        rows = []
        for photo_id, rel_path in moves:
            clean = clean_rel_path(rel_path)
            rows.append((clean, clean.casefold(), photo_id))

        def work(conn):
            for row in rows:
                cur = conn.execute("UPDATE photos SET rel_path = ?, rel_key = ? WHERE id = ?", row)
                if cur.rowcount == 0:
                    raise LookupError("Нет фото {}".format(row[2]))

        self.db.write(work)

    def counts(self, folder_ids):
        """{folder_id: {"total": всего, "unmarked": без отметки, отметка: сколько}} одним чтением."""
        ids = list(folder_ids)
        result = {folder_id: {"total": 0, "unmarked": 0} for folder_id in ids}

        def work(conn):
            for start in range(0, len(ids), _SQL_VARIABLES_LIMIT):
                chunk = ids[start:start + _SQL_VARIABLES_LIMIT]
                sql = "SELECT folder_id, mark, COUNT(*) FROM photos WHERE folder_id IN ({}) GROUP BY folder_id, mark"
                for folder_id, mark, count in conn.execute(sql.format(",".join("?" * len(chunk))), chunk):
                    item = result[folder_id]
                    item["total"] += count
                    item[mark or "unmarked"] = count

        self.db.read(work)
        return result
