"""Тестовые данные по макету: python -m samples.seed --out var/samples [--photos 12 | --full].

Создаёт ОТДЕЛЬНУЮ базу и фото в папке --out, рабочую базу не трогает. Повторный запуск ничего не дублирует.
Чтобы открыть программу на этих данных: config/local.json, {"database": {"path": "<out>/atlas.sqlite"}}.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from atlas.core import domain
from atlas.core.db import Database
from atlas.core.domain.folders import FoldersService
from atlas.core.domain.parts import PartsService
from atlas.core.domain.text import TIME_FORMAT
from atlas.core.domain.users import UsersService
from samples import photos as photo_files

DATA = Path(__file__).with_name("seed_data.json")
DEFAULT_PHOTOS = 12
COLORS = ["#7DB4FF", "#3DD68C", "#F2A93B", "#C59CFF", "#FF8A8A", "#5FD3D3"]


def _kind(parts, code):
    """В данных виды проектов условные («A», «B»): берём настроенные на этой машине виды по порядку."""
    kinds = parts.kinds
    return kinds[min(ord(code) - ord("A"), len(kinds) - 1)] if len(code) == 1 else code


def _pick_marks(marks, count):
    """Отметки подряд с начала папки, сколько поместится: [("type:2", индекс фото), ...]."""
    result, index = [], 0
    for mark, amount in (marks or {}).items():
        for _ in range(amount):
            if index < count:
                result.append((mark, index))
            index += 1
    return result


def _set_dates(db, folder_id, moment, status_changed):
    """Сервис ставит текущее время, а для макета нужно прошлое («проверено на этой неделе»)."""
    text = moment.strftime(TIME_FORMAT)
    db.write(lambda conn: conn.execute("UPDATE folders SET created_at = ? WHERE id = ?", (text, folder_id)))
    if status_changed:
        db.write(lambda conn: conn.execute("UPDATE folders SET status_at = ? WHERE id = ?", (text, folder_id)))


def seed(out, limit=DEFAULT_PHOTOS, full=False, width=photo_files.WIDTH, height=photo_files.HEIGHT, today=None, log=print):
    """Возвращает Database. limit — фото на папку; full — столько, сколько в макете."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    data = json.loads(DATA.read_text(encoding="utf-8"))
    today = today or date.today()
    db = Database(out / "atlas.sqlite")
    domain.migrate(db)
    users_service, parts, folders = UsersService(db), PartsService(db), FoldersService(db)
    people = {name: users_service.add(name, lambda count: COLORS[count % len(COLORS)]) for name in data["users"]}
    app = photo_files.ensure_gui()  # держим до конца: без него QPainter не рисует текст
    for item in data["folders"]:
        part = parts.ensure(_kind(parts, item["kind"]), item["project"], item["device"], item["part"], item["article"])
        day = today - timedelta(days=item["days_ago"])
        user = people[item["by"]]
        path = out / "photos" / _kind(parts, item["kind"]) / item["project"] / item["device"] / item["part"] / day.isoformat()
        folder = folders.add(part.id, str(path), day.isoformat(), user.id)
        count = item["photos"] if full else min(limit, item["photos"])
        marks = _pick_marks(item.get("marks"), count)
        by_index = dict((index, mark) for mark, index in marks)
        names = []
        for index in range(count):
            name = "{:04d}.jpg".format(index + 1)
            type_number = 2 if by_index.get(index) == "type:2" else 1
            label = "{} · SN{:06d}".format(item["part"], index + 1)
            seed_value = "{}/{}".format(path, name)
            if not photo_files.save_photo(path / name, item["variant"], type_number, label, seed_value, width, height):
                raise OSError("Не удалось записать {}".format(path / name))
            names.append(name)
        folders.add_photos(folder.id, names)
        stored = folders.photos(folder.id)
        for mark, index in marks:
            sn = "SN{:06d}".format(index + 1) if mark == "defect" else None
            folders.mark_photo(stored[index].id, mark, sn, user.id)
        changed = item["status"] != "new"
        if changed:
            folders.set_status(folder.id, item["status"], user.id)
        moment = datetime(day.year, day.month, day.day, 9, 12)
        _set_dates(db, folder.id, moment, changed)
        log("{}: {} фото".format(path, count))
    del app
    return db


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if "--out" not in args or args.index("--out") + 1 >= len(args):
        print(__doc__)
        return 2
    limit = DEFAULT_PHOTOS
    if "--photos" in args:
        limit = int(args[args.index("--photos") + 1])
    db = seed(args[args.index("--out") + 1], limit, "--full" in args)
    print("База: {}".format(db.path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
