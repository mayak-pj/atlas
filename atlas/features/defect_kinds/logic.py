"""Имена видов без Qt и без базы: проверка, ключ сравнения, первоначальный список из data/."""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("atlas.defect_kinds")

MAX_LENGTH = 80
SEED_FILE = "defect_kinds.json"
EVENT_CHANGED = "defect_kinds.changed"


class KindError(ValueError):
    """Текст показывается человеку."""


def clean(name):
    """Лишние пробелы убираются; пусто или слишком длинно — KindError."""
    text = " ".join(str(name or "").split())
    if not text:
        raise KindError("Введите название вида")
    if len(text) > MAX_LENGTH:
        raise KindError("Слишком длинно: не больше {} знаков".format(MAX_LENGTH))
    return text


def key(name):
    return " ".join(str(name).split()).lower().replace("ё", "е")


def seed_names(data_dir):
    """Список из data/defect_kinds.json — только чтобы не начинать с пустого."""
    path = Path(data_dir) / SEED_FILE
    try:
        names = json.loads(path.read_text(encoding="utf-8-sig"))["kinds"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.info("Начального списка видов нет (%s): %s", path, exc)
        return []
    result, seen = [], set()
    for name in names:
        try:
            text = clean(name)
        except KindError:
            continue
        if key(text) not in seen:
            seen.add(key(text))
            result.append(text)
    return result
