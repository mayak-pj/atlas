"""Без Outlook (macOS и тесты): письмо складывается в файл рядом, ничего не отправляется."""
from __future__ import annotations

from pathlib import Path


def open_mail(subject, html, work_dir, to=""):
    """Возвращает путь к сохранённому письму."""
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    path = Path(work_dir) / "last_mail.html"
    path.write_text("<!-- Тема: {} -->\n{}".format(subject, html), encoding="utf-8")
    return path
