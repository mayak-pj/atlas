"""rules (7.1): логика, запись с фото, «прочитано» на пользователя, вкладка и панель к детали."""
import json
import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt5.QtGui import QColor, QImage

from atlas.app import build_core, build_window, start_features
from atlas.core.config import AppPaths
from atlas.features.rules import logic

REPO = Path(__file__).resolve().parent.parent
PART = SimpleNamespace(id=5, name="SSD XS-2280", name_key="ssdxs2280", kind="A", project="Орион", project_id=1, device="N15", device_id=2)
OTHER = SimpleNamespace(id=9, name="Плата", name_key="плата", kind="B", project="Лира", project_id=7, device="P1", device_id=8)


def rule(scope, **kw):
    base = dict(id=1, scope=scope, kind=None, project_id=None, device_id=None, part_id=None, name_key=None,
                scope_label="", title="t", body="", author_id=1, created_at="2026-10-14 08:51:00")
    base.update(kw)
    return logic.Rule(**base)


# --- логика ---------------------------------------------------------------------------------
def test_draft_needs_title_and_open_part_for_narrow_scope():
    with pytest.raises(logic.RuleError):
        logic.checked(logic.draft_for("general", None, "  ", ""))
    with pytest.raises(logic.RuleError):
        logic.checked(logic.Draft("part", "Что-то", ""))  # область «деталь» без детали
    assert logic.draft_for("part", None, "t", "").scope == "general"  # без открытой детали область — общая
    assert logic.checked(logic.draft_for("part", PART, "  Что   проверять ", " текст ")).title == "Что проверять"


def test_draft_takes_scope_from_part():
    draft = logic.draft_for("device", PART, "t", "")
    assert (draft.kind, draft.project_id, draft.device_id, draft.part_id) == ("A", 1, 2, None)
    assert draft.scope_label == "A · Орион · N15"
    assert logic.draft_for("part", PART, "t", "").name_key == "ssdxs2280"


def test_rules_for_part_skip_general_and_foreign():
    rules = [rule("general"), rule("kind", kind="A"), rule("kind", kind="B"), rule("project", project_id=1),
             rule("device", device_id=8), rule("part", name_key="ssdxs2280"), rule("part", name_key="плата")]
    assert [(r.scope, r.kind or r.project_id or r.device_id or r.name_key) for r in logic.for_part(rules, PART)] == [
        ("kind", "A"), ("project", 1), ("part", "ssdxs2280")]
    assert logic.for_part(rules, OTHER)[0].kind == "B"


def test_filters():
    rules = [rule("general"), rule("kind", kind="A"), rule("part", kind="B", name_key="x")]
    assert len(logic.filtered(rules, "all")) == 3
    assert [r.scope for r in logic.filtered(rules, "general")] == ["general"]
    assert [r.scope for r in logic.filtered(rules, "part")] == ["part"]
    assert [r.scope for r in logic.filtered(rules, "kind:A")] == ["kind"]


def test_short_date():
    today = datetime(2026, 11, 2, 12, 0)
    assert logic.short_date("2026-11-02 08:51:00", today) == "сегодня 08:51"
    assert logic.short_date("2026-11-01 23:00:00", today) == "вчера"
    assert logic.short_date("2026-10-12 10:00:00", today) == "12.10"
    assert logic.short_date("2025-10-12 10:00:00", today) == "12.10.2025"


# --- в приложении -------------------------------------------------------------------------------
class App:
    def __init__(self, tmp_path, qtbot, features=("compare", "rules")):
        root = tmp_path / "Атлас"
        (root / "config").mkdir(parents=True)
        shutil.copy(str(REPO / "config" / "app.json"), str(root / "config" / "app.json"))
        (root / "config" / "features.json").write_text(
            json.dumps({"features": [{"id": name} for name in features]}), encoding="utf-8")
        local = {"image_cache": {"disk_dir": str(tmp_path / "кэш")}, "rules": {"dir": str(tmp_path / "правила")}}
        (root / "config" / "local.json").write_text(json.dumps(local), encoding="utf-8")
        (tmp_path / "правила").mkdir()
        self.ctx = build_core(AppPaths(root))
        self.qtbot, self.tmp = qtbot, tmp_path
        self.svc = self.ctx.services
        self.registry = start_features(self.ctx)
        assert self.registry.failures == []
        self.window = build_window(self.registry)
        qtbot.addWidget(self.window)
        self.window.show()
        self.petrov = self.svc.get("users").add("Петров", lambda count: "#7DB4FF")
        self.ivanova = self.svc.get("users").add("Иванова", lambda count: "#F2A93B")
        self.ctx.user = self.petrov
        self.rules = next(item.instance for item in self.registry.loaded if item.spec.id == "rules")

    def wait_idle(self):
        self.qtbot.waitUntil(lambda: not self.rules._busy_read and not self.rules._again
                             and not any(t.is_alive() for t in self.rules._threads), timeout=4000)

    def folder(self, name="SSD XS-2280"):
        part = self.svc.get("parts").ensure("A", "Орион", "N15", name)
        folder = self.svc.get("folders").add(part.id, str(self.tmp / "Сеть" / name / "2026-10-01"), "2026-10-01")
        return part, folder

    def open(self, part, folder):
        self.ctx.bus.publish("folder.opened", {"folder_id": folder.id, "part_id": part.id})
        self.wait_idle()

    def publish(self, draft):
        self.rules.publish(draft)
        self.qtbot.waitUntil(lambda: self.rules.screen.publish_button.isEnabled() and not self.rules._busy_read
                             and not any(t.is_alive() for t in self.rules._threads), timeout=5000)

    def stop(self):
        self.registry.stop_all()


@pytest.fixture
def app(tmp_path, qtbot):
    result = App(tmp_path, qtbot)
    yield result
    result.stop()


def photo(path):
    image = QImage(3000, 2000, QImage.Format_RGB32)
    image.fill(QColor("red"))
    assert image.save(str(path), "JPEG")
    return str(path)


def test_publish_with_photo_is_read_by_author_and_new_for_others(app):
    part, folder = app.folder()
    app.open(part, folder)
    source = photo(app.tmp / "снимок телефона.jpg")
    draft = logic.draft_for("part", app.rules.part, "Площадку проверять всегда", "С 14.10 идёт Тип 2", [source])
    events = []
    app.ctx.bus.subscribe("rule.published", events.append)
    app.publish(draft)
    rules = app.rules.repo.all(app.petrov.id)
    assert len(rules) == 1 and rules[0].read and len(rules[0].photos) == 1
    rel = rules[0].photos[0]
    big, thumb = app.tmp / "правила" / rel, app.tmp / "правила" / logic.thumb_rel(rel)
    assert QImage(str(big)).width() == 1600 and 0 < QImage(str(thumb)).width() <= 640
    assert app.rules.repo.all(app.ivanova.id)[0].read is False
    assert app.rules.unread_count(app.ivanova.id) == 1 and app.rules.unread_count(app.petrov.id) == 0
    qt_events = [e for e in events if e.get("rule_id")]
    assert qt_events and qt_events[0]["part_id"] == part.id


def test_badge_panel_and_read_marks_follow_user(app):
    part, folder = app.folder()
    app.rules.repo.add(logic.checked(logic.draft_for("part", part, "Сверять дорожку", "")), app.ivanova.id)
    app.rules.repo.add(logic.checked(logic.draft_for("general", None, "Общее", "")), app.ivanova.id)
    app.open(part, folder)
    assert app.rules.badge() == 2
    assert "2" in [app.window.tab_bar.tabButton(i, 1).text() for i in range(app.window.tab_bar.count())
                   if app.window.tab_bar.tabButton(i, 1) is not None]
    assert [r.title for r in app.rules.panel.shown_rules] == ["Сверять дорожку"]  # общее в панель не попадает
    assert not app.rules.panel.isHidden()
    app.rules.mark_read([app.rules.panel.shown_rules[0].id])
    app.wait_idle()
    assert app.rules.badge() == 1
    app.rules.mark_all_read()
    app.wait_idle()
    assert app.rules.badge() is None
    # «прочитано» у каждого своё: у Ивановой (автор) всё прочитано, у третьего пользователя — всё новое
    assert app.rules.unread_count(app.ivanova.id) == 0
    assert app.rules.unread_count(app.petrov.id + 100) == 2


def test_panel_hidden_without_rules_for_part(app):
    part, folder = app.folder()
    app.rules.repo.add(logic.checked(logic.draft_for("general", None, "Общее", "")), app.ivanova.id)
    app.open(part, folder)
    assert app.rules.panel.isHidden()


def test_failed_photo_publishes_nothing_and_leaves_no_files(app):
    draft = logic.draft_for("general", None, "Заголовок", "", [str(app.tmp / "нет такого.jpg")])
    app.publish(draft)
    assert app.rules.repo.all(app.petrov.id) == []
    assert list((app.tmp / "правила").iterdir()) == []
    assert "прочитать" in app.rules.screen.error_label.text()


def test_screen_filters_and_form_follow_open_folder(app):
    screen = app.rules.screen
    assert not screen.scope_buttons["part"].isEnabled()
    part, folder = app.folder()
    app.rules.repo.add(logic.checked(logic.draft_for("part", part, "К детали", "")), app.ivanova.id)
    app.rules.repo.add(logic.checked(logic.draft_for("general", None, "Общее", "")), app.ivanova.id)
    app.open(part, folder)
    assert screen.scope_buttons["part"].isEnabled()
    assert len(screen.cards) == 2  # две карточки в сетке
    screen.filter_buttons["general"].click()
    assert list(screen.cards) == [r.id for r in screen.rules if r.scope == "general"]
    screen.filter_buttons["all"].click()
    screen.title_edit.setText("")
    screen.publish()
    assert "заголовок" in screen.error_label.text().lower()


def test_photo_columns():
    from atlas.features.rules.screen import photo_columns
    assert [photo_columns(n) for n in (1, 2, 3, 4, 6)] == [1, 2, 3, 2, 3]
    assert photo_columns(3, compact=True) == 2


def test_card_with_four_photos_is_big_and_opens_viewer(app, qtbot):
    from atlas.features.rules.screen import PhotoDialog, RuleCard, ZoomView, _Tile
    part, folder = app.folder()
    sources = [photo(app.tmp / "плата{}.jpg".format(n)) for n in range(4)]
    app.open(part, folder)
    app.publish(logic.draft_for("general", None, "4 платы считать однотипными", "Общий комментарий", sources))
    rule = app.rules.repo.all(app.petrov.id)[0]
    assert len(rule.photos) == 4
    card = RuleCard(rule, "Петров", app.tmp / "правила")
    qtbot.addWidget(card)
    card.resize(760, 600)
    card.show()
    tiles = card.findChildren(_Tile)
    assert len(tiles) == 4
    qtbot.waitUntil(lambda: all(t.width() > 300 for t in tiles))  # две в ряд: каждая крупная
    got = []
    card.photo_clicked.connect(lambda rels, index: got.append((len(rels), index)))
    tiles[2].clicked.emit(2)
    assert got == [(4, 2)]
    dialog = PhotoDialog(app.tmp / "правила", rule.photos, 2)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.index == 2 and dialog.next_button.isEnabled()
    dialog.step(1)
    assert dialog.index == 3 and not dialog.next_button.isEnabled()
    view = dialog.view
    assert isinstance(view, ZoomView)
    before = view.zoom
    from PyQt5.QtCore import QPoint, QPointF, Qt
    from PyQt5.QtGui import QWheelEvent
    view.wheelEvent(QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120), 0, Qt.Vertical, Qt.NoButton, Qt.NoModifier))
    assert view.zoom > before
    view.fit()
    assert view.zoom == pytest.approx(before, rel=0.05)


def test_form_shows_previews_and_can_drop_photos(app, tmp_path):
    screen = app.rules.screen
    screen.attach([photo(tmp_path / "a.jpg"), photo(tmp_path / "b.jpg")])
    assert screen.previews_layout.count() == 2 and not screen.drop_button.isHidden()
    screen.drop_photos()
    assert screen.previews_layout.count() == 0 and screen.drop_button.isHidden()


# --- карточки: архив, удаление, изменение (04.11.2026) -----------------------------------------
def _published(app, title="Сверяем ножки", photos=1):
    app.window.select_tab("rules")  # анимация играет только на видимой карточке
    paths = [photo(app.tmp / "{}_{}.jpg".format(title, number)) for number in range(photos)]
    app.publish(logic.draft_for("general", None, title, "Считать по схеме", paths))
    return next(rule for rule in app.rules.rules if rule.title == title)


def test_archive_plays_stamp_then_rule_goes_down_and_is_not_counted(app):
    first = _published(app, "Первое")
    _published(app, "Второе")
    screen = app.rules.screen
    assert list(screen.cards) == [r.id for r in app.rules.rules]
    app.ctx.user = app.ivanova  # для неё оба новые
    app.rules.refresh()
    app.wait_idle()
    assert app.rules.badge() == 2
    card = screen.cards[first.id]
    card.archive_button.click()
    app.qtbot.waitUntil(lambda: first.id in screen._animating, timeout=3000)
    assert card.animating
    app.qtbot.waitUntil(lambda: not screen._animating, timeout=5000)
    app.wait_idle()
    rules = app.rules.rules
    assert [r.title for r in logic.filtered(rules, logic.FILTER_ALL)] == ["Второе", "Первое"]  # архив — внизу
    assert next(r for r in rules if r.id == first.id).archived
    assert app.rules.badge() == 1  # архивное непрочитанным не считается
    screen.cards[first.id].archive_button.click()  # вернуть
    app.qtbot.waitUntil(lambda: not screen._animating and not next(r for r in app.rules.rules if r.id == first.id).archived,
                        timeout=5000)


def test_archived_rule_is_not_shown_for_the_part():
    archived = rule("kind", kind="A", archived_at="2026-11-01 10:00:00")
    assert logic.for_part([rule("kind", kind="A"), archived], PART) == [rule("kind", kind="A")]
    assert logic.unread_count([rule("general", read=False), rule("general", read=False, archived_at="x")]) == 1


def test_delete_asks_burns_the_card_and_removes_photos(app):
    item = _published(app, photos=2)
    files = list((app.tmp / "правила").iterdir())
    assert len(files) == 4  # две копии и две миниатюры
    screen = app.rules.screen
    screen.ask_delete = lambda rule_: False
    screen.cards[item.id].delete_button.click()
    assert app.rules.repo.all(app.petrov.id)
    screen.ask_delete = lambda rule_: True
    screen.cards[item.id].delete_button.click()
    app.qtbot.waitUntil(lambda: item.id in screen._animating, timeout=3000)
    app.qtbot.waitUntil(lambda: not screen._animating, timeout=5000)
    app.wait_idle()
    assert app.rules.repo.all(app.petrov.id) == [] and not list((app.tmp / "правила").iterdir())
    assert item.id not in screen.cards


def test_edit_changes_text_and_photos_keeps_scope(app):
    item = _published(app, photos=2)
    screen = app.rules.screen
    screen.cards[item.id].edit_button.click()
    assert screen.editing.id == item.id and screen.title_edit.text() == item.title
    assert screen.publish_button.text() == "Сохранить изменения" and not screen.scope_buttons["general"].isEnabled()
    screen.keep_rels = screen.keep_rels[:1]  # одно фото убрали
    screen.attach([photo(app.tmp / "новое.jpg")])
    screen.title_edit.setText("Сверяем ножки по схеме")
    screen.publish()
    app.qtbot.waitUntil(lambda: screen.editing is None, timeout=5000)
    app.wait_idle()
    changed = next(r for r in app.rules.rules if r.id == item.id)
    assert changed.title == "Сверяем ножки по схеме" and changed.updated_at and changed.scope == "general"
    assert len(changed.photos) == 2 and changed.photos[0] == item.photos[0] and item.photos[1] not in changed.photos
    assert not (app.tmp / "правила" / item.photos[1]).exists()
    assert screen.publish_button.text() == "Опубликовать"


def test_card_shows_author_tag_cover_and_body_in_text_color(app):
    item = _published(app, photos=3)
    app.rules.screen.open_photo = lambda rels, index: None  # окно фото модальное: в тесте не открываем
    app.rules.screen._render()
    card = app.rules.screen.cards[item.id]
    assert card.tag is not None and card.tag.name == "Петров" and card.tag.isChecked()
    assert card.cover is not None and card.cover.more == 2 and card.cover.image is not None
    opened = []
    card.photo_clicked.connect(lambda rels, index: opened.append((rels, index)))
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    QTest.mouseClick(card.cover, Qt.LeftButton)
    assert opened == [(item.photos, 0)]


def test_rule_older_than_two_weeks_can_only_be_archived(app):
    from datetime import datetime, timedelta

    item = _published(app, "Старое")
    old = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d %H:%M:%S")
    app.ctx.db.write(lambda conn: conn.execute("UPDATE rules SET created_at = ? WHERE id = ?", (old, item.id)))
    app.rules.refresh()
    app.wait_idle()
    screen = app.rules.screen
    card = screen.cards[item.id]
    assert card.locked and not card.edit_button.isEnabled() and not card.delete_button.isEnabled()
    assert card.archive_button.isEnabled() and "14 дней" in card.edit_button.toolTip()
    screen.ask_delete = lambda rule_: True
    screen._on_delete_clicked(item.id)  # кнопка выключена, но и сам вызов не удаляет
    screen.edit_rule(item.id)
    assert screen.editing is None
    app.rules.delete(item.id)  # и сервис не даёт: окно могло быть открыто давно
    app.wait_idle()
    assert app.rules.repo.all(app.petrov.id)
    screen.cards[item.id].archive_button.click()  # карточка могла перестроиться после перечитывания
    app.qtbot.waitUntil(lambda: not screen._animating and any(r.archived for r in app.rules.rules), timeout=5000)
    app.wait_idle()
    from PyQt5.QtWidgets import QLabel
    archived = screen.cards[item.id]
    assert any(label.text().startswith("В архиве · Петров") for label in archived.findChildren(QLabel))


def test_archived_card_says_who_archived_it(qtbot):
    from atlas.features.rules.cards import RuleTile
    from PyQt5.QtWidgets import QLabel

    card = RuleTile(rule("general", archived_at="2026-11-04 10:00:00", archived_by=2), "Петров", "#7DB4FF", "/правила",
                    archiver="Иванова")
    qtbot.addWidget(card)
    assert any(label.text().startswith("В архиве · Иванова") for label in card.findChildren(QLabel))


def test_wheel_zoom_is_gentle_on_touchpad(qtbot):
    from PyQt5.QtCore import QPoint, QPointF, Qt
    from PyQt5.QtGui import QPixmap, QWheelEvent
    from atlas.features.rules.screen import ZoomView

    view = ZoomView()
    qtbot.addWidget(view)
    view.resize(400, 300)
    pixmap = QPixmap(800, 600)
    pixmap.fill()
    view.set_pixmap(pixmap)
    start = view.zoom
    small = QWheelEvent(QPointF(200, 150), QPointF(200, 150), QPoint(0, 0), QPoint(0, 12), Qt.NoButton, Qt.NoModifier,
                        Qt.ScrollUpdate, False)
    view.wheelEvent(small)  # одно мелкое событие тачпада — десятая доля шага
    assert view.zoom / start == pytest.approx(1.2 ** 0.1)
