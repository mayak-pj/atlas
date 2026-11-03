"""defect_kinds (03.11.2026): общий список видов замечаний в базе, правка в программе."""
import pytest
from PyQt5.QtWidgets import QMessageBox

from atlas.features.defect_kinds import logic
from atlas.features.defect_kinds.logic import KindError

from tests.test_compare_flow import App

SEED = ["Сбит / повреждён элемент", "Размытое фото", "Прислано не то фото"]  # data/defect_kinds.json


def test_clean_key_and_seed(tmp_path):
    assert logic.clean("  Сбит   элемент ") == "Сбит элемент"
    assert logic.key("Ёлка  Сбита") == logic.key("елка сбита")
    with pytest.raises(KindError):
        logic.clean("   ")
    with pytest.raises(KindError):
        logic.clean("а" * 81)
    (tmp_path / "defect_kinds.json").write_text('{"kinds": ["Один", " один ", "", "Два"]}', encoding="utf-8")
    assert logic.seed_names(tmp_path) == ["Один", "Два"]
    assert logic.seed_names(tmp_path / "нет") == []


@pytest.fixture
def app(tmp_path, qtbot):
    instance = App(tmp_path, qtbot, names=["1_1_A.jpg", "1_1_B.jpg"], count=2, features=("defect_kinds", "compare"))
    instance.wait_open()
    instance.kinds = instance.ctx.services.get("defect_kinds")
    qtbot.waitUntil(lambda: _combo(instance) == SEED, timeout=5000)
    yield instance
    instance.stop()


def _combo(app):
    box = app.screen.kind_box
    return [box.itemData(index) for index in range(1, box.count())]


def _remark(app, kind):
    folders = app.ctx.services.get("folders")
    photo = folders.photos(app.folder.id)[0]
    folders.mark_photo(photo.id, "remark", defect_kind=kind)
    return photo.id


def test_list_is_seeded_once_and_removed_kind_does_not_come_back(app):
    assert app.kinds.names() == SEED
    for name in SEED:
        app.kinds.remove(name)
    assert app.kinds.names() == []  # пусто, но не заполняется заново: таблица не пустая


def test_add_refuses_duplicates_regardless_of_case_and_yo(app, qtbot):
    app.kinds.add("Невозможно прочитать модель")
    with pytest.raises(KindError, match="уже есть"):
        app.kinds.add("  невозможно   прочитать модель ")
    qtbot.waitUntil(lambda: _combo(app)[-1] == "Невозможно прочитать модель", timeout=3000)
    app.kinds.remove("Размытое фото")
    app.kinds.add("размытое фото")  # удалённый можно завести снова
    assert app.kinds.names()[-1] == "размытое фото"


def test_rename_fixes_existing_remarks_and_remove_keeps_them(app, qtbot):
    photo_id = _remark(app, "Размытое фото")
    assert app.kinds.rename("Размытое фото", "Фото размыто") == 1
    folders = app.ctx.services.get("folders")
    kind = lambda: next(p.defect_kind for p in folders.photos(app.folder.id) if p.id == photo_id)  # noqa: E731
    assert kind() == "Фото размыто"
    qtbot.waitUntil(lambda: "Фото размыто" in _combo(app), timeout=3000)
    app.kinds.remove("Фото размыто")
    assert kind() == "Фото размыто"  # старая отметка не тронута
    with pytest.raises(KindError, match="уже нет"):
        app.kinds.rename("Фото размыто", "Другое")
    with pytest.raises(KindError, match="уже есть"):
        app.kinds.rename("Прислано не то фото", "сбит / повреждён элемент")


def test_removed_kind_still_shown_on_old_remark(app, qtbot):
    screen = app.screen
    screen.mark_buttons["remark"].click()
    qtbot.waitUntil(lambda: screen.defect_box.isVisible(), timeout=3000)
    screen.kind_box.setCurrentIndex(screen.kind_box.findData("Размытое фото"))
    screen._on_defect_edited()
    qtbot.waitUntil(lambda: screen.model.photos[screen.model.active_index].defect_kind == "Размытое фото", timeout=3000)
    app.kinds.remove("Размытое фото")
    qtbot.waitUntil(lambda: "Размытое фото" not in _combo(app)[:2], timeout=3000)
    assert screen.kind_box.currentData() == "Размытое фото"


def test_edit_button_only_with_feature(app, tmp_path, qtbot):
    assert not app.screen.kinds_button.isHidden()
    other = App(tmp_path / "без", qtbot, count=1)
    try:
        assert other.screen.kinds_button.isHidden()
        assert [other.screen.kind_box.itemData(i) for i in range(1, other.screen.kind_box.count())] == SEED  # из файла
    finally:
        other.stop()


def test_dialog_adds_renames_and_removes(app, qtbot, monkeypatch):
    from atlas.features.defect_kinds.dialog import KindsDialog

    dialog = KindsDialog(app.kinds)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.list.count() == 3, timeout=3000)
    dialog.edit.setText("Неверный артикул")
    dialog.add_button.click()
    qtbot.waitUntil(lambda: dialog.list.count() == 4, timeout=3000)
    assert dialog.selected() == "Неверный артикул" and "Добавлено" in dialog.status.text()
    dialog.edit.setText("Неверный артикул на стикере")
    dialog.rename_button.click()
    qtbot.waitUntil(lambda: dialog.selected() == "Неверный артикул на стикере", timeout=3000)
    assert "Исправлено" in dialog.status.text()
    dialog.edit.setText("размытое фото")
    dialog.add_button.click()
    qtbot.waitUntil(lambda: "уже есть" in dialog.status.text(), timeout=3000)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    dialog.list.setCurrentRow(0)
    dialog.remove_button.click()
    qtbot.waitUntil(lambda: dialog.list.count() == 3, timeout=3000)
    assert app.kinds.names()[0] == "Размытое фото"
    qtbot.waitUntil(lambda: "Неверный артикул на стикере" in _combo(app), timeout=3000)
    dialog.wait_idle()
