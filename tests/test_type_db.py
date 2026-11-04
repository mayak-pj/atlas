"""Карточка «В базу» (шаг 4.2): логика, картинки, запись на диск и в базу, кнопка в приложении."""
from datetime import datetime
from pathlib import Path

import pytest
from PyQt5.QtGui import QColor, QImage, QPainter

from atlas.features.type_db import logic, render
from atlas.features.type_db.logic import CardData, CardError
from atlas.features.type_db.repo import Repo
from atlas.features.type_db.store import SaveRequest, StoreError, TypeStore
from atlas.shared.annotate.model import Crop, Ellipse, Label

from tests.test_compare_flow import App

GREEN = QColor("#00FF00")
COLORS = {"defect": GREEN, "outline": QColor("#000001"), "crop": QColor("#FFFF00"), "dim": QColor(0, 0, 0, 200)}
BLUE = QColor("#2020E0")
NOW = datetime(2026, 11, 1, 15, 30, 12)


@pytest.fixture(autouse=True)
def _gui(qapp):
    """Шрифты подписи без QApplication роняют Qt: в программе он всегда есть."""


def make_jpeg(path, width=400, height=600):
    """Синее фото с красным квадратом в левом верхнем углу."""
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(BLUE)
    painter = QPainter(image)
    painter.fillRect(0, 0, width // 4, height // 4, QColor("#FF0000"))
    painter.end()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    assert image.save(str(path), "JPG", 95)
    return str(path)


def count(image, color, tolerance=0):
    return sum(
        1 for x in range(image.width()) for y in range(image.height())
        if all(abs(a - b) <= tolerance for a, b in zip(image.pixelColor(x, y).getRgb()[:3], color.getRgb()[:3]))
    )


# --- логика -------------------------------------------------------------------
def test_card_is_checked_and_cleaned():
    card = logic.checked(CardData(logic.KIND_TYPE, 2, "  третий   чип \n NAND ", " 512-XS-B "))
    assert card == CardData("type", 2, "третий чип NAND", "512-XS-B")
    assert logic.checked(CardData("defect", 5, "скол", "")).type_no is None  # у дефекта номера нет
    assert logic.checked(CardData("type", 2, "   ")).description == ""  # без описания можно
    for bad in (CardData("type", None, "x"), CardData("type", 0, "x"), CardData("type", 100, "x"), CardData("?", 1, "x")):
        with pytest.raises(CardError):
            logic.checked(bad)


def test_safe_names_work_on_windows():
    assert logic.safe_name('SSD: XS/2280 "512"?') == "SSD_ XS_2280 _512__"
    assert logic.safe_name("Деталь. ") == "Деталь" and logic.safe_name("   ") == "_"
    assert len(logic.safe_name("а" * 300)) <= 60
    assert logic.relative_dir("A", "Орион-24", "N15", "SSD XS-2280") == "A/Орион-24/N15/SSD XS-2280"


def test_stem_and_numbers():
    assert logic.file_stem("type", 2, NOW, "ab12cd") == "Тип 2_20261101_153012_ab12cd"
    assert logic.file_stem("defect", None, NOW, "ab12cd").startswith("Дефект_")
    assert logic.default_type_no([]) == 1 and logic.default_type_no([1, 3, None]) == 4 and logic.default_type_no([99]) == 99
    # фото уже отмечено «Тип N» — в окне стоит N (замечание 04.11.2026)
    assert logic.default_type_no([1, 3], "type:2") == 2 and logic.default_type_no([], "type:5") == 5
    assert logic.default_type_no([1], "remark") == 2 and logic.default_type_no([1], "type:x") == 2
    assert logic.default_type_no([1], "type:100") == 2


def test_under_folder_ignores_case_and_slashes():
    assert logic.under_folder("C:\\Сеть\\SSD\\Тип 1\\a.jpg", "c:/сеть/ssd")
    assert not logic.under_folder("C:/Сеть/SSD2/a.jpg", "C:/Сеть/SSD")


# --- картинки -------------------------------------------------------------------
def test_photo_gets_shapes_and_crop_is_cut_without_dim(tmp_path):
    path = make_jpeg(tmp_path / "a.jpg")
    shapes = (Ellipse(0.4, 0.4, 0.8, 0.6), Label(0.1, 0.8, "Скол"), Crop(0.5, 0.0, 1.0, 0.5))
    result = render.render(path, shapes, 0, COLORS)
    assert (result.photo.width(), result.photo.height()) == (400, 600) and result.shapes_drawn == 2
    assert count(result.photo, GREEN) > 100
    assert result.photo.pixelColor(300, 100).getRgb()[:3] == pytest.approx(BLUE.getRgb()[:3], abs=12)  # рамка и затемнение не рисуются
    assert (result.crop.width(), result.crop.height()) == (200, 300)


def test_no_crop_shape_means_no_crop_image(tmp_path):
    result = render.render(make_jpeg(tmp_path / "a.jpg"), (Ellipse(0.1, 0.1, 0.5, 0.5),), 0, COLORS)
    assert result.crop is None


def test_rotation_turns_saved_images_like_on_screen(tmp_path):
    path = make_jpeg(tmp_path / "a.jpg")
    result = render.render(path, (Crop(0.0, 0.0, 0.5, 0.5),), 90, COLORS)
    assert (result.photo.width(), result.photo.height()) == (600, 400)
    red = QColor("#FF0000").getRgb()[:3]
    assert result.photo.pixelColor(550, 50).getRgb()[:3] == pytest.approx(red, abs=12)  # красный угол ушёл вправо вверх
    assert (result.crop.width(), result.crop.height()) == (300, 200)


def test_big_photo_is_reduced_to_max_side(tmp_path):
    result = render.render(make_jpeg(tmp_path / "a.jpg"), (), 0, COLORS, max_side=300)
    assert (result.photo.width(), result.photo.height()) == (200, 300)


# --- запись ---------------------------------------------------------------------
class Part:
    id = 7
    kind, project, device, name, article = "A", "Орион-24", "N15", "SSD XS-2280", "512-XS-A"


@pytest.fixture
def db(tmp_path):
    from atlas.core.db import Database, MigrationRunner
    database = Database(str(tmp_path / "t.sqlite"))
    MigrationRunner(database).run("type_db", Path(__file__).resolve().parent.parent / "atlas" / "features" / "type_db" / "migrations")
    return database


def request(path, card=None, shapes=(), part=Part):
    return SaveRequest(part, card or CardData("type", 2, "третий чип", ""), path, 0, shapes, "XZ79070", 3)


def test_save_writes_files_and_row(db, tmp_path):
    root = tmp_path / "Сеть" / "типы"
    store = TypeStore(Repo(db), root, COLORS)
    root.mkdir(parents=True)
    path = make_jpeg(tmp_path / "a.jpg")
    record_id = store.save(request(path, shapes=(Ellipse(0.2, 0.2, 0.6, 0.5), Crop(0.1, 0.1, 0.9, 0.9))), now=NOW, unique="ab12cd")
    record = Repo(db).get(record_id)
    assert record.photo_rel == "A/Орион-24/N15/SSD XS-2280/Тип 2_20261101_153012_ab12cd_photo.jpg"
    assert record.crop_rel.endswith("_crop.jpg")
    assert (root / record.photo_rel).is_file() and (root / record.crop_rel).is_file()
    assert (record.part_id, record.kind, record.type_no, record.description) == (7, "type", 2, "третий чип")
    assert (record.article, record.source_sn, record.created_by, record.source_photo) == ("512-XS-A", "XZ79070", 3, path)
    assert Repo(db).numbers(7) == [2]


def test_without_crop_there_is_no_crop_file_and_defect_has_no_number(db, tmp_path):
    root = tmp_path / "типы"
    root.mkdir()
    store = TypeStore(Repo(db), root, COLORS)
    record = Repo(db).get(store.save(request(make_jpeg(tmp_path / "a.jpg"), CardData("defect", None, "скол", "XY-1")), now=NOW))
    assert record.crop_rel is None and record.type_no is None and record.article == "XY-1"
    assert Repo(db).numbers(7) == []


def test_two_saves_in_one_second_do_not_overwrite_each_other(db, tmp_path):
    root = tmp_path / "типы"
    root.mkdir()
    store = TypeStore(Repo(db), root, COLORS)
    path = make_jpeg(tmp_path / "a.jpg")
    first, second = (Repo(db).get(store.save(request(path), now=NOW)) for _ in range(2))
    assert first.photo_rel != second.photo_rel and len(list(root.rglob("*.jpg"))) == 2


def test_database_failure_removes_written_files(db, tmp_path, monkeypatch):
    root = tmp_path / "типы"
    root.mkdir()
    repo = Repo(db)
    monkeypatch.setattr(repo, "add", lambda *args: (_ for _ in ()).throw(RuntimeError("база занята")))
    store = TypeStore(repo, root, COLORS)
    with pytest.raises(StoreError):
        store.save(request(make_jpeg(tmp_path / "a.jpg"), shapes=(Crop(0.1, 0.1, 0.9, 0.9),)))
    assert list(root.rglob("*.jpg")) == []


def test_unreadable_photo_and_missing_network_folder_are_reported(db, tmp_path):
    root = tmp_path / "типы"
    root.mkdir()
    with pytest.raises(StoreError):
        TypeStore(Repo(db), root, COLORS).save(request(str(tmp_path / "нет.jpg")))
    with pytest.raises(StoreError):  # сетевую папку сами не создаём
        TypeStore(Repo(db), tmp_path / "нет такой", COLORS).save(request(make_jpeg(tmp_path / "a.jpg")))
    assert not (tmp_path / "нет такой").exists()
    local = TypeStore(Repo(db), tmp_path / "своя" / "типы", COLORS, create_root=True)  # локальную относительную — создаём
    local.save(request(make_jpeg(tmp_path / "a.jpg")))
    assert (tmp_path / "своя" / "типы").is_dir()
    with pytest.raises(CardError):
        TypeStore(Repo(db), root, COLORS).save(request(make_jpeg(tmp_path / "a.jpg"), CardData("type", 0, "")))
    assert Repo(db).numbers(7) == [2]


# --- кнопка в приложении -----------------------------------------------------------
@pytest.fixture
def app(tmp_path, qtbot):
    instance = App(tmp_path, qtbot, count=3, features=("compare", "annotate_tools", "type_db"))
    byid = {f.spec.id: f.instance for f in instance.registry.loaded}
    instance.tools, instance.type_db = byid["annotate_tools"], byid["type_db"]
    instance.type_db.asked = []

    def ask(draft):
        instance.type_db.asked.append(draft)
        return instance.answer

    instance.answer = CardData("type", 2, "третий чип", "")
    instance.type_db.ask_card = ask
    instance.root = tmp_path / "Атлас тест" / "var" / "type_db"
    instance.wait_open()
    yield instance
    instance.stop()


def _saved_rows(app):
    return app.ctx.db.read(lambda conn: conn.execute("SELECT id, kind, type_no, photo_rel, crop_rel, source_sn FROM types").fetchall())


def _message(app):
    return app.window.statusBar().currentMessage()


def test_button_saves_current_photo_with_shapes_and_announces_it(app):
    view = app.screen.active_view()
    app.tools.store.add(view.path, Ellipse(0.2, 0.2, 0.6, 0.5))
    app.tools.store.add(view.path, Crop(0.1, 0.1, 0.9, 0.9))
    app.type_db.add_button.click()
    app.qtbot.waitUntil(lambda: bool(_saved_rows(app)), timeout=5000)
    app.qtbot.waitUntil(lambda: not app.type_db.busy, timeout=5000)
    (row,) = _saved_rows(app)
    assert row["kind"] == "type" and row["type_no"] == 2
    assert (app.root / row["photo_rel"]).is_file() and (app.root / row["crop_rel"]).is_file()
    assert "SSD XS-2280" in _message(app) and "Тип 2" in _message(app)
    assert [payload["part_id"] for name, payload in app.events if name == "type.added"] == [app.part.id]
    draft = app.type_db.asked[0]
    assert draft.number == 1 and draft.part.name == "SSD XS-2280" and draft.base[0] == view.path


def test_next_card_offers_next_number(app):
    app.type_db.add_button.click()
    app.qtbot.waitUntil(lambda: not app.type_db.busy and bool(_saved_rows(app)), timeout=5000)
    app.type_db.add_button.click()
    app.qtbot.waitUntil(lambda: len(app.type_db.asked) == 2, timeout=5000)
    assert app.type_db.asked[1].number == 3


def test_cancelled_dialog_saves_nothing_and_frees_the_button(app):
    app.answer = None
    app.type_db.add_button.click()
    app.qtbot.waitUntil(lambda: bool(app.type_db.asked) and not app.type_db.busy, timeout=5000)
    assert _saved_rows(app) == [] and not app.root.exists()


def test_photo_from_another_folder_is_refused(app):
    other = app.ctx.services.get("folders").add(app.part.id, str(app.path.parent / "Другая"), "2026-10-30")
    view = app.screen.active_view()
    view.set_photo(make_jpeg(app.path.parent / "Другая" / "x.jpg"))
    app.qtbot.waitUntil(lambda: view.is_current_shown, timeout=5000)
    app.type_db.start()
    assert "другой папки" in _message(app) and app.type_db.asked == [] and not app.type_db.busy
    assert other is not None


def test_saving_error_is_shown_and_button_stays_usable(app, tmp_path):
    app.type_db.store.root = tmp_path / "нет такой"
    app.type_db.store.create_root = False
    app.type_db.add_button.click()
    app.qtbot.waitUntil(lambda: "недоступна" in _message(app), timeout=5000)
    assert not app.type_db.busy and _saved_rows(app) == []


# --- окно карточки ----------------------------------------------------------------
def test_dialog_saves_without_description_and_defect_has_no_number(qtbot):
    from atlas.features.type_db.dialog import CardDialog
    dialog = CardDialog("A › Орион-24 › N15 › SSD XS-2280", 3, "512-XS-A", "Сохранится фото")
    qtbot.addWidget(dialog)
    assert dialog.number.value() == 3 and dialog.article.text() == "512-XS-A"
    assert dialog.save_button.isEnabled()  # сразу, без описания
    dialog.description.setPlainText("  третий чип ")
    card = dialog.card()  # поля, а не сам объект: другой тест выгружает модули функций, и класс может оказаться новой копией
    assert dialog.save_button.isEnabled()
    assert (card.kind, card.type_no, card.description, card.article) == ("type", 3, "  третий чип ", "512-XS-A")
    dialog.kind.setCurrentIndex(1)
    assert not dialog.number.isEnabled() and dialog.card().kind == "defect" and dialog.card().type_no is None


def test_card_offers_the_type_the_photo_is_marked_with(app):
    """Отметил фото «Тип 2» — в окне карточки уже стоит 2, а не следующий номер детали."""
    screen = app.screen
    screen.mark_buttons["type:2"].click()
    app.qtbot.waitUntil(lambda: screen.model.photos[screen.model.active_index].mark == "type:2", timeout=3000)
    app.type_db.add_button.click()
    app.qtbot.waitUntil(lambda: not app.type_db.busy and bool(app.type_db.asked), timeout=5000)
    assert app.type_db.asked[-1].number == 2



def test_label_on_rotated_photo_is_saved_upright_where_it_was_on_screen(tmp_path):
    """04.11.2026: подпись на повёрнутом фото сохранялась боком и не на своём месте."""
    from atlas.shared.annotate.model import Label, to_screen

    path = make_jpeg(tmp_path / "a.jpg")  # 400×600, вертикальное
    label = Label(0.1, 0.8, "ТИП 2")
    plain = render.render(path, (), 90, COLORS).photo
    marked = render.render(path, (label,), 90, COLORS).photo
    assert (marked.width(), marked.height()) == (600, 400)
    # где подпись на экране: левый верхний угол текста — в точке подписи после поворота
    sx, sy = to_screen(label.x, label.y, 90)
    x0, y0 = int(sx * marked.width()), int(sy * marked.height())
    changed = [(x, y) for x in range(marked.width()) for y in range(0, marked.height(), 2)
               if marked.pixelColor(x, y) != plain.pixelColor(x, y)]
    assert changed
    xs, ys = [x for x, _ in changed], [y for _, y in changed]
    assert min(xs) >= x0 - 4 and min(ys) >= y0 - 4  # текст начинается в своей точке и идёт вправо-вниз от неё
    assert (max(xs) - min(xs)) > (max(ys) - min(ys))  # строка горизонтальна: шире, чем выше
