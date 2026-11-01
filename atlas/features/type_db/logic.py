"""Чистая логика карточки «В базу»: данные, имена файлов. Без Qt и без обращений к диску и базе."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

KIND_TYPE = "type"
KIND_DEFECT = "defect"
KINDS = (KIND_TYPE, KIND_DEFECT)
MAX_TYPE_NO = 99
_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_NAME_LIMIT = 60  # длина одного куска пути: полный путь на Windows 7 ограничен 260 знаками


class CardError(ValueError):
    """Карточка заполнена неверно: текст можно показать человеку."""


@dataclass(frozen=True)
class CardData:
    kind: str
    type_no: Optional[int]
    description: str
    article: str = ""


def checked(card):
    """Карточка в чистом виде или CardError."""
    if card.kind not in KINDS:
        raise CardError("Выберите: тип или дефект")
    description = " ".join(str(card.description).split())
    if not description:
        raise CardError("Опишите отличие")
    type_no = card.type_no
    if card.kind == KIND_TYPE:
        if type_no is None or not 1 <= int(type_no) <= MAX_TYPE_NO:
            raise CardError("Номер типа — от 1 до {}".format(MAX_TYPE_NO))
        type_no = int(type_no)
    else:
        type_no = None
    return CardData(card.kind, type_no, description, " ".join(str(card.article or "").split()))


def label(kind, type_no):
    return "Тип {}".format(type_no) if kind == KIND_TYPE else "Дефект"


def safe_name(text):
    """Кусок пути: без знаков, запрещённых в Windows, без точек и пробелов на конце, не длиннее предела."""
    cleaned = _ILLEGAL.sub("_", " ".join(str(text).split()))[:_NAME_LIMIT].rstrip(" .")
    return cleaned or "_"


def relative_dir(kind_of_project, project, device, part):
    return "/".join(safe_name(item) for item in (kind_of_project, project, device, part))


def file_stem(kind, type_no, now, unique):
    """«Тип 2_20261101_153012_ab12cd»: unique — короткая случайная строка, чтобы два сохранения в секунду не столкнулись."""
    return "{}_{}_{}".format(safe_name(label(kind, type_no)), now.strftime("%Y%m%d_%H%M%S"), unique)


def photo_rel(directory, stem):
    return "{}/{}_photo.jpg".format(directory, stem)


def crop_rel(directory, stem):
    return "{}/{}_crop.jpg".format(directory, stem)


def default_type_no(existing):
    """Следующий номер типа детали: существующие номера → максимум + 1 (нет типов — 1)."""
    numbers = [int(number) for number in existing if number is not None]
    return min(MAX_TYPE_NO, max(numbers) + 1) if numbers else 1


def under_folder(photo_path, folder_path):
    """Лежит ли фото в папке (в том числе в подпапке «Тип N»): регистр и вид слэшей не важны."""
    photo = str(photo_path).replace("\\", "/").rstrip("/").casefold()
    folder = str(folder_path).replace("\\", "/").rstrip("/").casefold()
    return photo.startswith(folder + "/")


def stamp(now=None):
    return now or datetime.now()
