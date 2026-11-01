"""Безопасное перемещение файлов внутри одной папки: ничего не перезаписывается, каждый сбой описан.

Только переименование (`os.rename`) в пределах одного тома: на сетевом диске оно мгновенное и не копирует данные.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

REASON_MISSING = "файла нет"
REASON_EXISTS = "в целевой папке уже есть такой файл"


@dataclass
class MoveReport:
    done: List[Tuple[Path, Path]]  # (откуда, куда) — то, что действительно переместилось
    failed: List[Tuple[Path, Path, str]]  # (откуда, куда, причина)


def move_files(pairs) -> MoveReport:
    """Перемещает по одному; сбой одного файла остальных не останавливает. Существующий файл не перезаписывается."""
    report = MoveReport([], [])
    for src, dst in pairs:
        src, dst = Path(src), Path(dst)
        try:
            if not src.is_file():
                report.failed.append((src, dst, REASON_MISSING))
            elif dst.exists():
                report.failed.append((src, dst, REASON_EXISTS))
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.rename(str(src), str(dst))  # на Windows не перезапишет; на других ОС exists() выше
                report.done.append((src, dst))
        except OSError as exc:  # файл открыт другой программой, нет прав, сеть пропала
            report.failed.append((src, dst, str(exc) or exc.__class__.__name__))
    return report


def undo_moves(done) -> MoveReport:
    """Возвращает перемещённое на место (в обратном порядке). Пустые папки, оставшиеся после, убирает."""
    report = move_files((dst, src) for src, dst in reversed(list(done)))
    for taken_from, _put_back_to in report.done:
        remove_if_empty(taken_from.parent)
    return report


def remove_if_empty(folder):
    """Убирает пустую папку; непустую и несуществующую не трогает."""
    try:
        folder.rmdir()  # непустую не удалит
    except OSError:
        pass
