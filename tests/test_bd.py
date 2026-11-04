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


# --- «+ Добавить из файла…» -------------------------------------------------------------
def test_manual_card_is_checked(tmp_path):
    from atlas.features.type_db.manual import ManualCard, ManualError, checked
    from tests.test_type_db import make_jpeg

    photo = make_jpeg(tmp_path / "старое фото.jpg")
    good = ManualCard(str(photo), "A", " Орион ", "", "Плата  USB", "", 2, "", "2026-03-15", 7)
    card = checked(good)
    assert (card.project, card.device, card.part) == ("Орион", "Без устройства", "Плата USB")
    import dataclasses
    for change, text in (({"photo": ""}, "фото"), ({"photo": str(tmp_path / "нет.jpg")}, "Нет такого"),
                         ({"project": " "}, "проект"), ({"part": ""}, "детали"), ({"user_id": None}, "кто добавил")):
        try:
            checked(dataclasses.replace(good, **change))
        except ManualError as exc:
            assert text in str(exc)
        else:
            raise AssertionError(change)


def test_add_from_file_saves_a_type_with_its_date_and_author(app, tmp_path):  # noqa: F811
    from tests.test_type_db import make_jpeg

    users = app.ctx.services.get("users")
    author = users.add("Сидоров", lambda count: "#7DB4FF")
    type_db = app.type_db
    type_db.refresh()
    app.qtbot.waitUntil(lambda: any(name == "Сидоров" for _, name in type_db._users), timeout=5000)
    events = []
    app.ctx.bus.subscribe("type.added", events.append)
    dialog = type_db.open_manual()
    app.qtbot.addWidget(dialog)
    photo = make_jpeg(tmp_path / "архив" / "0402290000836_1_XZ79070.jpg")
    dialog.photo.setText(str(photo))
    dialog.project.setText("Вега")
    dialog.part.setText("Плата дисплея")
    dialog.article.setText("BY22091")
    dialog.number.setValue(3)
    from PyQt5.QtCore import QDate
    dialog.day.setDate(QDate(2026, 3, 15))
    dialog.user.setCurrentIndex(dialog.user.findData(author.id))
    dialog.save_button.click()
    app.qtbot.waitUntil(lambda: "Добавлено" in dialog.status.text(), timeout=5000)
    assert dialog.photo.text() == "" and dialog.part.text() == "Плата дисплея"  # следующее фото той же детали
    (record,) = type_db.repo.all()
    assert (record.type_no, record.created_by, record.source_sn) == (3, author.id, "XZ79070")
    assert record.created_at.startswith("2026-03-15")
    part = app.ctx.services.get("parts").get(record.part_id)
    assert (part.project, part.device, part.name, part.article) == ("Вега", "Без устройства", "Плата дисплея", "BY22091")
    assert (type_db.store.root / record.photo_rel).is_file()
    assert events == [{"type_id": record.id, "part_id": part.id}]
    dialog.save_button.click()  # файл не выбран
    assert "Выберите фото" in dialog.status.text()


def test_portrait_photo_on_card_is_shown_landscape(qtbot):
    from PyQt5.QtGui import QImage
    from atlas.features.type_db.screen import ThumbView

    card = ThumbView(FakeCache(), 240, landscape=True)
    qtbot.addWidget(card)
    portrait = QImage(200, 300, QImage.Format_RGB32)
    card.set_path("/a.jpg")
    card._on_ready("/a.jpg", 1, portrait)
    assert (card._image.width(), card._image.height()) == (300, 200)
    detail = ThumbView(FakeCache(), 240)  # панель справа — как есть
    qtbot.addWidget(detail)
    detail.set_path("/a.jpg")
    detail._on_ready("/a.jpg", 1, portrait)
    assert (detail._image.width(), detail._image.height()) == (200, 300)
