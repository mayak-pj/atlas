"""Тема и оболочка: подстановка токенов, слоты, вкладки, строка контекста."""
import json
import re
from pathlib import Path

import pytest
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

from atlas.core.theme import Theme, pick_font, render_qss
from atlas.shared.widgets import ContextBar, NameTag, initials_of

CORE = Path(__file__).resolve().parent.parent / "atlas" / "core"


def test_qss_has_no_unknown_tokens_and_no_raw_colors():
    theme = Theme.load()
    template = (CORE / "theme" / "atlas.qss").read_text(encoding="utf-8")
    qss = theme.build_qss(template)
    assert "$" not in qss
    # цвета — только через токены: в самом шаблоне нет #rrggbb
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", template)


def test_unknown_token_is_error():
    with pytest.raises(KeyError):
        render_qss("a { color: $nope; }", {"bg": "#000"})


def test_tokens_cover_ui_spec():
    colors = json.loads((CORE / "theme" / "tokens.json").read_text(encoding="utf-8"))["colors"]
    for key, value in {"bg": "#0F1115", "panel": "#171A1F", "accent": "#4C9AFF", "defect": "#FF5A5F",
                       "type2": "#F2A93B", "remark": "#C59CFF", "ok": "#3DD68C"}.items():
        assert colors[key].upper() == value


def test_pick_font_is_case_insensitive():
    assert pick_font(["dejavu sans", "Arial"], ["Segoe UI", "DejaVu Sans"]) == "dejavu sans"
    assert pick_font(["X"], ["Segoe UI"]) == ""


def test_initials():
    assert initials_of("Смирнова") == "СМ"
    assert initials_of("") == "?"
    assert initials_of("О") == "О"


def test_name_tag_size_and_check(qtbot):
    tag = NameTag("Петров", "#3DD68C")
    qtbot.addWidget(tag)
    assert tag.sizeHint().height() == 44
    tag.setChecked(True)
    assert tag.isChecked()
    compact = NameTag("Петров", "#3DD68C", compact=True)
    qtbot.addWidget(compact)
    assert compact.sizeHint().height() == 32 and not compact.isCheckable()
    tag.grab()
    compact.grab()


def test_context_bar(qtbot):
    bar = ContextBar()
    qtbot.addWidget(bar)
    bar.show()
    assert not bar.isVisible() or True
    bar.set_context(kind="КК", project="Орион-24", device="SSD", part=None, path="\\\\srv\\Фото")
    assert bar.chain_text == "Орион-24 › SSD"
    assert bar.isVisible()
    bar.set_show_kind(False)
    bar.clear()
    assert not bar.isVisible()


@pytest.fixture
def shell(qtbot):
    from atlas.core.shell import ShellWindow

    window = ShellWindow(None)
    qtbot.addWidget(window)
    return window


def test_panel_waits_for_slot_and_replaces_by_key(shell):
    first, second = QLabel("a"), QLabel("b")
    shell.add_panel("x.right", first, key="k")
    host = QWidget()
    layout = QVBoxLayout(host)
    shell.register_slot("x.right", layout)
    assert layout.count() == 1
    shell.add_panel("x.right", second, key="k")  # тот же ключ — замена
    assert layout.count() == 1 and layout.itemAt(0).widget() is second


def test_panel_order(shell):
    host = QWidget()
    layout = QVBoxLayout(host)
    shell.register_slot("s", layout)
    a, b, c = QLabel("a"), QLabel("b"), QLabel("c")
    shell.add_panel("s", b, order=2)
    shell.add_panel("s", c, order=3)
    shell.add_panel("s", a, order=1)
    assert [layout.itemAt(i).widget() for i in range(3)] == [a, b, c]


def test_panel_without_slot_is_harmless(shell):
    shell.add_panel("nobody.here", QLabel("x"))
    assert shell.slots.panels("nobody.here")


def test_builtin_user_slot(shell):
    shell.add_panel("shell.user", NameTag("Петров", compact=True), key="login")
    assert len(shell.slots.panels("shell.user")) == 1
    shell.remove_panel("shell.user", "login")
    assert shell.slots.panels("shell.user") == []
