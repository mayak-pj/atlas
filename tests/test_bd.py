"""«БД» (04.11.2026): «База типов» и «Замечания», общий поиск, крестик, вырезка на карточке."""
from pathlib import Path

from atlas.features.type_db import logic
from atlas.features.type_db.screen import TypeDbScreen

from tests.test_type_db_tab import FakeCache, entry
from tests.test_type_db_tab import app  # noqa: F401  (фикстура)
from tests.test_type_db import CardData


def remark(photo_id, created, name="SSD XS-2280", sn="ZZ48256", kind="Сбит элемент", device_id=1, project_kind="A"):
    return logic.RemarkEntry(photo_id, 1, 1, device_id, project_kind, "Орион-24", "N15", name, "512", sn, kind,
                             "/сеть/{}.jpg".format(photo_id), "Петров", created)


ENTRIES = [
    entry(1, created="2026-01-01 10:00:00", type_no=1),
    entry(2, created="2026-03-01 10:00:00", type_no=3, archived="2026-04-01 10:00:00"),
    entry(3, created="2026-02-01 10:00:00", kind="defect", type_no=None, description="скол"),  # карточка «дефект»
]
REMARKS = [remark(10, "2026-05-01 10:00:00"), remark(11, "2026-01-15 10:00:00", name="Плата USB", sn="ZZ48842", kind="")]


def _keys(items):
    return [("r", item.photo_id) if logic.is_remark(item) else ("t", item.id) for item in items]


def test_tabs_without_query_and_both_bases_with_query():
    assert _keys(logic.select_db(ENTRIES, REMARKS)) == [("t", 1), ("t", 2)]  # живые, потом архив
    assert _keys(logic.select_db(ENTRIES, REMARKS, tab=logic.TAB_REMARKS)) == [("r", 10), ("t", 3), ("r", 11)]  # по дате
    # с запросом: типы, архивные типы, потом замечания по дате — сразу из обеих баз
    assert _keys(logic.select_db(ENTRIES, REMARKS, "xs 2280")) == [("t", 1), ("t", 2), ("r", 10), ("t", 3)]
    assert _keys(logic.select_db(ENTRIES, REMARKS, "zz48842")) == [("r", 11)]  # SN замечания
    assert _keys(logic.select_db(ENTRIES, REMARKS, "сбит")) == [("r", 10)]  # вид замечания
    assert _keys(logic.select_db(ENTRIES, REMARKS, "", project_kind="B", tab=logic.TAB_REMARKS)) == []


def _screen(qtbot):
    widget = TypeDbScreen(FakeCache(), Path("/типы"), ("A", "B"))
    qtbot.addWidget(widget)
    widget.resize(1200, 800)
    widget.show()
    widget.set_entries(ENTRIES, REMARKS)
    return widget


def test_screen_opens_types_switches_to_remarks_and_search_hides_tabs(qtbot):
    screen = _screen(qtbot)
    assert screen.tab == logic.TAB_TYPES and screen.visible_ids == [1, 2]
    screen.set_tab(logic.TAB_REMARKS)
    assert _keys(screen.visible) == [("r", 10), ("t", 3), ("r", 11)]
    assert sorted(screen._remark_cards) == [10, 11]
    card = screen._remark_cards[11]
    assert card.description.text() == "Вид не указан" and "ZZ48842" in card.meta.text()
    screen.search.setText("xs-2280")
    assert screen.tabs.isHidden() and not screen.both_note.isHidden()
    assert _keys(screen.visible) == [("t", 1), ("t", 2), ("r", 10), ("t", 3)]
    screen.search.setText("")
    assert not screen.tabs.isHidden() and screen.tab == logic.TAB_REMARKS


def test_type_card_shows_the_crop_and_has_a_cross(qtbot):
    import dataclasses

    screen = TypeDbScreen(FakeCache(), Path("/типы"), ("A", "B"))
    qtbot.addWidget(screen)
    screen.show()
    screen.set_entries([dataclasses.replace(entry(5), crop_rel="x/5_crop.jpg"), entry(6)])
    assert screen._cards[5].thumb._path == str(Path("/типы") / "x/5_crop.jpg")
    assert screen._cards[6].thumb._path == str(Path("/типы") / "x/6_photo.jpg")  # без вырезки — всё фото
    asked = []
    screen.delete_requested.connect(asked.append)
    screen._cards[5].delete_button.click()
    assert asked == [5]


# --- в приложении ---------------------------------------------------------------
def test_remark_from_compare_appears_in_bd(app):  # noqa: F811
    folders = app.ctx.services.get("folders")
    photo = folders.photos(app.folder.id)[1]
    folders.mark_photo(photo.id, "remark", sn="ZZ1", defect_kind="Сбит элемент")
    screen = app.type_db.screen
    screen.set_tab(logic.TAB_REMARKS)
    app.type_db.refresh()
    app.qtbot.waitUntil(lambda: [item.photo_id for item in screen.visible if logic.is_remark(item)] == [photo.id], timeout=5000)
    item = screen.visible[0]
    assert item.sn == "ZZ1" and item.defect_kind == "Сбит элемент" and Path(item.path).name == Path(photo.rel_path).name
    assert Path(item.path).is_file()


def test_cross_deletes_record_and_its_files(app):  # noqa: F811
    app.type_db.add_button.click()
    app.qtbot.waitUntil(lambda: not app.type_db.busy, timeout=5000)
    screen = app.type_db.screen
    app.qtbot.waitUntil(lambda: len(screen.visible_ids) == 1, timeout=5000)
    record = app.type_db.repo.all()[0]
    photo_file = app.type_db.store.root / record.photo_rel
    assert photo_file.is_file()
    events = []
    app.ctx.bus.subscribe("type.deleted", events.append)
    app.type_db.ask_delete = lambda item: False  # передумал
    screen._cards[record.id].delete_button.click()
    assert app.type_db.repo.all() and photo_file.is_file()
    app.type_db.ask_delete = lambda item: True
    screen._cards[record.id].delete_button.click()
    app.qtbot.waitUntil(lambda: screen.visible_ids == [], timeout=5000)
    assert app.type_db.repo.all() == [] and not photo_file.exists()
    assert events == [{"type_id": record.id, "part_id": app.part.id}]
    assert app.type_db.store.delete(record.id) is None  # второй раз — уже нет


def test_card_without_description_is_saved(app):  # noqa: F811
    app.answer = CardData("type", 1, "", "")
    app.type_db.add_button.click()
    app.qtbot.waitUntil(lambda: not app.type_db.busy and bool(app.type_db.repo.all()), timeout=5000)
    assert app.type_db.repo.all()[0].description == ""
