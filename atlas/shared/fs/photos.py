"""Поиск фото в папке: .jpg и .jpeg, подпапки тоже. Без Qt; на сетевом диске может быть долгим — вызывать не из GUI-потока."""
from __future__ import annotations

from pathlib import Path

PHOTO_SUFFIXES = (".jpg", ".jpeg")


def photo_paths(folder):
    """Пути фото внутри папки через «/», по алфавиту."""
    folder = Path(folder)
    found = [item for item in folder.rglob("*") if item.is_file() and item.suffix.lower() in PHOTO_SUFFIXES]
    return sorted(item.relative_to(folder).as_posix() for item in found)
