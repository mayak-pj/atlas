"""Тема: токены → Fusion + палитра + QSS + шрифты в пикселях.

    theme = apply_theme(app, paths)    # один раз при запуске
    theme.color("accent")              # цвета для рисования — только через токены
"""
from __future__ import annotations

import json
import string
from pathlib import Path

_DIR = Path(__file__).resolve().parent
THEMES = {"dark": "tokens.json", "light": "tokens_light.json"}
THEME_TITLES = {"dark": "Тёмная", "light": "Светлая"}
DEFAULT_THEME = "dark"


def tokens_file(name):
    """Файл токенов темы; неизвестное имя — тёмная."""
    return _DIR / THEMES.get(name, THEMES[DEFAULT_THEME])
_current = None


def pick_font(available, wanted):
    """Первый шрифт из wanted, который есть в системе (без учёта регистра), иначе ''."""
    have = {name.lower(): name for name in available}
    for name in wanted:
        if name.lower() in have:
            return have[name.lower()]
    return ""


def render_qss(template, values):
    """Подставляет $имя. Неизвестное имя — ошибка (опечатка в QSS не должна пройти молча)."""
    return string.Template(template).substitute(values)


class Theme:
    def __init__(self, tokens, ui_family="", mono_family=""):
        self.colors = dict(tokens["colors"])
        self.sizes = dict(tokens["sizes"])
        self.font_candidates = tokens["fonts"]
        self.ui_family = ui_family
        self.mono_family = mono_family
        self.qss = ""

    @classmethod
    def load(cls, path=None):
        data = json.loads(Path(path or _DIR / "tokens.json").read_text(encoding="utf-8-sig"))
        return cls(data)

    def color(self, key):
        return self.colors[key]

    def qcolor(self, key):
        from PyQt5.QtGui import QColor

        return QColor(self.colors[key])

    def size(self, key):
        return self.sizes[key]

    def values(self):
        result = {}
        result.update(self.colors)
        result.update(self.sizes)
        result["font_ui"] = '"{}"'.format(self.ui_family or "sans-serif")
        result["font_mono"] = '"{}"'.format(self.mono_family or "monospace")
        return result

    def build_qss(self, template=None):
        if template is None:
            template = (_DIR / "atlas.qss").read_text(encoding="utf-8")
        self.qss = render_qss(template, self.values())
        return self.qss

    def palette(self):
        """Палитра: закрывает то, что QSS не красит (текст в нативных диалогах, подсказки в полях)."""
        from PyQt5.QtGui import QPalette

        palette = QPalette()
        roles = (
            (QPalette.Window, "bg"), (QPalette.WindowText, "text"), (QPalette.Base, "panel"),
            (QPalette.AlternateBase, "bg"), (QPalette.Text, "text"), (QPalette.Button, "panel_2"),
            (QPalette.ButtonText, "text"), (QPalette.BrightText, "on_accent"),
            (QPalette.Highlight, "accent_soft"), (QPalette.HighlightedText, "text"),
            (QPalette.ToolTipBase, "panel_2"), (QPalette.ToolTipText, "text"),
            (QPalette.Link, "link"), (QPalette.Mid, "border"), (QPalette.Dark, "border_strong"),
        )
        for role, key in roles:
            palette.setColor(role, self.qcolor(key))
        palette.setColor(QPalette.PlaceholderText, self.qcolor("muted"))
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            palette.setColor(QPalette.Disabled, role, self.qcolor("disabled"))
        return palette


def apply_theme(app, tokens_path=None, name=None):
    """Нужен созданный QApplication. Шрифт — в пикселях: размер не зависит от системного масштаба. name — "dark" | "light"."""
    from PyQt5.QtGui import QFont, QFontDatabase

    global _current
    theme = Theme.load(tokens_path or (tokens_file(name) if name else None))
    families = QFontDatabase().families()
    theme.ui_family = pick_font(families, theme.font_candidates["ui"])
    theme.mono_family = pick_font(families, theme.font_candidates["mono"])
    app.setStyle("Fusion")
    font = QFont(app.font())
    if theme.ui_family:
        font.setFamily(theme.ui_family)
    font.setPixelSize(int(theme.size("font_md")))
    app.setFont(font)
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.build_qss())
    _current = theme
    return theme


def current():
    """Текущая тема; до apply_theme (например, в тестах) — тема из токенов без QSS."""
    global _current
    if _current is None:
        _current = Theme.load()
    return _current
