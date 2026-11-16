"""Чтение текста на фото (шаг 12.6a): PP-OCRv4 через rapidocr-onnxruntime, без интернета.

Только чтение: что считать маркировкой и как сравнивать — в функции `marking` (12.6b). Без пакетов (rapidocr,
onnxruntime) `engine_available()` — False, остальное программа делает как раньше. Движок грузится при первом чтении,
один раз на процесс; чтение потокобезопасно (один расчёт за раз). Версии и причины — `docs/RESEARCH_MARKING.md`.
"""
from atlas.shared.ocr.reader import (  # noqa: F401
    DEFAULT_SETTINGS,
    OcrUnavailable,
    TextLine,
    engine_available,
    read_text,
    unrotate,
)
