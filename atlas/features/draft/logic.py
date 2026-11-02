"""Чистая логика черновика: автосписок из отметок фото, ручные строки. Без Qt, диска и базы."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

KIND_TYPE, KIND_DEFECT, KIND_REMARK = "type", "defect", "remark"
KIND_ORDER = {KIND_TYPE: 0, KIND_DEFECT: 1, KIND_REMARK: 2}
KIND_TITLES = {KIND_TYPE: "ТИП", KIND_DEFECT: "ДЕФЕКТ", KIND_REMARK: "ЗАМЕЧАНИЕ"}
KIND_TONES = {KIND_TYPE: "type2", KIND_DEFECT: "defect", KIND_REMARK: "remark"}
MANUAL_KINDS = (KIND_TYPE, KIND_DEFECT, KIND_REMARK)
NOTES_LIMIT = 20000
TEXT_LIMIT = 500


class DraftError(ValueError):
    """Строка заполнена неверно: текст можно показать человеку."""


@dataclass(frozen=True)
class Entry:
    key: str  # photo:<id>, type:<N> или manual:<id>
    kind: str
    type_no: Optional[int] = None
    sn: str = ""
    count: int = 1  # для типа — сколько фото
    kind_text: str = ""  # вид замечания из справочника
    text: str = ""  # пояснение
    manual_id: Optional[int] = None
    photo_id: Optional[int] = None  # первое фото типа или само фото


def mark_kind(mark):
    """('type', N) / ('defect', None) / ('remark', None) / None для строки mark фото."""
    if mark and str(mark).startswith("type:"):
        try:
            return KIND_TYPE, int(str(mark)[5:])
        except ValueError:
            return None
    if mark in (KIND_DEFECT, KIND_REMARK):
        return mark, None
    return None


def auto_entries(photos: Iterable, comments: Dict[str, str]) -> List[Entry]:
    """Автосписок: типы — одной строкой с числом фото, дефекты и замечания — по фото. Порядок: типы по номеру, потом остальное."""
    types: Dict[int, List] = {}
    singles = []
    for photo in photos:
        parsed = mark_kind(photo.mark)
        if parsed is None:
            continue
        kind, number = parsed
        if kind == KIND_TYPE:
            types.setdefault(number, []).append(photo)
        else:
            singles.append((kind, photo))
    result = []
    for number in sorted(types):
        group = types[number]
        key = "type:{}".format(number)
        sns = sorted({p.sn for p in group if p.sn})
        result.append(Entry(key, KIND_TYPE, number, sns[0] if len(sns) == 1 else "", len(group),
                            text=comments.get(key, ""), photo_id=group[0].id))
    for kind, photo in sorted(singles, key=lambda pair: (KIND_ORDER[pair[0]], pair[1].rel_path)):
        key = "photo:{}".format(photo.id)
        result.append(Entry(key, kind, None, photo.sn or "", 1, kind_text=getattr(photo, "defect_kind", None) or "",
                            text=comments.get(key, ""), photo_id=photo.id))
    return result


def manual_entry(row) -> Entry:
    """row: (id, kind, type_no, sn, body)."""
    item_id, kind, number, sn, body = row
    return Entry("manual:{}".format(item_id), kind, number, sn or "", 1, text=body or "", manual_id=item_id)


def checked_manual(kind, type_no, sn, body):
    """(kind, type_no|None, sn, body) или DraftError."""
    if kind not in MANUAL_KINDS:
        raise DraftError("Выберите, что добавить: тип, дефект или замечание")
    sn, body = (sn or "").strip(), (body or "").strip()
    if kind == KIND_TYPE:
        if not type_no or int(type_no) < 1:
            raise DraftError("Укажите номер типа")
        type_no = int(type_no)
    else:
        type_no = None
    if not sn and not body:
        raise DraftError("Заполните SN или описание")
    if len(body) > TEXT_LIMIT:
        raise DraftError("Описание длиннее {} знаков".format(TEXT_LIMIT))
    return kind, type_no, sn, body


def title(entry: Entry) -> str:
    if entry.kind == KIND_TYPE:
        return "{} {}".format(KIND_TITLES[KIND_TYPE], entry.type_no)
    return KIND_TITLES[entry.kind]


def all_entries(photos, comments, manual_rows) -> List[Entry]:
    return auto_entries(photos, comments) + [manual_entry(row) for row in manual_rows]


def count_text(entry: Entry) -> str:
    """«88 фото» для типа из отметок; у остальных строк пусто."""
    return "{} фото".format(entry.count) if entry.kind == KIND_TYPE and entry.manual_id is None else ""
