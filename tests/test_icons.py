"""Значки Lucide: все файлы читаются и рисуются, цвет берётся из темы, лицензия лежит рядом, сборка их включает."""
from pathlib import Path

import pytest
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QPushButton

from atlas.core import theme
from atlas.shared.widgets import icons

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _gui(qapp):
    """Рисование значков без QApplication роняет Qt."""


def test_every_icon_file_renders_something():
    assert len(icons.names()) >= 25
    for name in icons.names():
        image = icons.pixmap(name, "#FF0000").toImage()
        painted = [image.pixelColor(x, y).alpha() for x in range(image.width()) for y in range(image.height())]
        assert max(painted) > 0, name


def test_color_comes_from_theme_and_disabled_differs():
    tokens = theme.current()
    button = QPushButton()
    icons.set_icon(button, "search", "accent")
    normal = button.icon().pixmap(16, 16, QIcon.Normal).toImage()
    off = button.icon().pixmap(16, 16, QIcon.Disabled).toImage()
    reds = lambda image: {image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height()) if image.pixelColor(x, y).alpha() > 200}
    assert tokens.color("accent").lower() in reds(normal)
    assert tokens.color("disabled").lower() in reds(off)
    assert not button.icon().isNull()


def test_checked_icon_has_its_own_color():
    button = QPushButton()
    button.setCheckable(True)
    icons.set_icon(button, "triangle-alert", on="defect")
    on = button.icon().pixmap(16, 16, QIcon.Normal, QIcon.On).toImage()
    solid = {on.pixelColor(x, y).name() for x in range(on.width()) for y in range(on.height()) if on.pixelColor(x, y).alpha() > 200}
    assert theme.current().color("defect").lower() in solid


def test_unknown_icon_is_an_error():
    with pytest.raises(KeyError):
        icons.svg_text("нет-такого", "#000000")


def test_license_is_next_to_icons_and_shipped():
    assert "ISC License" in (icons.ICON_DIR / "LICENSE.txt").read_text(encoding="utf-8")
    import sys
    sys.path.insert(0, str(REPO / "packaging"))
    from bundle_contents import data_files

    shipped = {Path(src).name for src, _dest in data_files(str(REPO))}
    assert "LICENSE.txt" in shipped and "search.svg" in shipped
