"""Архив базы типов (шаг 4.4): кадры анимации, печать, серый вид, запись в базу, события, экран."""
import pytest
from PyQt5.QtCore import QRectF
from PyQt5.QtGui import QColor, QImage, QPainter

from atlas.features.type_db.repo import Repo
from atlas.shared.widgets import stamp

from tests.test_compare_flow import App
from tests.test_type_db import Part, make_jpeg
from tests.test_type_db_tab import FakeCache, _fill, entry, screen  # noqa: F401  (screen — фикстура)
from tests.test_type_db import CardData

GREEN = QColor("#20C040")
RED = QColor("#FF5A5F")


@pytest.fixture(autouse=True)
def _gui(qapp):
    """Шрифты печати без QApplication роняют Qt: в программе он всегда есть."""


# --- кадры анимации ---------------------------------------------------------------
def test_archive_frames_follow_the_mockup_timeline():
    start = stamp.frame_at(0)
    assert (start.gray, start.has_stamp, start.thud) == (0.0, False, 0.0)
    assert stamp.frame_at(450).gray == pytest.approx(0.5) and not stamp.frame_at(450).has_stamp  # серость идёт, печати ещё нет
    early = stamp.frame_at(500)
    assert early.has_stamp and early.stamp_scale > 2.0 and early.stamp_rotation < -20  # печать только начала падать
    hit = stamp.frame_at(450 + 0.7 * 550)
    assert hit.stamp_opacity == pytest.approx(1.0) and hit.stamp_scale == pytest.approx(0.9) and hit.stamp_rotation == pytest.approx(-12)
    assert stamp.frame_at(900).gray == 1.0 and stamp.frame_at(1000).stamp_scale == pytest.approx(1.0)
    assert stamp.frame_at(1100).thud == pytest.approx(3.0)  # «удар» карточки
    assert stamp.frame_at(stamp.ARCHIVE_TOTAL_MS) == stamp.ARCHIVED
    assert stamp.frame_at(99999) == stamp.ARCHIVED


def test_gray_never_goes_back_while_archiving_and_never_forward_while_restoring():
    archiving = [stamp.frame_at(ms).gray for ms in range(0, 1300, 25)]
    restoring = [stamp.frame_at(ms, restoring=True).gray for ms in range(0, 1000, 25)]
    assert archiving == sorted(archiving) and restoring == sorted(restoring, reverse=True)
    assert restoring[0] == 1.0 and restoring[-1] == 0.0


def test_restore_returns_to_color_and_removes_the_stamp():
    assert not stamp.frame_at(300, restoring=True).has_stamp and stamp.frame_at(300, restoring=True).gray > 0
    end = stamp.frame_at(stamp.RESTORE_TOTAL_MS, restoring=True)
    assert end.gray == 0.0 and not end.has_stamp
    assert stamp.final_frame(True) == stamp.ARCHIVED and stamp.final_frame(False) == stamp.COLOR


def test_total_durations():
    assert stamp.total_ms(False) == 1250 and stamp.total_ms(True) == 900


# --- печать на картинке -------------------------------------------------------------
def _canvas(width=400, height=150):
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor("#101010"))
    return image


def _reddish(image):
    return sum(1 for x in range(image.width()) for y in range(image.height()) if image.pixelColor(x, y).red() > 150 and image.pixelColor(x, y).green() < 120)


def test_stamp_is_drawn_only_when_it_has_opacity():
    image = _canvas()
    painter = QPainter(image)
    stamp.paint_stamp(painter, QRectF(image.rect()), stamp.COLOR, RED)
    painter.end()
    assert _reddish(image) == 0
    painter = QPainter(image)
    stamp.paint_stamp(painter, QRectF(image.rect()), stamp.ARCHIVED, RED)
    painter.end()
    assert _reddish(image) > 200


def test_stamp_grows_with_the_image_height():
    small, big = _canvas(300, 150), _canvas(600, 300)
    for image in (small, big):
        painter = QPainter(image)
        stamp.paint_stamp(painter, QRectF(image.rect()), stamp.ARCHIVED, RED)
        painter.end()
    assert _reddish(big) > _reddish(small) * 2


# --- серый вид картинки ---------------------------------------------------------------
def test_thumb_goes_gray_and_back(qtbot):
    from atlas.features.type_db.screen import ThumbView
    cache = FakeCache()
    thumb = ThumbView(cache, 150)
    qtbot.addWidget(thumb)
    thumb.resize(300, 150)
    thumb.show()
    thumb.set_path("/a.jpg")
    image = QImage(60, 40, QImage.Format_RGB32)
    image.fill(GREEN)
    cache.ready.emit("/a.jpg", 1, image)

    def center():
        pixel = thumb.grab().toImage().pixelColor(48, 75)  # левее печати
        return pixel.red(), pixel.green(), pixel.blue()

    red, green, blue = center()
    assert green > red + 60  # в цвете
    thumb.show_frame(stamp.frame_at(900))
    red, green, blue = center()
    assert max(red, green, blue) - min(red, green, blue) < 12 and green < 140  # серое и темнее
    thumb.show_frame(stamp.COLOR)
    red, green, blue = center()
    assert green > red + 60


# --- запись -----------------------------------------------------------------------------
@pytest.fixture
def repo(tmp_path):
    from pathlib import Path
    from atlas.core.db import Database, MigrationRunner
    database = Database(str(tmp_path / "t.sqlite"))
    MigrationRunner(database).run("type_db", Path(__file__).resolve().parent.parent / "atlas" / "features" / "type_db" / "migrations")
    repository = Repo(database)
    repository.type_id = repository.add(7, "type", 2, "чип", "A", "a_photo.jpg", None, None, None, 1)
    return repository


def test_archive_and_restore_in_the_database(repo):
    part_id, stamp_text = repo.set_archived(repo.type_id, True, user_id=5)
    record = repo.get(repo.type_id)
    assert part_id == 7 and record.archived_at == stamp_text and record.archived_by == 5
    assert repo.set_archived(repo.type_id, True, user_id=9) == (7, stamp_text)  # повтор: время и автор прежние
    assert repo.get(repo.type_id).archived_by == 5
    assert repo.set_archived(repo.type_id, False) == (7, None)
    record = repo.get(repo.type_id)
    assert record.archived_at is None and record.archived_by is None
    assert repo.set_archived(999, True) is None


def test_archived_is_not_offered_as_reference(repo):
    repo.set_archived(repo.type_id, True)
    assert repo.for_part(7) == [] and len(repo.for_part(7, include_archived=True)) == 1
    assert repo.numbers(7) == [2]  # номер занят: новый тип не получит номер архивного


# --- экран ------------------------------------------------------------------------------
def _cards(screen):
    return [screen.grid.itemAt(i).widget() for i in range(screen.grid.count())]


def _card(screen, entry_id):
    return next(card for card in _cards(screen) if card.entry.id == entry_id)


def test_button_asks_to_archive_and_blocks_second_click(screen, qtbot):  # noqa: F811
    _fill(screen)
    asked = []
    screen.archive_toggled.connect(lambda number, flag: asked.append((number, flag)))
    card = _card(screen, 1)
    assert card.archive_button.text() == "В архив"
    card.archive_button.click()
    assert asked == [(1, True)] and not card.archive_button.isEnabled()
    assert _card(screen, 2).archive_button.text() == "Вернуть из архива"
    screen.archive_failed(1)
    assert card.archive_button.isEnabled()
    _card(screen, 2).archive_button.click()
    assert asked[-1] == (2, False)


def test_archive_plays_animation_then_card_goes_to_the_bottom(screen, qtbot):  # noqa: F811
    _fill(screen)  # порядок: 3, 1, 2(архив)
    card = _card(screen, 3)
    screen.apply_archive(3, True, "2026-11-01 12:00:00")
    assert card.animating and screen.visible_ids == [3, 1, 2]  # пока играет, на месте
    assert _card(screen, 3) is card
    qtbot.waitUntil(lambda: not screen._animating, timeout=5000)
    assert screen.visible_ids == [1, 2, 3] and screen._entry(3).archived  # архив внизу: новый архивный выше старого по дате
    new_card = _card(screen, 3)
    assert new_card.archive_button.text() == "Вернуть из архива" and new_card.thumb.frame == stamp.ARCHIVED


def test_restore_plays_back_to_color(screen, qtbot):  # noqa: F811
    _fill(screen)
    card = _card(screen, 2)
    assert card.thumb.frame == stamp.ARCHIVED
    screen.apply_archive(2, False, None)
    assert card.animating
    qtbot.waitUntil(lambda: not screen._animating, timeout=5000)
    assert not screen._entry(2).archived and _card(screen, 2).thumb.frame == stamp.COLOR
    assert screen.visible_ids == [2, 3, 1]  # вернулась на своё место среди живых: по дате она самая новая


def test_fresh_data_during_animation_waits_for_its_end(screen, qtbot):  # noqa: F811
    _fill(screen)
    card = _card(screen, 3)
    screen.apply_archive(3, True, "2026-11-01 12:00:00")
    screen.set_entries([entry(3, name="Матплата MB-15 rev.B", device_id=2, device="N16", project_kind="B", created="2026-02-01 10:00:00",
                              archived="2026-11-01 12:00:00"), entry(7, created="2026-11-01 09:00:00")])
    assert _card(screen, 3) is card and card.animating  # анимацию не оборвали
    qtbot.waitUntil(lambda: not screen._animating, timeout=5000)
    assert 7 in screen.visible_ids and 1 not in screen.visible_ids  # данные применились после анимации


def test_without_animations_the_card_moves_at_once(qtbot):
    from pathlib import Path
    from atlas.features.type_db.screen import TypeDbScreen
    widget = TypeDbScreen(FakeCache(), Path("/t"), ("A", "B"), animations=False)
    qtbot.addWidget(widget)
    widget.resize(1200, 800)
    widget.show()
    _fill(widget)
    widget.apply_archive(3, True, "2026-11-01 12:00:00")
    assert widget.visible_ids == [1, 2, 3]  # архивные внизу, среди них новые первыми
    assert widget._entry(3).archived and not widget._animating
    assert _card(widget, 3).thumb.frame == stamp.ARCHIVED


def test_detail_panel_shows_archived_status(screen):  # noqa: F811
    _fill(screen)
    screen.select(2)
    assert screen.detail.status.text() == "В архиве" and screen.detail.photo.frame == stamp.ARCHIVED
    screen.select(1)
    assert screen.detail.status.text() == "Действует" and screen.detail.photo.frame == stamp.COLOR


# --- в приложении -------------------------------------------------------------------------
@pytest.fixture
def app(tmp_path, qtbot):
    instance = App(tmp_path, qtbot, count=3, features=("compare", "annotate_tools", "type_db"))
    instance.type_db = next(f.instance for f in instance.registry.loaded if f.spec.id == "type_db")
    instance.answer = CardData("type", 1, "базовый", "")
    instance.type_db.ask_card = lambda draft: instance.answer
    instance.wait_open()
    for number, text in ((1, "базовый"), (2, "третий чип")):
        instance.answer = CardData("type", number, text, "")
        instance.type_db.add_button.click()
        instance.qtbot.waitUntil(lambda: not instance.type_db.busy, timeout=5000)
    instance.qtbot.waitUntil(lambda: len(instance.type_db.screen.visible_ids) == 2, timeout=5000)
    yield instance
    instance.stop()


def _rows(app):
    return app.ctx.db.read(lambda conn: conn.execute("SELECT id, archived_at, archived_by FROM types ORDER BY id").fetchall())


def test_archive_button_writes_database_publishes_event_and_reorders(app):
    screen = app.type_db.screen
    first, second = sorted(screen.visible_ids)  # номера по порядку добавления
    assert screen.visible_ids[0] == second  # новая первой
    _card(screen, second).archive_button.click()
    app.qtbot.waitUntil(lambda: _rows(app)[1]["archived_at"] is not None, timeout=5000)
    archived = lambda: [payload["type_id"] for name, payload in app.events if name == "type.archived"]  # noqa: E731
    app.qtbot.waitUntil(lambda: archived() == [second], timeout=5000)  # событие приходит через очередь Qt, позже записи в базу
    app.qtbot.waitUntil(lambda: not screen._animating and screen.visible_ids == [first, second], timeout=5000)
    service = app.ctx.services.get("type_db")
    assert [r.id for r in service.types_for_part(app.part.id)] == [first]  # архивное эталоном не служит
    assert [item.id for item in service.search("", include_archived=False)] == [first]
    assert [item.id for item in service.search("")] == [first, second]
    _card(screen, second).archive_button.click()  # «Вернуть из архива»
    app.qtbot.waitUntil(lambda: _rows(app)[1]["archived_at"] is None, timeout=5000)
    app.qtbot.waitUntil(lambda: not screen._animating and screen.visible_ids == [second, first], timeout=5000)
    assert [payload["type_id"] for name, payload in app.events if name == "type.restored"] == [second]


def test_archive_failure_is_shown_and_card_stays(app, monkeypatch):
    screen = app.type_db.screen
    target = screen.visible_ids[0]
    monkeypatch.setattr(app.type_db.repo, "set_archived", lambda *args: (_ for _ in ()).throw(RuntimeError("база занята")))
    card = _card(screen, target)
    card.archive_button.click()
    app.qtbot.waitUntil(lambda: "изменить архив" in app.window.statusBar().currentMessage(), timeout=5000)
    assert card.archive_button.isEnabled() and not screen._entry(target).archived and not screen._animating
    assert [r["archived_at"] for r in _rows(app)] == [None, None]
