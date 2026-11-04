"""Чистая логика карточки «В базу»: данные, имена файлов. Без Qt и без обращений к диску и базе."""
from __future__ import annotations

import re
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from atlas.core.domain.text import normalize_name

KIND_TYPE = "type"
KIND_DEFECT = "defect"
KINDS = (KIND_TYPE, KIND_DEFECT)
MAX_TYPE_NO = 99
_TYPE_WORD = normalize_name("Тип")
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
    description = " ".join(str(card.description or "").split())  # необязательно: добавляют сразу, описать можно потом
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


def default_type_no(existing, mark=None):
    """Номер типа в окне карточки. Фото уже отмечено «Тип N» — N (это и хотят сохранить);
    иначе следующий номер детали: существующие → максимум + 1 (нет типов — 1)."""
    marked = marked_type_no(mark)
    if marked is not None:
        return marked
    numbers = [int(number) for number in existing if number is not None]
    return min(MAX_TYPE_NO, max(numbers) + 1) if numbers else 1


def marked_type_no(mark):
    """«type:2» → 2; другая отметка или её нет — None."""
    text = str(mark or "")
    if not text.startswith("type:"):
        return None
    try:
        number = int(text[len("type:"):])
    except ValueError:
        return None
    return number if 1 <= number <= MAX_TYPE_NO else None


def under_folder(photo_path, folder_path):
    """Лежит ли фото в папке (в том числе в подпапке «Тип N»): регистр и вид слэшей не важны."""
    photo = str(photo_path).replace("\\", "/").rstrip("/").casefold()
    folder = str(folder_path).replace("\\", "/").rstrip("/").casefold()
    return photo.startswith(folder + "/")


def stamp(now=None):
    return now or datetime.now()


# --- выдача: записи, поиск, порядок -------------------------------------------------
@dataclass(frozen=True)
class Entry:
    """Запись базы типов вместе с тем, что про неё надо показать: деталь, устройство, автор."""

    id: int
    part_id: int
    device_id: int
    project_kind: str
    project: str
    device: str
    part_name: str
    kind: str
    type_no: Optional[int]
    description: str
    article: str
    photo_rel: str
    crop_rel: Optional[str]
    author: str
    created_at: str
    archived_at: Optional[str]

    @property
    def label(self):
        return label(self.kind, self.type_no)

    @property
    def archived(self):
        return self.archived_at is not None

    @property
    def pill(self):
        return self.label.upper()

    @property
    def tone(self):
        """Цвет «таблетки» как в макете: тип 1 — зелёный, второй — янтарный, остальные — бирюзовый, дефект — красный."""
        if self.kind == KIND_DEFECT:
            return "defect"
        return {1: "ok", 2: "type2"}.get(self.type_no, "type3")

    @property
    def date_text(self):
        """ГГГГ-ММ-ДД ЧЧ:ММ:СС → ДД.ММ.ГГГГ."""
        day = str(self.created_at)[:10].split("-")
        return ".".join(reversed(day)) if len(day) == 3 else str(self.created_at)


def entry_of(record, part, author):
    """TypeRecord + Part ядра + имя автора → Entry."""
    return Entry(
        record.id, record.part_id, part.device_id, part.kind, part.project, part.device, part.name, record.kind,
        record.type_no, record.description, record.article or part.article or "", record.photo_rel, record.crop_rel,
        author or "", record.created_at, record.archived_at,
    )


def search_text(entry):
    """Всё, по чему ищем: деталь, артикул, устройство, проект, описание и подпись «Тип 2»."""
    return normalize_name(" ".join((entry.part_name, entry.article, entry.device, entry.project, entry.description, entry.label)))


def _words(query):
    """Слова запроса без разделителей; «тип 1» остаётся одним словом, иначе «1» нашлось бы в любом артикуле."""
    words = [normalize_name(word) for word in str(query).split()]
    words = [word for word in words if word]
    merged = []
    for word in words:
        if merged and merged[-1] == _TYPE_WORD and word.isdigit():
            merged[-1] += word
        else:
            merged.append(word)
    return merged


def matches(entry, query):
    """Пустой запрос подходит всему. Регистр, «е/ё» и разделители не важны: «xs 2280» найдёт «XS-2280».

    Подходит, если запрос целиком встречается подряд или каждое его слово встречается где-нибудь.
    """
    words = _words(query)
    if not words:
        return True
    text = search_text(entry)
    return "".join(words) in text or all(word in text for word in words)


def select(entries, query="", project_kind=None, device_id=None):
    """Отбор и порядок: сначала живые, потом архив; внутри — новые первыми."""
    found = [
        entry for entry in entries
        if (project_kind is None or entry.project_kind == project_kind)
        and (device_id is None or entry.device_id == device_id)
        and matches(entry, query)
    ]
    found.sort(key=lambda entry: (entry.created_at, entry.id), reverse=True)
    found.sort(key=lambda entry: entry.archived)  # устойчивая: порядок «новые первыми» внутри групп сохранится
    return found


# --- замечания: отметки фото из «Сравнения» (БД, 04.11.2026) ---------------------------
TAB_TYPES = "types"
TAB_REMARKS = "remarks"
TEXT_REMARK = "Замечание"


@dataclass(frozen=True)
class RemarkEntry:
    """Фото, отмеченное «Замечание» (или старым «Дефектом») в «Сравнении». Хранится в отметке фото, не в таблице types."""

    photo_id: int
    folder_id: int
    part_id: int
    device_id: int
    project_kind: str
    project: str
    device: str
    part_name: str
    article: str
    sn: str
    defect_kind: str
    path: str  # полный путь фото: папка + путь внутри неё
    author: str
    created_at: str  # когда отметили

    archived = False
    kind = "remark"

    @property
    def label(self):
        return TEXT_REMARK

    @property
    def pill(self):
        return TEXT_REMARK.upper()

    @property
    def tone(self):
        return "remark"

    @property
    def date_text(self):
        day = str(self.created_at)[:10].split("-")
        return ".".join(reversed(day)) if len(day) == 3 else str(self.created_at)


def remark_entry_of(marked, part, folder_path, author):
    """MarkedPhoto ядра + Part + путь папки + имя автора → RemarkEntry."""
    path = str(Path(str(folder_path)) / Path(*str(marked.rel_path).split("/")))
    return RemarkEntry(
        marked.photo_id, marked.folder_id, marked.part_id, part.device_id, part.kind, part.project, part.device, part.name,
        part.article or "", marked.sn or "", marked.defect_kind or "", path, author or "", marked.marked_at,
    )


def _remark_search_text(entry):
    return normalize_name(" ".join((entry.part_name, entry.article, entry.device, entry.project, entry.sn,
                                    entry.defect_kind, TEXT_REMARK)))


def is_remark(item):
    """Замечание — отметка фото, а не запись types. По полю, а не по классу: тесты перезагружают модули функций."""
    return getattr(item, "kind", None) == RemarkEntry.kind


def _db_text(item):
    return _remark_search_text(item) if is_remark(item) else search_text(item)


def select_db(entries, remarks, query="", project_kind=None, device_id=None, tab=TAB_TYPES):
    """Выдача вкладки «БД».

    Без запроса — то, что на вкладке: «База типов» (живые, потом архив) или «Замечания» (карточки «дефект» из
    «+ В базу» и отметки фото вместе, новые первыми). С запросом — обе базы сразу, чтобы не искать деталь дважды:
    сначала типы, потом архивные типы, потом замечания по дате.
    """
    words = _words(query)

    def fits(item):
        if project_kind is not None and item.project_kind != project_kind:
            return False
        if device_id is not None and item.device_id != device_id:
            return False
        if not words:
            return True
        text = _db_text(item)
        return "".join(words) in text or all(word in text for word in words)

    types = select([item for item in entries if item.kind == KIND_TYPE and fits(item)])
    problems = [item for item in entries if item.kind != KIND_TYPE and fits(item)] + [item for item in remarks if fits(item)]
    problems.sort(key=lambda item: str(item.created_at), reverse=True)
    if words:
        return types + problems
    return types if tab == TAB_TYPES else problems


def device_summary(entries, device_id):
    """[(деталь, [(подпись, в архиве)])] — все типы устройства: «SSD XS-2280 — Тип 1, Тип 2, Тип 0 (архив)»."""
    parts = {}
    for entry in sorted((item for item in entries if item.device_id == device_id), key=lambda item: (item.part_name.casefold(), item.kind != KIND_TYPE, item.type_no or 0, item.id)):
        parts.setdefault(entry.part_name, []).append((entry.label, entry.archived))
    return list(parts.items())


def short_text(text, limit=110):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
