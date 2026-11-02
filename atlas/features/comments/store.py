"""Фото комментариев: уменьшенная копия и миниатюра в папку comments.dir. Не из GUI-потока."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QImage, QImageReader

from atlas.core.domain.text import now_text
from atlas.features.comments import logic

DEFAULT_MAX_SIDE = 1600
THUMB_SIDE = 480
JPEG_QUALITY = 88


class StoreError(Exception):
    """Фото сохранить не удалось; текст можно показать человеку."""


def _read(source, side):
    """source — путь к файлу или QImage из буфера обмена."""
    if isinstance(source, QImage):
        image = source
        if max(image.width(), image.height()) > side:
            image = image.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    else:
        reader = QImageReader(str(source))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and max(size.width(), size.height()) > side:
            size.scale(QSize(side, side), Qt.KeepAspectRatio)
            reader.setScaledSize(size)
        image = reader.read()
    if image.isNull():
        raise StoreError("Не удалось прочитать фото: {}".format(source if not isinstance(source, QImage) else "буфер"))
    return image


class PhotoStore:
    def __init__(self, root, create_root=False, max_side=DEFAULT_MAX_SIDE):
        """Сетевую (абсолютную) папку сами не создаём: при сбое диска появилась бы вторая пустая."""
        self.root = Path(root)
        self.create_root = create_root
        self.max_side = max_side

    def save(self, sources):
        """Копии фото → список относительных путей. При сбое то, что успели записать, удаляется."""
        if not sources:
            return []
        if not self.root.is_dir():
            if not self.create_root:
                raise StoreError("Папка комментариев недоступна: {}".format(self.root))
            try:
                self.root.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise StoreError("Не удалось создать папку {}: {}".format(self.root, exc)) from exc
        stamp, unique = now_text(), uuid.uuid4().hex[:6]
        written, rels = [], []
        try:
            for number, source in enumerate(sources, 1):
                rel = logic.photo_rel(stamp, unique, number)
                big = _read(source, self.max_side)
                thumb = big.scaled(THUMB_SIDE, THUMB_SIDE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                for name, image in ((rel, big), (logic.thumb_rel(rel), thumb)):
                    target = self.root / name
                    written.append(target)
                    if not image.save(str(target), "JPEG", JPEG_QUALITY):
                        raise StoreError("Не удалось записать {}".format(target))
                rels.append(rel)
        except Exception:
            self.discard(written)
            raise
        return rels

    @staticmethod
    def discard(targets):
        for target in targets:
            try:
                os.remove(str(target))
            except OSError:
                pass

    def discard_rels(self, rels):
        self.discard([self.root / name for rel in rels for name in (rel, logic.thumb_rel(rel))])
