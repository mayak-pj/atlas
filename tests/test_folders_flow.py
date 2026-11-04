"""folders в настоящем приложении: панель в слоте compare.left, клик открывает папку."""
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PyQt5.QtTest import QTest
from PyQt5.QtCore import Qt

from atlas.app import build_core, build_window, start_features
from atlas.core.app_context import User
from atlas.core.config import AppPaths

REPO = Path(__file__).resolve().parent.parent


class App:
    def __init__(self, tmp_path, qtbot, features=("compare", "folders", "presence")):
        root = tmp_path / "Атлас"
        (root / "config").mkdir(parents=True)
        shutil.copy(str(REPO / "config" / "app.json"), str(root / "config" / "app.json"))
        entries = [{"id": name} for name in features]
        (root / "config" / "features.json").write_text(json.dumps({"features": entries}), encoding="utf-8")
        local = {"image_cache": {"disk_dir": str(tmp_path / "кэш")}, "folders": {"refresh_s": 3600}, "presence": {"heartbeat_s": 3600}}
        (root / "config" / "local.json").write_text(json.dumps(local), encoding="utf-8")
        self.ctx = build_core(AppPaths(root))
        self.qtbot = qtbot
        self.svc = self.ctx.services
        self.root = tmp_path
        self.registry = start_features(self.ctx)
        assert self.registry.failures == []
        self.window = build_window(self.registry)
        qtbot.addWidget(self.window)
        self.window.show()

    def feature(self, name):
        return next(item.instance for item in self.registry.loaded if item.spec.id == name)

    def add_folder(self, name, project="Орион-24", kind="A", photos=2, date="2026-10-31"):
        part = self.svc.get("parts").ensure(kind, project, "N15", name)
        folder = self.svc.get("folders").add(part.id, str(self.root / "Сеть" / name), date)
        self.svc.get("folders").add_photos(folder.id, ["{}.jpg".format(number) for number in range(photos)])
        return folder

    def finish(self, folder, user, when=None):
        self.svc.get("folders").set_status(folder.id, "done", user.id)
        if when:
            stamp = when.strftime("%Y-%m-%d %H:%M:%S")
            self.ctx.db.write(lambda conn: conn.execute("UPDATE folders SET status_at = ? WHERE id = ?", (stamp, folder.id)))

    def reload(self):
        feature = self.feature("folders")
        self.qtbot.waitUntil(lambda: feature._thread is None, timeout=3000)
        feature.refresh()
        self.qtbot.waitUntil(lambda: feature._thread is None and not feature._again, timeout=3000)

    def titles(self):
        panel = self.feature("folders").panel
        return [card.entry.title for card in panel.cards]

    def stop(self):
        self.registry.stop_all()


@pytest.fixture
def app(tmp_path, qtbot):
    result = App(tmp_path, qtbot)
    yield result
    result.stop()


def test_panel_lists_new_and_recently_checked(app):
    user = app.svc.get("users").add("Иванова", lambda count: "#7DB4FF")
    app.add_folder("SSD XS-2280")
    app.add_folder("Шлейф FPC-40", kind="B", project="Вега")
    old = app.add_folder("Дисплей LCD-156")
    fresh = app.add_folder("Матплата MB-15")
    app.finish(old, user, datetime.now() - timedelta(days=9))
    app.finish(fresh, user)
    app.reload()
    assert sorted(app.titles()[:2]) == ["SSD XS-2280", "Шлейф FPC-40"]
    assert "Дисплей LCD-156" not in app.titles()
    done = app.feature("folders").snapshot.done
    assert [(item.title, item.pill, item.pill_token) for item in done] == [("Матплата MB-15", "ОК", "ok")]
    assert done[0].note.endswith("Иванова")
    assert app.feature("folders").snapshot.new_total == 2


def test_panel_is_in_compare_left_slot(app):
    app.reload()
    assert app.feature("folders").panel in app.window.slots.panels("compare.left")
    assert app.feature("compare").screen.left.isVisible()


def test_click_opens_folder_in_compare(app):
    first = app.add_folder("SSD XS-2280")
    second = app.add_folder("Плата PWR-7")
    app.reload()
    card = next(item for item in app.feature("folders").panel.cards if item.entry.folder_id == second.id)
    QTest.mouseClick(card, Qt.LeftButton)
    compare = app.feature("compare")
    app.qtbot.waitUntil(lambda: compare.folder is not None and compare.folder.id == second.id, timeout=5000)
    app.qtbot.waitUntil(lambda: app.feature("folders").selected_id == second.id, timeout=3000)
    selected = [item.entry.folder_id for item in app.feature("folders").panel.cards if item.property("on")]
    assert selected == [second.id]
    assert first.id not in selected


def test_new_folder_appears_on_copy_event(app):
    app.reload()
    assert app.titles() == []
    folder = app.add_folder("SSD XS-2280")
    app.ctx.bus.publish("folder.copied", {"folder_id": folder.id, "part_id": folder.part_id})
    app.qtbot.waitUntil(lambda: app.titles() == ["SSD XS-2280"], timeout=3000)


def test_shows_who_works_on_folder_except_me(app):
    me = app.svc.get("users").add("Иванова", lambda count: "#7DB4FF")
    other = app.svc.get("users").add("Кузнецова", lambda count: "#3DD68C")
    app.ctx.user = me
    folder = app.add_folder("SSD XS-2280")
    app.reload()
    from atlas.features.presence.ui import OnlineUser
    online = [OnlineUser(me.id, me.name, me.color, folder.id, None), OnlineUser(other.id, other.name, other.color, folder.id, None)]
    app.feature("presence")._online = online
    app.ctx.bus.publish("presence.changed", {"online": online})
    from PyQt5.QtWidgets import QLabel
    texts = [label.text() for label in app.feature("folders").panel.findChildren(QLabel)]
    assert "Кузнецова работает" in texts
    assert not any(text.startswith("Иванова") for text in texts)


def test_database_failure_keeps_previous_list(app):
    app.add_folder("SSD XS-2280")
    app.reload()
    feature = app.feature("folders")
    feature._read = lambda: (_ for _ in ()).throw(OSError("сеть пропала"))
    app.reload()
    assert app.titles() == ["SSD XS-2280"]


def test_works_without_compare_and_presence(tmp_path, qtbot):
    app = App(tmp_path, qtbot, features=("folders",))
    try:
        app.add_folder("SSD XS-2280")
        app.reload()
        assert app.titles() == ["SSD XS-2280"]
        QTest.mouseClick(app.feature("folders").panel.cards[0], Qt.LeftButton)  # compare нет: без падения
    finally:
        app.stop()


def test_compare_works_without_folders(tmp_path, qtbot):
    app = App(tmp_path, qtbot, features=("compare",))
    try:
        folder = app.add_folder("SSD XS-2280")
        app.svc.get("compare").open_folder(folder.id)
        qtbot.waitUntil(lambda: app.svc.get("compare").current_folder() is not None, timeout=5000)
    finally:
        app.stop()


# --- удалить папку из Atlas (04.11.2026) -------------------------------------------------------
def test_cross_deletes_open_folder_and_it_can_be_added_again(app):
    folder = app.add_folder("SSD XS-2280", photos=3)
    folders = app.svc.get("folders")
    photo = folders.photos(folder.id)[0]
    folders.mark_photo(photo.id, "remark", defect_kind="Сбит элемент")
    app.reload()
    compare = app.feature("compare")
    compare.open_folder(folder.id)
    app.qtbot.waitUntil(lambda: compare.folder is not None, timeout=5000)
    presence = app.feature("presence")
    presence.beat() if hasattr(presence, "beat") else None
    user = app.svc.get("users").add("Петров", lambda count: "#7DB4FF")
    app.ctx.db.write(lambda conn: conn.execute(  # коллега «работает» над этой папкой: ссылка не мешает удалению
        "INSERT OR REPLACE INTO presence (user_id, folder_id, beat, seen_at) VALUES (?, ?, 1, '2026-11-04 10:00:00')",
        (user.id, folder.id)))
    feature = app.feature("folders")
    asked = []
    feature.ask_delete = lambda title: asked.append(title) or False
    card = next(item for item in feature.panel.cards if item.entry.folder_id == folder.id)
    card.delete_button.click()
    assert asked and folders.get(folder.id) is not None  # передумал
    feature.ask_delete = lambda title: True
    events = []
    app.ctx.bus.subscribe("folder.deleted", events.append)
    card.delete_button.click()
    app.qtbot.waitUntil(lambda: events == [{"folder_id": folder.id}], timeout=5000)
    assert folders.get(folder.id) is None and folders.photos(folder.id) == []
    assert compare.folder is None and compare.screen.model.photos == []
    assert app.ctx.db.read(lambda conn: conn.execute(
        "SELECT folder_id FROM presence WHERE user_id = ?", (user.id,)).fetchone()[0]) is None
    app.qtbot.waitUntil(lambda: folder.id not in [c.entry.folder_id for c in feature.panel.cards], timeout=5000)
    again = folders.add(folder.part_id, folder.path, "2026-10-31")  # тот же путь — снова как новая
    assert again.id != folder.id and folders.add_photos(again.id, ["0.jpg"]) == 1
    assert folders.delete(folder.id) is None  # уже нет


def test_folder_in_work_is_listed_and_can_be_reopened(app):
    """04.11.2026: папку с отметками не было видно нигде — ни в «Новых», ни в «Проверено»."""
    folder = app.add_folder("SSD XS-2280")
    folders = app.svc.get("folders")
    folders.mark_photo(folders.photos(folder.id)[0].id, "type:1")
    folders.set_status(folder.id, "in_work")
    app.reload()
    feature = app.feature("folders")
    assert folder.id in [entry.folder_id for entry in feature.snapshot.in_work]
    card = next(item for item in feature.panel.cards if item.entry.folder_id == folder.id)
    QTest.mouseClick(card, Qt.LeftButton)
    compare = app.feature("compare")
    app.qtbot.waitUntil(lambda: compare.folder is not None and compare.folder.id == folder.id, timeout=5000)
