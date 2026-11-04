"""Запись карточки: картинки в папку type_db.dir, строка в базу. Всё это не из GUI-потока."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from atlas.features.type_db import logic, render


class StoreError(Exception):
    """Карточку сохранить не удалось; текст можно показать человеку."""


@dataclass(frozen=True)
class SaveRequest:
    """Снимок на момент нажатия: пока идёт запись, человек может листать и рисовать дальше."""

    part: object  # Part ядра
    card: logic.CardData
    photo_path: str
    rotation: int
    shapes: tuple
    sn: Optional[str]
    user_id: Optional[int]


class TypeStore:
    def __init__(self, repo, root, colors, max_side=render.DEFAULT_MAX_SIDE, quality=render.JPEG_QUALITY, create_root=False):
        """root — папка картинок. Сетевую (абсолютную) сами не создаём: при сбое диска появилась бы вторая пустая — как с БД."""
        self.repo = repo
        self.root = Path(root)
        self.colors = colors
        self.max_side = max_side
        self.quality = quality
        self.create_root = create_root

    def save(self, request, now=None, unique=None):
        card = logic.checked(request.card)
        if not self.root.is_dir():
            if not self.create_root:
                raise StoreError("Папка базы типов недоступна: {}".format(self.root))
            self._mkdir(self.root)
        try:
            rendered = render.render(request.photo_path, request.shapes, request.rotation, self.colors, self.max_side)
        except Exception as exc:  # файл пропал, не читается, оборвалась сеть
            raise StoreError("Не удалось прочитать фото: {}".format(exc)) from exc
        part = request.part
        directory = logic.relative_dir(part.kind, part.project, part.device, part.name)
        stem = logic.file_stem(card.kind, card.type_no, logic.stamp(now), unique or uuid.uuid4().hex[:6])
        photo_rel = logic.photo_rel(directory, stem)
        crop_rel = logic.crop_rel(directory, stem) if rendered.crop is not None else None
        written = []
        try:
            self._mkdir(self.root / directory)
            for rel, image in ((photo_rel, rendered.photo), (crop_rel, rendered.crop)):
                if rel is None:
                    continue
                target = self.root / rel
                written.append(target)
                render.save_jpeg(image, target, self.quality)
            return self.repo.add(
                part.id, card.kind, card.type_no, card.description, card.article or part.article, photo_rel, crop_rel,
                request.photo_path, request.sn, request.user_id,
            )
        except Exception as exc:  # диск или база: после себя ничего не оставляем
            for target in written:
                try:
                    os.remove(str(target))
                except OSError:
                    pass
            if isinstance(exc, StoreError):
                raise
            raise StoreError("Не удалось сохранить в базу типов: {}".format(exc)) from exc

    def delete(self, type_id):
        """Запись — из базы, затем её картинки с диска. → TypeRecord или None (уже удалили на другом ПК).

        Картинку, которую не удалось стереть (сеть, файл открыт), оставляем: запись из базы уже ушла, ничего не сломано.
        """
        record = self.repo.delete(type_id)
        if record is None:
            return None
        for rel in (record.photo_rel, record.crop_rel):
            if rel:
                try:
                    os.remove(str(self.root / rel))
                except OSError:
                    pass
        return record

    def _mkdir(self, path):
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StoreError("Не удалось создать папку {}: {}".format(path, exc)) from exc
