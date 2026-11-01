"""Чтение фото с диска. Только не из GUI-потока: файл может лежать на сетевом диске."""
from __future__ import annotations

import os

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QImage, QImageReader

from atlas.shared.viewer.levels import L3, scaled_size


class DecodeError(Exception):
    """Файл не прочитать как изображение."""


def file_signature(path):
    """(путь, размер, mtime). Другая подпись — другой файл для дискового кэша."""
    stat = os.stat(str(path))
    return str(path), stat.st_size, stat.st_mtime_ns


def decode_file(path, level):
    """QImage уровня L1–L3 с учётом EXIF-поворота.

    Размер задаётся в осях файла: QImageReader сначала масштабирует, потом поворачивает.
    """
    reader = QImageReader(str(path))
    reader.setDecideFormatFromContent(True)
    reader.setAutoTransform(True)
    size = reader.size()
    if level != L3 and size.isValid():
        reader.setScaledSize(QSize(*scaled_size(size.width(), size.height(), level)))
    image = reader.read()
    if image.isNull():
        raise DecodeError("{}: {}".format(path, reader.errorString()))
    return image


def make_thumbnail(image, side):
    """L0 из уже прочитанного L1: второе чтение большого файла с сетевого диска не нужно. Не увеличивает."""
    if max(image.width(), image.height()) <= side:
        return image
    return image.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def read_small(path):
    """Файл из дискового кэша целиком; None — не прочитался."""
    image = QImage()
    return image if image.load(str(path)) else None
