"""Вкладка «База типов» (шаг 4.3): поиск, порядок, фильтры, сетка, карточка справа, чтение из базы."""
from pathlib import Path

import pytest
from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtGui import QImage

from atlas.features.type_db import logic
from atlas.features.type_db.screen import MAX_CARDS, TypeDbScreen
from atlas.shared.viewer.levels import L1
from atlas.shared.viewer.memory_cache import CachedImage

from tests.test_compare_flow import App
from tests.test_type_db import COLORS, CardData, Part, make_jpeg, request


def entry(number, name="SSD XS-2280", description="третий чип", kind="type", type_no=2, device="N15", device_id=1,
          project_kind="A", created="2026-10-14 10:00:00", archived=None, article="512-XS-B", author="Петров", part_id=1):
    return logic.Entry(
        number, part_id, device_id, project_kind, "Орион-24", device, name, kind, type_no, description, article,
        "x/{}_photo.jpg".format(number), None, author, created, archived,
    )


@pytest.fixture(autouse=True)
def _gui(qapp):
    """Шрифты без QApplication роняют Qt: в программе он всегда есть."""


# --- логика ---------------------------------------------------------------------
@pytest.mark.parametrize("query", ["", "ssd", "SSD", "xs 2280", "xs-2280", "XS_2280", "чип", "ТРЕТИЙ", "512-xs", "орион", "n15", "тип 2", "тип2", "чип третий"])
def test_matches_ignores_case_separators_and_word_order(query):
    assert logic.matches(entry(1), query)


@pytest.mark.parametrize("query", ["ssd xs-2280 тип 1", "матплата", "дефект", "zzz"])
def test_does_not_match_foreign_words(query):
    assert not logic.matches(entry(1), query)


def test_yo_and_ye_are_the_same():
    assert logic.matches(entry(1, description="Всё на ёлке"), "все на елке") and logic.matches(entry(1, name="Ёмкость"), "емкость")


def test_search_looks_at_name_article_device_description_only_not_the_author_or_date():
    item = entry(1, author="Соколов", created="2026-10-14 10:00:00")
    assert not logic.matches(item, "Соколов") and not logic.matches(item, "14.10")


def test_archive_goes_to_the_bottom_and_new_first_inside_groups():
    items = [
        entry(1, created="2026-01-01 10:00:00"),
        entry(2, created="2026-03-01 10:00:00", archived="2026-04-01 10:00:00"),
        entry(3, created="2026-02-01 10:00:00"),
        entry(4, created="2026-05-01 10:00:00", archived="2026-06-01 10:00:00"),
    ]
    assert [item.id for item in logic.select(items)] == [3, 1, 4, 2]
    assert [item.id for item in logic.select(items, "ssd")] == [3, 1, 4, 2]  # поиск порядок не ломает


def test_filters_by_kind_and_device():
    items = [entry(1), entry(2, project_kind="B"), entry(3, device_id=2, device="N16")]
    assert [item.id for item in logic.select(items, project_kind="B")] == [2]
    assert sorted(item.id for item in logic.select(items, device_id=1)) == [1, 2]


def test_device_summary_lists_every_part_with_types_and_archive_marks():
    items = [
        entry(1, name="SSD XS-2280", type_no=1), entry(2, name="SSD XS-2280", type_no=2),
        entry(3, name="SSD XS-2280", type_no=0, archived="x"), entry(4, name="Матплата MB-15", type_no=1),
        entry(5, name="Дисплей", device_id=2),
    ]
    assert logic.device_summary(items, 1) == [
        ("SSD XS-2280", [("Тип 0", True), ("Тип 1", False), ("Тип 2", False)]), ("Матплата MB-15", [("Тип 1", False)]),
    ]


def test_entry_display_helpers():
    item = entry(1)
    assert (item.pill, item.tone, item.date_text, item.archived) == ("ТИП 2", "type2", "14.10.2026", False)
    assert entry(1, type_no=1).tone == "ok" and entry(1, kind="defect", type_no=None).tone == "defect"
    assert entry(1, kind="defect", type_no=None).pill == "ДЕФЕКТ"
    assert len(logic.short_text("а" * 300)) == 110 and logic.short_text("  много   пробелов ") == "много пробелов"


# --- экран ----------------------------------------------------------------------
class FakeCache(QObject):
    ready = pyqtSignal(str, int, QImage)
    failed = pyqtSignal(str, int, str)

    def __init__(self):
        super().__init__()
        self.asked = []

    def get(self, path, level, priority=0, exact=False):
        self.asked.append(path)
        return None


@pytest.fixture
def screen(qtbot):
    widget = TypeDbScreen(FakeCache(), Path("/типы"), ("A", "B"))
    qtbot.addWidget(widget)
    widget.resize(1200, 800)
    widget.show()
    return widget


def _fill(screen):
    screen.set_entries([
        entry(1, created="2026-01-01 10:00:00", type_no=1, description="Базовый: два чипа"),
        entry(2, created="2026-03-01 10:00:00", type_no=0, archived="2026-04-01 10:00:00", description="Старая ревизия"),
        entry(3, name="Матплата MB-15", device_id=2, device="N16", project_kind="B", created="2026-02-01 10:00:00",
              description="Другой разъём питания", article="MB15-B-02"),
    ])


def test_empty_database_tells_how_to_add(screen):
    screen.set_entries([])
    assert "В базу типов" in screen.message.text() and screen.visible_ids == [] and screen.found.text() == ""


def test_cards_are_ordered_with_archive_last(screen):
    _fill(screen)
    assert screen.visible_ids == [3, 1, 2] and screen.found.text() == "Найдено: 3"
    assert [screen.grid.itemAt(i).widget().entry.id for i in range(screen.grid.count())] == [3, 1, 2]


def test_typing_filters_at_once_and_nothing_found_is_said(screen, qtbot):
    _fill(screen)
    qtbot.keyClicks(screen.search, "xs 2280")
    assert screen.visible_ids == [1, 2]
    screen.search.setText("разъем")  # ё/е не важны
    assert screen.visible_ids == [3]
    screen.search.setText("zzz")
    assert screen.visible_ids == [] and screen.message.text() == "Ничего не найдено" and screen.found.text() == "Найдено: 0"
    screen.search.setText("")
    assert screen.visible_ids == [3, 1, 2] and screen.message.text() == ""


def test_project_kind_chips(screen):
    _fill(screen)
    screen.kind_buttons["B"].click()
    assert screen.visible_ids == [3] and screen.kind_buttons["B"].isChecked() and not screen.kind_buttons[None].isChecked()
    screen.kind_buttons[None].click()
    assert screen.visible_ids == [3, 1, 2]


def test_click_shows_the_card_on_the_right_and_all_device_types(screen):
    _fill(screen)
    screen.grid.itemAt(1).widget().clicked.emit(1)  # клик по карточке
    assert screen.selected_id == 1 and not screen.detail.body.isHidden()
    detail = screen.detail
    assert detail.title.text() == "SSD XS-2280" and detail.description.text() == "Базовый: два чипа"
    assert detail.article.text() == "512-XS-B" and detail.author.text() == "Петров, 01.01.2026"
    assert detail.device_caption.text() == "Все типы устройства «N15»"
    assert "Тип 0 (архив)" in detail.device_types.text() and "Тип 1" in detail.device_types.text()
    assert "Матплата" not in detail.device_types.text()  # другое устройство


def test_device_chip_limits_to_the_device(screen):
    _fill(screen)
    assert screen.device_button.isHidden()
    screen.select(3)
    assert screen.device_button.text() == "Устройство: N16" and not screen.device_button.isHidden()
    screen.device_button.click()
    assert screen.visible_ids == [3]
    screen.device_button.click()
    assert screen.visible_ids == [3, 1, 2]


def test_selection_survives_refresh_and_goes_when_entry_is_gone(screen):
    _fill(screen)
    screen.select(1)
    screen.set_entries([entry(1, created="2026-01-01 10:00:00", description="новое описание"), entry(9)])
    assert screen.selected_id == 1 and screen.detail.description.text() == "новое описание"
    screen.set_entries([entry(9)])
    assert screen.selected_id is None and not screen.detail.empty.isHidden() and screen.device_button.isHidden()


def test_same_data_does_not_rebuild_cards(screen):
    _fill(screen)
    card = screen.grid.itemAt(0).widget()
    _fill(screen)
    assert screen.grid.itemAt(0).widget() is card


def test_only_first_cards_are_built_for_a_huge_result(screen):
    screen.set_entries([entry(number, created="2026-01-01 10:{:02d}:00".format(number % 60)) for number in range(1, MAX_CARDS + 41)])
    assert screen.grid.count() == MAX_CARDS and screen.found.text() == "Показано {} из {}".format(MAX_CARDS, MAX_CARDS + 40)


def test_grid_columns_follow_the_width(screen, qtbot):
    _fill(screen)
    wide = {screen.grid.getItemPosition(i)[1] for i in range(screen.grid.count())}
    screen.resize(520, 800)
    qtbot.waitUntil(lambda: len({screen.grid.getItemPosition(i)[1] for i in range(screen.grid.count())}) < len(wide), timeout=3000)


def test_photos_are_asked_from_the_cache_for_cards_and_detail(screen):
    _fill(screen)
    screen.select(1)
    asked = screen.detail.photo._cache.asked
    assert any(path.endswith("x/1_photo.jpg") for path in asked) and any(path.endswith("x/3_photo.jpg") for path in asked)


def test_failed_read_keeps_old_cards_and_says_so(screen):
    _fill(screen)
    screen.show_failure()
    assert "прежние" in screen.message.text() and screen.visible_ids == [3, 1, 2]


def test_thumb_shows_image_when_it_arrives_and_no_photo_when_it_fails(qtbot):
    from atlas.features.type_db.screen import ThumbView
    cache = FakeCache()
    thumb = ThumbView(cache, 100)
    qtbot.addWidget(thumb)
    thumb.set_path("/a.jpg")
    image = QImage(40, 60, QImage.Format_RGB32)
    image.fill(Qt.red)
    cache.ready.emit("/a.jpg", L1, image)
    assert thumb.has_image
    thumb.set_path("/b.jpg")
    assert not thumb.has_image
    cache.failed.emit("/b.jpg", L1, "нет файла")
    assert thumb.failed
    cache.ready.emit("/a.jpg", L1, image)  # опоздавший ответ про прежний путь
    assert not thumb.has_image


# --- в приложении ---------------------------------------------------------------
@pytest.fixture
def app(tmp_path, qtbot):
    instance = App(tmp_path, qtbot, count=3, features=("compare", "annotate_tools", "type_db"))
    instance.type_db = next(f.instance for f in instance.registry.loaded if f.spec.id == "type_db")
    instance.answer = CardData("type", 2, "третий чип NAND", "512-XS-B")
    instance.type_db.ask_card = lambda draft: instance.answer
    instance.wait_open()
    yield instance
    instance.stop()


def _add(app):
    app.type_db.add_button.click()
    app.qtbot.waitUntil(lambda: not app.type_db.busy, timeout=5000)


def test_tab_exists_and_shows_a_card_added_from_compare(app):
    screen = app.type_db.screen
    assert "База типов" in app.window.tab_titles()
    app.qtbot.waitUntil(lambda: "В базу типов" in screen.message.text(), timeout=5000)
    _add(app)
    app.qtbot.waitUntil(lambda: len(screen.visible_ids) == 1, timeout=5000)
    card = screen.grid.itemAt(0).widget().entry
    assert (card.part_name, card.label, card.description, card.article) == ("SSD XS-2280", "Тип 2", "третий чип NAND", "512-XS-B")
    assert card.project_kind == "A" and card.project == "Орион-24" and card.device == "N15"
    screen.search.setText("чип nand")
    assert len(screen.visible_ids) == 1
    screen.search.setText("xyz")
    assert screen.visible_ids == []


def test_real_photo_thumbnail_is_loaded_from_the_type_folder(app):
    _add(app)
    screen = app.type_db.screen
    app.qtbot.waitUntil(lambda: len(screen.visible_ids) == 1, timeout=5000)
    thumb = screen.grid.itemAt(0).widget().thumb
    app.qtbot.waitUntil(lambda: thumb.has_image, timeout=5000)


def test_service_searches_and_lists_types_of_a_part(app):
    _add(app)
    app.answer = CardData("defect", None, "скол на разъёме", "")
    app.type_db.ask_card = lambda draft: app.answer
    _add(app)
    service = app.ctx.services.get("type_db")
    found = service.search("скол")
    assert [item.label for item in found] == ["Дефект"]
    assert [item.label for item in service.search("")] == ["Дефект", "Тип 2"]
    assert [(r.kind, r.type_no) for r in service.types_for_part(app.part.id)] == [("type", 2), ("defect", None)]
    assert service.types_for_part(app.part.id + 99) == []


def test_archived_record_is_hidden_from_part_list_but_shown_last_in_search(app):
    _add(app)
    _add(app)
    ids = [item.id for item in app.ctx.services.get("type_db").search("")]
    app.ctx.db.write(lambda conn: conn.execute("UPDATE types SET archived_at = '2026-11-01 10:00:00' WHERE id = ?", (ids[0],)))
    service = app.ctx.services.get("type_db")
    assert [item.id for item in service.search("")] == [ids[1], ids[0]]
    assert [r.id for r in service.types_for_part(app.part.id)] == [ids[1]]
    assert sorted(r.id for r in service.types_for_part(app.part.id, include_archived=True)) == sorted(ids)


def test_unreadable_database_keeps_the_screen_working(app, monkeypatch):
    screen = app.type_db.screen
    monkeypatch.setattr(app.type_db.repo, "all", lambda: (_ for _ in ()).throw(RuntimeError("база занята")))
    app.type_db.refresh()
    app.qtbot.waitUntil(lambda: "прежние" in screen.message.text(), timeout=5000)


def test_opening_the_tab_picks_up_cards_added_by_a_colleague(app, tmp_path):
    screen = app.type_db.screen
    path = make_jpeg(tmp_path / "чужое.jpg")
    app.type_db.store.save(request(path, part=app.part))  # как будто записал другой компьютер: события у нас нет
    assert screen.visible_ids == []
    app.window.select_tab("type_db")
    app.qtbot.waitUntil(lambda: len(screen.visible_ids) == 1, timeout=5000)
