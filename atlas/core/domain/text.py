"""Ключи для поиска и сравнения. Считаются в Python: LOWER в SQLite не понимает кириллицу."""
from __future__ import annotations

import unicodedata
from datetime import datetime

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def now_text(now=None):
    return (now or datetime.now()).strftime(TIME_FORMAT)


def clean_name(raw):
    """Имя для показа: без лишних пробелов."""
    return " ".join(str(raw).split())


def name_key(name):
    """Ключ человека: только регистр («петров» и «Петров» — один, «Семёнов» и «Семенов» — разные)."""
    return name.casefold()


def normalize_name(raw):
    """Ключ проекта, устройства, детали: регистр, «е/ё» и разделители не важны.

    «SSD XS-2280», «ssd_xs 2280» и «SSDXS2280» — одна деталь. Нечёткое сравнение — не здесь, а в findings.
    """
    text = unicodedata.normalize("NFKC", str(raw)).casefold().replace("ё", "е")
    return "".join(ch for ch in text if ch.isalnum())


def required_key(raw, what):
    key = normalize_name(raw)
    if not key:
        raise ValueError("Пустое название: {}".format(what))
    return key
