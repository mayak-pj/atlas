"""План раскладки без Qt и без диска: какие фото куда."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

log = logging.getLogger("atlas.sort_types")

DEFAULT_TEMPLATE = "Тип {n}"
_TYPE_MARK = re.compile(r"^type:(\d+)$")


@dataclass(frozen=True)
class Move:
    photo_id: int
    from_rel: str
    to_rel: str


@dataclass
class Plan:
    moves: List[Move] = field(default_factory=list)
    per_folder: Dict[str, int] = field(default_factory=dict)  # подпапка → сколько фото уйдёт
    in_place: int = 0  # уже лежат где надо
    not_typed: int = 0  # без отметки типа: остаются
    conflicts: List[str] = field(default_factory=list)  # одно имя в одну подпапку: переносим первое, остальные остаются


def load_template(data_dir):
    """Шаблон имени подпапки из data/type_folders.json; без «{n}» или без файла — «Тип {n}»."""
    path = Path(data_dir) / "type_folders.json"
    try:
        template = str(json.loads(path.read_text(encoding="utf-8-sig"))["template"])
        template.format(n=1)
        if "{n}" not in template or not template.format(n=1).strip():
            raise ValueError("нет «{n}»")
        return template
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        log.warning("Нет шаблона подпапок в %s (%s), взят стандартный", path, exc)
        return DEFAULT_TEMPLATE


def folder_name(mark, template):
    """«type:2» → «Тип 2»; другая отметка → None."""
    match = _TYPE_MARK.match(mark or "")
    return template.format(n=int(match.group(1))) if match else None


def plan_moves(photos, template) -> Plan:
    """photos — Photo из сервиса folders. Имя файла сохраняется; всё лежит ровно в подпапке типа, без вложений."""
    plan = Plan()
    taken = set()
    for photo in photos:
        target_dir = folder_name(photo.mark, template)
        if target_dir is None:
            plan.not_typed += 1
            continue
        directory, _, name = photo.rel_path.rpartition("/")
        if directory.casefold() == target_dir.casefold():
            plan.in_place += 1
            continue
        target = "{}/{}".format(target_dir, name)
        if target.casefold() in taken:
            plan.conflicts.append(photo.rel_path)
            continue
        taken.add(target.casefold())
        plan.moves.append(Move(photo.id, photo.rel_path, target))
        plan.per_folder[target_dir] = plan.per_folder.get(target_dir, 0) + 1
    return plan


def confirm_text(plan):
    """Текст вопроса перед перемещением."""
    lines = ["Переместить {} фото в подпапки:".format(len(plan.moves))]
    lines += ["  {} — {}".format(name, count) for name, count in sorted(plan.per_folder.items())]
    if plan.not_typed:
        lines.append("Без отметки типа ({}) останутся на месте.".format(plan.not_typed))
    if plan.conflicts:
        lines.append("Не будут перемещены из-за одинаковых имён: {}.".format(len(plan.conflicts)))
    lines.append("Раскладку можно отменить.")
    return "\n".join(lines)
