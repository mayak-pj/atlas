"""comments (7.2): логика, запись с фото и вставкой из буфера, адресат, «Готово», срок жизни, счётчик."""
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PyQt5.QtGui import QColor, QImage

from atlas.app import build_core, build_window, start_features
from atlas.core.config import AppPaths
from atlas.features.comments import logic

REPO = Path(__file__).resolve().parent.parent


def comment(**kw):
    base = dict(id=1, author_id=1, to_user_id=None, body="t", part_id=None, folder_id=None, part_label="",
                earlier_error=False, created_at="2026-11-02 08:51:00", expires_at=None)
    base.update(kw)
    return logic.Comment(**base)


# --- логика ---------------------------------------------------------------------------------
def test_checked_needs_text_or_photo_and_limits():
    with pytest.raises(logic.CommentError):
        logic.checked(logic.Draft("   "))
    assert logic.checked(logic.Draft("  привет ")).body == "привет"
    assert logic.checked(logic.Draft("", photos=("a.jpg",))).photos == ("a.jpg",)
    with pytest.raises(logic.CommentError):
        logic.checked(logic.Draft("x", photos=("a",) * 5), max_photos=4)


def test_expiry_and_lifetime_text():
    now = datetime(2026, 11, 2, 12, 0)
    assert logic.expires_at(None, now) is None
    assert logic.expires_at(7, now) == "2026-11-09 12:00:00"
    item = comment(expires_at="2026-11-07 12:00:00")
    assert logic.lifetime_text(item, now) == "исчезнет через 5 дн"
    assert logic.lifetime_text(comment(), now) == ""
    assert logic.is_expired(comment(expires_at="2026-11-02 11:00:00"), now)
    assert not logic.is_expired(comment(), now)


def test_visibility_and_pending_count():
    items = [comment(id=1, author_id=2), comment(id=2, author_id=2, to_user_id=1), comment(id=3, author_id=2, to_user_id=3),
             comment(id=4, author_id=1), comment(id=5, author_id=2, done=True)]
    assert [i.id for i in items if logic.visible_to(i, 1)] == [1, 2, 4]
    assert logic.pending_count(items, 1) == 2  # чужие «всем» и «мне»; своё и закрытое не считаются
    assert logic.pending_count([comment(author_id=2, expires_at="2020-01-01 00:00:00")], 1) == 0


def test_options_come_from_data_file(tmp_path):
    assert logic.load_options(tmp_path)[0] == logic.DEFAULT_LIFETIMES
    lifetimes, max_photos = logic.load_options(REPO / "data")
    assert (7, "7 дней") in lifetimes and (None, "не удалять") in lifetimes and max_photos == 4


# --- в приложении -------------------------------------------------------------------------------
class App:
    def __init__(self, tmp_path, qtbot, features=("compare", "comments")):
        root = tmp_path / "Атлас"
        (root / "config").mkdir(parents=True)
        shutil.copy(str(REPO / "config" / "app.json"), str(root / "config" / "app.json"))
        (root / "config" / "features.json").write_text(
            json.dumps({"features": [{"id": name} for name in features]}), encoding="utf-8")
        local = {"image_cache": {"disk_dir": str(tmp_path / "кэш")}, "comments": {"dir": str(tmp_path / "сообщения")}}
        (root / "config" / "local.json").write_text(json.dumps(local), encoding="utf-8")
        (tmp_path / "сообщения").mkdir()
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
        self.feature = next(item.instance for item in self.registry.loaded if item.spec.id == "comments")

    def idle(self):
        f = self.feature
        self.qtbot.waitUntil(lambda: not f._busy_read and not f._again and not any(t.is_alive() for t in f._threads),
                             timeout=4000)

    def folder(self, name="SSD XS-2280"):
        part = self.svc.get("parts").ensure("A", "Орион", "N15", name)
        folder = self.svc.get("folders").add(part.id, str(self.tmp / "Сеть" / name / "2026-10-01"), "2026-10-01")
        return part, folder

    def open(self, part, folder):
        self.ctx.bus.publish("folder.opened", {"folder_id": folder.id, "part_id": part.id})
        self.idle()

    def send(self, draft):
        self.feature.send(draft)
        self.qtbot.waitUntil(lambda: self.feature.screen.send_button.isEnabled() and not self.feature._busy_read
                             and not any(t.is_alive() for t in self.feature._threads), timeout=5000)

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


def test_send_with_file_and_pasted_image_stores_both(app):
    pasted = QImage(800, 600, QImage.Format_RGB32)
    pasted.fill(QColor("blue"))
    events = []
    app.ctx.bus.subscribe("comment.posted", events.append)
    app.send(logic.Draft("Гляньте", app.ivanova.id, photos=(photo(app.tmp / "снимок.jpg"), pasted)))
    items = app.feature.repo.all(app.petrov.id)
    assert len(items) == 1 and len(items[0].photos) == 2
    big = app.tmp / "сообщения" / items[0].photos[0]
    assert QImage(str(big)).width() == 1600
    assert (app.tmp / "сообщения" / logic.thumb_rel(items[0].photos[1])).is_file()
    assert events and events[-1]["to_user"] == app.ivanova.id
    assert items[0].expires_at is not None


def test_addressee_counter_and_done_follow_user(app):
    repo = app.feature.repo
    repo.add(logic.checked(logic.Draft("Вам", app.petrov.id)), app.ivanova.id)
    repo.add(logic.checked(logic.Draft("Всем")), app.ivanova.id)
    repo.add(logic.checked(logic.Draft("Не вам", 999)), app.ivanova.id)
    app.feature.refresh()
    app.idle()
    assert app.feature.badge() == 2
    assert app.feature.pending_count(app.ivanova.id) == 0  # свои не считаются
    first = next(i for i in app.feature.items if i.body == "Вам")
    app.feature.mark_done(first.id)
    app.idle()
    assert app.feature.badge() == 1
    # у Ивановой «Готово» Петрова не сказалось
    assert [i.done for i in repo.all(app.ivanova.id)] == [False, False, False]
    screen = app.feature.screen
    assert screen.list.count() == 2  # «Всем» и растяжка


def test_expired_comments_are_hidden_and_purged_with_files(app):
    old = (datetime.now() - timedelta(days=1)).strftime(logic.TIME_FORMAT)
    app.send(logic.Draft("Старое", photos=(photo(app.tmp / "a.jpg"),), days=1))
    app.feature.repo.db.write(lambda conn: conn.execute("UPDATE comments SET expires_at = ?", (old,)))
    assert app.feature.repo.all(app.petrov.id) == []
    rels = app.feature.repo.purge_expired()
    app.feature.store.discard_rels(rels)
    assert len(rels) == 1 and list((app.tmp / "сообщения").iterdir()) == []


def test_bind_to_open_part_and_open_in_compare(app, monkeypatch):
    part, folder = app.folder()
    screen = app.feature.screen
    assert not screen.bind_button.isEnabled()
    app.open(part, folder)
    assert screen.bind_button.isEnabled()
    screen.bind_button.click()
    screen.earlier_button.click()
    screen.edit.setPlainText("Сбит конденсатор")
    screen.send()
    app.qtbot.waitUntil(lambda: app.feature.repo.all(app.petrov.id) != [], timeout=4000)
    app.idle()
    item = app.feature.repo.all(app.petrov.id)[0]
    assert (item.part_id, item.folder_id, item.earlier_error) == (part.id, folder.id, True)
    assert "SSD XS-2280" in item.part_label
    app.qtbot.waitUntil(lambda: screen.edit.toPlainText() == "", timeout=4000)  # ответ потока приходит очередью в GUI
    assert screen.bind_button.isChecked()  # привязка к открытой детали остаётся
    opened = []
    monkeypatch.setattr(app.svc.get_optional("compare"), "open_folder", opened.append)
    app.feature._open_in_compare(item)
    assert opened == [folder.id]


def test_reply_prefills_addressee_and_paste_adds_photo(app):
    repo = app.feature.repo
    repo.add(logic.checked(logic.Draft("Вопрос")), app.ivanova.id)
    app.feature.refresh()
    app.idle()
    screen = app.feature.screen
    screen.reply_to(app.feature.items[0])
    assert screen.to_box.currentData() == app.ivanova.id
    image = QImage(100, 100, QImage.Format_RGB32)
    image.fill(QColor("green"))
    from PyQt5.QtCore import QMimeData
    mime = QMimeData()
    mime.setImageData(image)
    assert screen.edit.canInsertFromMimeData(mime)
    screen.edit.insertFromMimeData(mime)
    assert len(screen.photos) == 1 and screen.edit.toPlainText() == ""
    assert screen.previews_layout.count() == 1 and not screen.drop_button.isHidden()
    screen.drop_photos()
    assert screen.photos == []


def test_failed_photo_sends_nothing_and_leaves_no_files(app):
    app.send(logic.Draft("x", photos=(str(app.tmp / "нет такого.jpg"),)))
    assert app.feature.repo.all(app.petrov.id) == []
    assert list((app.tmp / "сообщения").iterdir()) == []
    assert "прочитать" in app.feature.screen.error_label.text()
