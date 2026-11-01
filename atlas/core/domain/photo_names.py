"""Разбор имени фото: артикул, ракурс, SN. Шаблон — в data/photo_names.json, чтобы менять без программиста."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Optional

log = logging.getLogger("atlas.photo_names")

# Запасной шаблон, если data/photo_names.json потерялся: тот же, что в файле.
DEFAULT_PATTERN = r"^(?P<article>[0-9]+)_(?P<view>[0-9]+)_(?P<sn>[0-9A-Za-z]+)(?:_[^_]+)?$"
_GROUPS = ("article", "view", "sn")


@dataclass(frozen=True)
class PhotoName:
    article: str
    view: int
    sn: str


def compile_pattern(text):
    """Шаблон со всеми тремя группами или ValueError."""
    pattern = re.compile(text)
    missing = [group for group in _GROUPS if group not in pattern.groupindex]
    if missing:
        raise ValueError("В шаблоне имени нет групп: {}".format(", ".join(missing)))
    return pattern


def load_pattern(data_dir):
    """Шаблон из data/photo_names.json. Файла нет или он испорчен — стандартный, с записью в журнал."""
    path = Path(data_dir) / "photo_names.json"
    try:
        return compile_pattern(json.loads(path.read_text(encoding="utf-8-sig"))["pattern"])
    except (OSError, ValueError, KeyError, TypeError, re.error) as exc:
        log.warning("Нет шаблона имён фото в %s (%s), взят стандартный", path, exc)
        return compile_pattern(DEFAULT_PATTERN)


def parse_photo_name(name, pattern=None) -> Optional[PhotoName]:
    """Имя файла (с расширением или без) → PhotoName; не подошло — None. Ракурс — число, SN — как написано."""
    stem = PureWindowsPath(str(name)).stem  # понимает и «/», и «\\» на любой ОС
    match = (pattern or compile_pattern(DEFAULT_PATTERN)).match(stem)
    if match is None:
        return None
    return PhotoName(match.group("article"), int(match.group("view")), match.group("sn"))
