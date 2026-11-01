"""Настройки вида, которые пользователь выбрал сам (панели, тема): файл var/ui_state.json рядом с программой, не в git."""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("atlas.ui_state")

FILE = "ui_state.json"


def path_of(paths):
    return Path(paths.root) / "var" / FILE


def load(paths):
    """Сохранённое; нет файла или он испорчен — пустой словарь."""
    try:
        data = json.loads(path_of(paths).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(paths, key, value):
    data = load(paths)
    data[key] = value
    target = path_of(paths)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except OSError as exc:
        log.warning("Не записать %s (%s): выбор не сохранён", target, exc)
        return False
