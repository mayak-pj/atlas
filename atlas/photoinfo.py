"""--photoinfo: как лежат фото папки — для разбора «открыло фото не в той ориентации» (замечание с выезда, 14.11.2026).

    atlas.exe --photoinfo "R:\\папка с фото"      (или перетащить папку на Atlas_photoinfo.bat)

Без окна и без Qt. Для каждого фото: размер в файле, метка поворота EXIF (её учитывают и Проводник, и Atlas),
как фото встаёт на экране, и поворот, запомненный в Atlas (если папка добавлена). Итог — reports/photoinfo.txt
в папке установки: его можно привезти вместо самих фото.
"""
from __future__ import annotations

import logging
import struct
from collections import Counter
from pathlib import Path

from atlas.core.report import TextReport
from atlas.shared.fs.photos import photo_paths

log = logging.getLogger("atlas.photoinfo")

OK, BAD_ARGS, FAILED = 0, 2, 3
REPORT_NAME = "photoinfo.txt"
ORIENTATIONS = {
    1: "как есть", 2: "зеркально", 3: "180°", 4: "180° зеркально",
    5: "90° зеркально", 6: "90° по часовой", 7: "270° зеркально", 8: "90° против часовой",
}
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def jpeg_info(path):
    """(ширина, высота, ориентация EXIF или None) из заголовка JPEG; не JPEG или испорчен — ValueError.

    Читается только начало файла: метки идут до сжатых данных.
    """
    with open(str(path), "rb") as stream:
        if stream.read(2) != b"\xff\xd8":
            raise ValueError("не JPEG")
        orientation, size = None, None
        while size is None:
            head = stream.read(4)
            if len(head) < 4 or head[0] != 0xFF:
                raise ValueError("испорчен заголовок")
            marker, length = head[1], struct.unpack(">H", head[2:])[0]
            body = stream.read(length - 2)
            if marker == 0xE1 and body.startswith(b"Exif\x00\x00") and orientation is None:
                orientation = _exif_orientation(body[6:])
            elif marker in _SOF:
                height, width = struct.unpack(">HH", body[1:5])
                size = (width, height)
            elif marker == 0xDA:
                raise ValueError("нет размера до данных")
        return size[0], size[1], orientation


def _exif_orientation(tiff):
    """Тег 0x0112 из IFD0 или None."""
    if len(tiff) < 8 or tiff[:2] not in (b"II", b"MM"):
        return None
    order = "<" if tiff[:2] == b"II" else ">"
    offset = struct.unpack(order + "I", tiff[4:8])[0]
    if offset + 2 > len(tiff):
        return None
    count = struct.unpack(order + "H", tiff[offset:offset + 2])[0]
    for number in range(count):
        start = offset + 2 + number * 12
        entry = tiff[start:start + 12]
        if len(entry) < 12:
            return None
        tag, kind = struct.unpack(order + "HH", entry[:4])
        if tag == 0x0112 and kind == 3:
            return struct.unpack(order + "H", entry[8:10])[0]
    return None


def shown_size(width, height, orientation):
    """Размер на экране после метки EXIF: 5–8 меняют ширину и высоту местами."""
    return (height, width) if orientation in (5, 6, 7, 8) else (width, height)


def _rotations(paths, folder):
    """{относительный путь: поворот в Atlas} или None, если папки нет в базе или база недоступна."""
    try:
        from atlas.core import domain
        from atlas.core.config import Config
        from atlas.core.db import Database
        from atlas.core.domain.folders import FoldersService, path_key

        config = Config.load(paths)
        db_path = paths.resolve(config.get("database.path"))
        if not db_path.is_file():
            return None
        db = Database(db_path, config.get("database.busy_timeout_ms", 5000))
        domain.migrate(db)
        key = path_key(str(folder))
        row = db.read(lambda conn: conn.execute("SELECT id FROM folders WHERE path_key = ?", (key,)).fetchone())
        if row is None:
            return None
        return {photo.rel_path: photo.rotation for photo in FoldersService(db).photos(row[0])}
    except Exception as exc:  # отчёт о файлах нужен и без базы
        log.warning("Повороты из базы не прочитаны: %s", exc)
        return None


def describe(folder, rotations=None):
    """Строки отчёта о папке."""
    folder = Path(folder)
    rels = photo_paths(folder)
    lines = ["Папка: {}".format(folder), "Фото: {}".format(len(rels))]
    if rotations is None:
        lines.append("Поворотов Atlas нет: папка не добавлена в Atlas или база недоступна")
    lines.append("")
    lines.append("файл | в файле Ш×В | метка EXIF | на экране Ш×В | поворот Atlas | итог")
    tally = Counter()
    for rel in rels:
        try:
            width, height, orientation = jpeg_info(folder / Path(*rel.split("/")))
        except (OSError, ValueError, struct.error) as exc:
            lines.append("{} | не прочитан: {}".format(rel, exc))
            tally["не прочитан"] += 1
            continue
        shown_w, shown_h = shown_size(width, height, orientation)
        turn = (rotations or {}).get(rel, 0)
        if turn in (90, 270):
            shown_w, shown_h = shown_h, shown_w
        result = "вертикальное" if shown_h > shown_w else "горизонтальное" if shown_w > shown_h else "квадратное"
        mark = "нет" if orientation is None else "{} ({})".format(orientation, ORIENTATIONS.get(orientation, "?"))
        lines.append("{} | {}×{} | {} | {}×{} | {} | {}".format(
            rel, width, height, mark, *shown_size(width, height, orientation), "{}°".format(turn) if turn else "—", result))
        tally["метка EXIF: {}".format(mark)] += 1
        tally["итог: {}".format(result)] += 1
        if turn:
            tally["повёрнуто в Atlas"] += 1
    lines.append("")
    lines.append("Сводка:")
    lines.extend("  {}: {}".format(name, count) for name, count in sorted(tally.items()))
    return lines


def run(paths, folder):
    """Код выхода. Отчёт — в reports/ папки установки (у обычной копии — рядом с программой)."""
    report_path = paths.home / "reports" / REPORT_NAME
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = TextReport(report_path)
    except OSError:
        return FAILED
    if not folder or folder.startswith("--") or not Path(folder).is_dir():
        report.line("Нет такой папки: {}".format(folder or "(не указана)"))
        return BAD_ARGS
    try:
        lines = describe(folder, _rotations(paths, folder))
        report.line("\n".join(lines))  # одной записью: отчёт лежит на сетевом диске
    except Exception as exc:
        log.exception("Отчёт о фото не составлен")
        report.line("ОШИБКА: {}".format(exc))
        return FAILED
    return OK
