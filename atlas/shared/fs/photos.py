"""Поиск фото в папке: .jpg и .jpeg, подпапки тоже. Без Qt; на сетевом диске может быть долгим — вызывать не из GUI-потока."""
from __future__ import annotations

from pathlib import Path

from atlas.core.domain.folders import is_system_file

PHOTO_SUFFIXES = (".jpg", ".jpeg")


def photo_paths(folder):
    """Пути фото внутри папки через «/», по алфавиту."""
    folder = Path(folder)
    found = [item for item in folder.rglob("*") if item.is_file() and item.suffix.lower() in PHOTO_SUFFIXES]
    rels = (item.relative_to(folder).as_posix() for item in found)
    return sorted(rel for rel in rels if not is_system_file(rel))  # «._…» — служебные файлы macOS, не фото
