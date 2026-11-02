"""Раскладка установки на сетевом диске и версия программы. Без Qt.

    <папка установки>\\
      Atlas.bat, create_shortcut.vbs    запуск версии из version.txt, ярлык
      config\\local.json, var\\, logs\\     настройки и данные: от версии не зависят
      release\\version.txt               какая версия действует сейчас
      release\\<версия>\\atlas.exe         программа, у каждой версии своя папка

Версии лежат рядом, потому что файлы работающей программы заняты: у коллеги, который в ней работает, их не заменить.
"""
from __future__ import annotations

import logging
from pathlib import Path

from atlas import __version__

log = logging.getLogger("atlas.release")

RELEASE_DIR = "release"
VERSION_FILE = "version.txt"
EXE_NAME = "atlas.exe"


def current_version():
    return __version__


def parse_version(text):
    """'1.2.3' → (1, 2, 3); всё остальное → None. Такая строка станет именем папки: «..» и слэши сюда не пройдут."""
    parts = str(text).strip().split(".")
    if not all(part.isascii() and part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def home_of(program_dir):
    """Папка установки, если программа лежит в release/<версия>; иначе None (обычная копия). Файлы не читает."""
    program_dir = Path(program_dir)
    if parse_version(program_dir.name) is not None and program_dir.parent.name.lower() == RELEASE_DIR:
        return program_dir.parent.parent
    return None


def read_active_version(release_dir):
    """Версия из version.txt или None, если файл недоступен или испорчен. Сеть: не из GUI-потока."""
    path = Path(release_dir) / VERSION_FILE
    try:
        text = path.read_text(encoding="utf-8-sig").strip()  # Блокнот мог сохранить с BOM
    except (OSError, ValueError) as exc:
        log.info("Не прочитать %s: %s", path, exc)
        return None
    if parse_version(text) is None:
        log.warning("В %s не версия: %r", path, text[:40])
        return None
    return text


def write_active_version(release_dir, version):
    """Замена одним действием: читающий видит старую или новую версию, но не половину файла."""
    target = Path(release_dir) / VERSION_FILE
    part = target.with_name(VERSION_FILE + ".part")
    part.write_bytes((version + "\r\n").encode("ascii"))
    part.replace(target)
