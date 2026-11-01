"""«Добавить папку…» без Qt: чистка пути, подсказка проекта/устройства/детали/даты из пути, проверка полей."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import PureWindowsPath
from typing import Optional, Tuple

from atlas.core.domain.text import normalize_name

DEFAULT_NO_DEVICE = "Без устройства"
_QUOTES = "\"'«»“”"
# Последняя папка пути — «дата копирования + кол-во фото»: дата в начале или в конце названия
_ISO = r"(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})"
_DMY = r"(?P<d>\d{1,2})[.\-/](?P<m>\d{1,2})(?:[.\-/](?P<y>\d{4}|\d{2}))?"
_AT_START = [re.compile(r"^\s*" + pattern + r"(?!\d)") for pattern in (_ISO, _DMY)]
_AT_END = [re.compile(r"(?<!\d)" + pattern + r"\s*$") for pattern in (_ISO, _DMY)]


@dataclass(frozen=True)
class Suggestion:
    kind: Optional[str]
    project: str
    device: str
    part: str
    date: Optional[str]  # ГГГГ-ММ-ДД


@dataclass(frozen=True)
class FolderData:
    path: str
    kind: str
    project: str
    device: str
    part: str
    date: str  # ГГГГ-ММ-ДД
    photos: Tuple[str, ...]  # пути фото внутри папки через «/»


def load_no_device(data_dir):
    """Имя устройства «по умолчанию» из data/add_folder.json; нет файла — встроенное."""
    try:
        with open(str(data_dir / "add_folder.json"), encoding="utf-8") as stream:
            value = str(json.load(stream).get("no_device_name", "")).strip()
    except (OSError, ValueError, AttributeError):
        return DEFAULT_NO_DEVICE
    return value or DEFAULT_NO_DEVICE


def clean_path(text):
    """Путь из поля: без пробелов и кавычек по краям (проводник копирует путь в кавычках)."""
    return str(text).strip().strip(_QUOTES).strip()


def _make_date(year, month, day, today):
    try:
        number = int(year) if year else today.year
        if number < 100:
            number += 2000
        return date(number, int(month), int(day)).isoformat()
    except ValueError:
        return None


def parse_date(text, today=None):
    """Дата, написанная целиком: ГГГГ-ММ-ДД, ДД.ММ.ГГГГ, ДД.ММ.ГГ, ДД.ММ (год — текущий). Иначе None."""
    today = today or date.today()
    text = str(text).strip()
    for pattern in (re.compile("^" + _ISO + "$"), re.compile("^" + _DMY + "$")):
        found = pattern.match(text)
        if found:
            return _make_date(found.group("y"), found.group("m"), found.group("d"), today)
    return None


def find_date(name, today=None):
    """Дата в начале или в конце названия папки: «31.10.2026 (120 фото)», «120 фото 2026-10-31». Иначе None."""
    today = today or date.today()
    for pattern in _AT_START + _AT_END:
        found = pattern.search(name)
        if found:
            result = _make_date(found.group("y"), found.group("m"), found.group("d"), today)
            if result:
                return result
    return None


def split_path(text):
    """(начало пути — диск или сервер, [папки]). Понимает «R:\\…», «\\\\сервер\\ресурс\\…» и «/»."""
    pure = PureWindowsPath(clean_path(text))
    parts = list(pure.parts)
    anchor = pure.anchor
    return anchor, parts[1:] if anchor else parts


def suggest(text, kinds=(), no_device=DEFAULT_NO_DEVICE, today=None):
    """Что подставить в поля по пути `ДИСК/Однотипность/Проект/[Устройство/]Деталь/дата`.

    Подсказка, а не истина: уровней может быть три или четыре, поэтому человек всё равно видит и правит поля.
    Вид проекта — по букве диска, если она совпала с одним из видов.
    """
    anchor, names = split_path(text)
    when = find_date(names[-1], today) if names else None
    folders = names[:-1] if when else names
    part = folders[-1] if folders else ""
    if len(folders) >= 4:
        device, project = folders[-2], folders[-3]
    elif len(folders) >= 2:
        device, project = no_device, folders[-2]
    else:
        device, project = no_device, ""
    if not part:
        device = project = ""
    letter = anchor[:1].casefold() if len(anchor) >= 2 and anchor[1] == ":" else ""
    kind = next((item for item in kinds if str(item).casefold() == letter), None) if letter else None
    return Suggestion(kind, project, device, part, when)


def check(path, kind, project, device, part, date_text, photos, kinds, today=None):
    """FolderData или текст ошибки (str), который можно показать человеку."""
    path = clean_path(path)
    if not path:
        return "Укажите папку с фото"
    if kind not in kinds:
        return "Выберите вид проекта"
    for label, value in (("проект", project), ("устройство", device), ("название детали", part)):
        if not normalize_name(value):
            return "Укажите {}".format(label)
    when = parse_date(date_text, today)
    if when is None:
        return "Дата — в виде ГГГГ-ММ-ДД или ДД.ММ.ГГГГ"
    if not photos:
        return "В папке нет файлов .jpg"
    return FolderData(path, kind, " ".join(project.split()), " ".join(device.split()), " ".join(part.split()), when, tuple(photos))


def known_options(parts):
    """Подсказки для выпадающих списков: {вид: {проект: [устройства]}} по уже внесённым деталям."""
    result = {}
    for part in parts:
        devices = result.setdefault(part.kind, {}).setdefault(part.project, [])
        if part.device not in devices:
            devices.append(part.device)
    for projects in result.values():
        for devices in projects.values():
            devices.sort(key=normalize_name)
    return result


def today_text(now=None):
    return (now or datetime.now()).date().isoformat()
