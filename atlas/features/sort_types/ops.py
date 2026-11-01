"""Раскладка и отмена: файлы, база, журнал. Без Qt; вызывать не из GUI-потока."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

from atlas.features.sort_types.logic import plan_moves
from atlas.shared.fs.moves import move_files, remove_if_empty, undo_moves

log = logging.getLogger("atlas.sort_types")


@dataclass
class Result:
    moved: int = 0
    failed: List[Tuple[str, str]] = field(default_factory=list)  # (путь внутри папки, причина)
    skipped: int = 0  # при отмене: фото, которые с тех пор переместили или переименовали
    journal_ok: bool = True


def _path(root, rel):
    return root.joinpath(*rel.split("/"))


class Sorter:
    def __init__(self, folders, repo, template):
        self.folders = folders
        self.repo = repo
        self.template = template

    def plan(self, folder_id):
        return plan_moves(self.folders.photos(folder_id), self.template)

    def can_undo(self, folder_id):
        return self.repo.last_batch(folder_id) is not None

    def apply(self, folder_id, plan, user_id=None) -> Result:
        """Файлы переносятся первыми, потом одной транзакцией меняются пути в базе. Сбой базы возвращает файлы назад."""
        folder = self.folders.get(folder_id)
        if folder is None:
            raise LookupError("Нет папки {}".format(folder_id))
        root = Path(folder.path)
        by_src = {_path(root, move.from_rel): move for move in plan.moves}
        report = move_files((_path(root, move.from_rel), _path(root, move.to_rel)) for move in plan.moves)
        moved = [by_src[src] for src, _dst in report.done]
        result = Result(failed=[(str(src.relative_to(root).as_posix()), reason) for src, _dst, reason in report.failed])
        if not moved:
            return result
        try:
            self.folders.move_photos([(move.photo_id, move.to_rel) for move in moved])
        except Exception:
            undo_moves(report.done)  # база не приняла: на диске всё как было
            raise
        result.moved = len(moved)
        try:
            self.repo.add_batch(folder_id, user_id, [(m.photo_id, m.from_rel, m.to_rel) for m in moved])
        except Exception:  # файлы и база согласованы, потеряна только возможность отмены
            log.exception("Раскладка выполнена, но журнал не записан")
            result.journal_ok = False
        return result

    def undo(self, folder_id) -> Result:
        """Возвращает последнюю раскладку папки. Фото, которые с тех пор тронули, не трогаем."""
        folder = self.folders.get(folder_id)
        last = self.repo.last_batch(folder_id)
        if folder is None or last is None:
            return Result()
        batch_id, moves = last
        root = Path(folder.path)
        current = {photo.id: photo.rel_path for photo in self.folders.photos(folder_id)}
        actual = [move for move in moves if current.get(move[0]) == move[2]]
        stale = [move for move in moves if move not in actual]
        by_dst = {_path(root, to_rel): (photo_id, from_rel) for photo_id, from_rel, to_rel in actual}
        report = move_files((_path(root, to_rel), _path(root, from_rel)) for _id, from_rel, to_rel in actual)
        restored = [by_dst[src] for src, _dst in report.done]
        result = Result(
            failed=[(str(src.relative_to(root).as_posix()), reason) for src, _dst, reason in report.failed],
            skipped=len(stale),
        )
        if restored:
            try:
                self.folders.move_photos(restored)
            except Exception:
                move_files((dst, src) for src, dst in report.done)  # вернули назад — как до отмены
                raise
        result.moved = len(restored)
        for taken_from, _put_back_to in report.done:
            remove_if_empty(taken_from.parent)  # подпапка типа опустела
        self.repo.finish_undo(batch_id, [photo_id for photo_id, _rel in restored] + [move[0] for move in stale])
        return result
