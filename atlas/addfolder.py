"""--addfolder: внести в базу настоящую папку с фото, пока нет импорта из письма (шаг 6).

    atlas.exe --addfolder "R:\\папка с фото" --kind A --project "Проект" --device "Устройство" --part "Деталь" [--date 2026-10-31] [--article 0402290000836]

Без окна и без Qt. Фото — все .jpg/.jpeg внутри папки, подпапки тоже. Повторный запуск ничего не дублирует.
Итог — одна строка в reports/addfolder.txt (оконный exe консоли не имеет).
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

from atlas.core import domain
from atlas.core.config import Config
from atlas.core.db import Database

log = logging.getLogger("atlas.addfolder")

PHOTO_SUFFIXES = (".jpg", ".jpeg")
OK, BAD_ARGS, FAILED = 0, 2, 3


def photo_paths(folder):
    """Пути фото внутри папки через «/», по алфавиту."""
    found = [item for item in Path(folder).rglob("*") if item.is_file() and item.suffix.lower() in PHOTO_SUFFIXES]
    return sorted(item.relative_to(folder).as_posix() for item in found)


def add_folder(paths, folder, kind, project, device, part, folder_date=None, article=None):
    """Папка и её фото в базе настроенной машины → (Folder, сколько фото добавлено, сколько всего)."""
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError("Нет такой папки: {}".format(folder))
    rel_paths = photo_paths(folder)
    if not rel_paths:
        raise ValueError("В папке нет файлов .jpg: {}".format(folder))
    folder_date = folder_date or date.today().isoformat()
    datetime.strptime(folder_date, "%Y-%m-%d")
    config = Config.load(paths)
    db_value = config.get("database.path")
    db_path = paths.resolve(db_value)
    if not Path(db_value).is_absolute():  # как build_core: сетевую папку не создаём, иначе получим вторую пустую базу
        db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path, config.get("database.busy_timeout_ms", 5000))
    domain.migrate(db)
    from atlas.core.domain.folders import FoldersService
    from atlas.core.domain.parts import PartsService

    part_row = PartsService(db, config.get("project_kinds")).ensure(kind, project, device, part, article)
    service = FoldersService(db)
    row = service.add(part_row.id, str(folder), folder_date)
    added = service.add_photos(row.id, rel_paths)
    return row, added, len(rel_paths)


def run(paths, args, option):
    """Код выхода. option(args, имя) — разбор ключей из app.py."""
    values = {name: option(args, name) for name in ("--addfolder", "--kind", "--project", "--device", "--part")}
    report = paths.root / "reports" / "addfolder.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    missing = [name for name, value in values.items() if not value or value.startswith("--")]
    if missing:
        report.write_text("Не указано: {}\n".format(", ".join(missing)), encoding="utf-8")
        return BAD_ARGS
    try:
        row, added, total = add_folder(
            paths, values["--addfolder"], values["--kind"], values["--project"], values["--device"], values["--part"],
            option(args, "--date"), option(args, "--article"),
        )
    except Exception as exc:  # причина нужна человеку: в отчёт, а не в тишину
        log.exception("Не удалось добавить папку")
        report.write_text("ОШИБКА: {}\n".format(exc), encoding="utf-8")
        return FAILED
    report.write_text(
        "Готово: папка №{}, фото в папке {}, добавлено новых {}. Откройте Atlas — папка в списке «Новые».\n".format(
            row.id, total, added),
        encoding="utf-8",
    )
    return OK
