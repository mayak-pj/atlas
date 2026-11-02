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
    assert screen.list.count() == 3  # две карточки и растяжка
    screen.filter_buttons["general"].click()
    assert screen.list.count() == 2
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
