"""Чистая логика отчёта: колонки Excel, строки, текст письма. Без Qt, диска (кроме чтения шаблонов) и базы."""
from __future__ import annotations

import json
import re
from html import escape
from string import Template

COLUMN_KEYS = ("date", "project", "device", "part", "kind", "type_no", "sn", "photos", "kind_text", "text", "user")
DEFAULT_COLUMNS = (
    ("date", "Дата папки", 12), ("project", "Проект", 22), ("device", "Устройство", 22), ("part", "Деталь", 30),
    ("kind", "Что найдено", 14), ("type_no", "Тип №", 8), ("sn", "SN", 18), ("photos", "Фото", 8),
    ("kind_text", "Вид замечания", 26), ("text", "Пояснение", 44), ("user", "Проверил", 14),
)
DEFAULT_SHEET = "Проверка"
DEFAULT_SUBJECT = "RE: ${part}, ${date}"
DEFAULT_MAIL = ("<p>Добрый день!</p><p><b>${part}</b> (${photos_total} фото): ${types_line}</p>"
                "${defects_block}${remarks_block}${notes_block}<p>${user}</p>")
KIND_TITLES = {"type": "Тип", "defect": "Дефект", "remark": "Замечание"}


def load_columns(templates_dir):
    """(название листа, [(ключ, подпись, ширина)]) из templates/excel_columns.json; нет файла или ошибка — встроенное."""
    try:
        with open(str(templates_dir / "excel_columns.json"), encoding="utf-8-sig") as stream:
            raw = json.load(stream)
        columns = [(str(c["key"]), str(c["title"]), c.get("width", 14)) for c in raw["columns"]]
        columns = [c for c in columns if c[0] in COLUMN_KEYS]
        if not columns:
            raise ValueError("нет колонок")
        return str(raw.get("sheet") or DEFAULT_SHEET), columns
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_SHEET, list(DEFAULT_COLUMNS)


def load_mail(templates_dir):
    """Текст шаблона письма; нет файла — встроенный."""
    try:
        with open(str(templates_dir / "mail_reply.html"), encoding="utf-8-sig") as stream:
            text = stream.read()
        return re.sub(r"<!--.*?-->", "", text, flags=re.S).strip() or DEFAULT_MAIL
    except OSError:
        return DEFAULT_MAIL


def rows(entries, context, columns):
    """Строки Excel по записям черновика: список списков в порядке колонок."""
    result = []
    for entry in entries:
        values = {
            "date": context.get("date", ""), "project": context.get("project", ""),
            "device": context.get("device", ""), "part": context.get("part", ""),
            "kind": KIND_TITLES.get(entry.kind, entry.kind), "type_no": entry.type_no or "", "sn": entry.sn,
            "photos": entry.count if entry.kind == "type" and entry.manual_id is None else "",
            "kind_text": entry.kind_text, "text": entry.text, "user": context.get("user", ""),
        }
        result.append([values[key] for key, _title, _width in columns])
    return result


def _item_text(entry):
    parts = []
    if entry.sn:
        parts.append("SN {}".format(entry.sn))
    description = "; ".join(p for p in (entry.kind_text, entry.text) if p)
    if description:
        parts.append(description)
    return " — ".join(parts) if parts else "без SN"


def _block(title, entries):
    if not entries:
        return ""
    items = "; ".join(escape(_item_text(e)) for e in entries)
    return "<p><b>{}:</b> {}</p>".format(title, items)


def mail_values(entries, context, notes=""):
    """Подстановки шаблона письма (всё уже экранировано для HTML)."""
    types = {}
    for entry in entries:
        if entry.kind == "type":
            types.setdefault(entry.type_no, []).append(entry)
    parts = []
    for number in sorted(types):
        group = types[number]
        count = sum(e.count for e in group if e.manual_id is None)
        text = "Тип {}".format(number) + (": {}".format(count) if count else "")
        extra = "; ".join(e.text for e in group if e.text)
        parts.append(text + (" ({})".format(escape(extra)) if extra else ""))
    types_line = ", ".join(parts) if parts else "типов не отмечено"
    notes = notes.strip()
    return {
        "part": escape(context.get("part", "")), "device": escape(context.get("device", "")),
        "project": escape(context.get("project", "")), "date": escape(context.get("date", "")),
        "photos_total": str(context.get("photos_total", 0)), "types_line": types_line,
        "defects_block": _block("Дефекты", [e for e in entries if e.kind == "defect"]),
        "remarks_block": _block("Замечания", [e for e in entries if e.kind == "remark"]),
        "notes_block": "<p>{}</p>".format(escape(notes).replace("\n", "<br>")) if notes else "",
        "user": escape(context.get("user", "")),
    }


def render(template, values):
    return Template(template).safe_substitute(values)


def subject(pattern, context):
    values = {key: str(context.get(key, "")) for key in ("part", "device", "project", "date")}
    return Template(pattern or DEFAULT_SUBJECT).safe_substitute(values)


def file_name(context, stamp):
    """Имя файла Excel: деталь_дата_время.xlsx, без запрещённых в Windows знаков."""
    base = re.sub(r"_+", "_", re.sub(r'[\\/:*?"<>|\s]+', "_", "{}_{}".format(context.get("part", "отчёт"), context.get("date", ""))))
    return "{}_{}.xlsx".format(base.strip("_.") or "отчёт", stamp)


def date_text(folder_date):
    """2026-10-01 → 01.10.2026; что не похоже на дату — как есть."""
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(folder_date))
    return "{}.{}.{}".format(match.group(3), match.group(2), match.group(1)) if match else str(folder_date)
