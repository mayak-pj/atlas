"""Такая же деталь рядом на диске, если её нет в Atlas (04.11.2026).

Правил, где лежат прошлые проверки, пока нет (OPEN_ITEMS №2), а для тестов кнопка «Найти такую же деталь» должна
находить эталон, который лежит рядом: «Деталь - Эталон» возле «Деталь», другие даты той же детали. Ищется только
рядом: соседи открытой папки и соседи папки над ней. Подходит папка, чьё имя начинается с названия детали
(регистр, «е/ё» и разделители не важны) и в которой есть фото. Из нескольких — изменённая последней.
Папка в Atlas не добавляется: эталон только показывается. Выключить — `compare.disk_search: false`.
"""
from __future__ import annotations

from pathlib import Path

from atlas.core.domain.text import normalize_name
from atlas.shared.fs.photos import photo_paths


def candidates(folder_path, part_name):
    """[(папка, [пути фото])] — подходящие соседи, свежие первыми. Не из GUI-потока: ходит по сетевому диску."""
    current = Path(str(folder_path))
    key = normalize_name(part_name)
    if not key:
        return []
    skip = {current, current.parent}
    found = []
    for level in (current.parent, current.parent.parent):
        try:
            children = [item for item in level.iterdir() if item.is_dir()]
        except OSError:
            continue
        for item in children:
            if item in skip or not normalize_name(item.name).startswith(key):
                continue
            try:
                rels = photo_paths(item)
                stamp = item.stat().st_mtime
            except OSError:
                continue
            if rels:
                found.append((stamp, item, [str(item / Path(*rel.split("/"))) for rel in rels]))
        if found:
            break  # ближайший уровень важнее: соседняя дата той же детали ближе, чем папка над ней
    found.sort(key=lambda entry: entry[0], reverse=True)
    return [(item, paths) for _, item, paths in found]
