"""draft (8.1): автосписок из отметок, ручные строки, заметки с автосохранением, пояснения, слот действий."""
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from atlas.app import build_core, build_window, start_features
from atlas.core.config import AppPaths
from atlas.features.draft import logic

REPO = Path(__file__).resolve().parent.parent


def photo(pid, mark, sn="", rel="a.jpg", kind=None):
    return SimpleNamespace(id=pid, mark=mark, sn=sn, rel_path=rel, defect_kind=kind)


# --- логика ---------------------------------------------------------------------------------
def test_auto_entries_group_types_and_list_problems():
    photos = [photo(1, "type:2", "S1"), photo(2, "type:2", "S1"), photo(3, "type:1"), photo(4, None),
              photo(5, "remark", "S9", "b.jpg", "Размытое фото"), photo(6, "defect", "S8", "a.jpg")]
    entries = logic.auto_entries(photos, {"type:2": "3-й чип", "photo:5": "переснять"})
    assert [e.key for e in entries] == ["type:1", "type:2", "photo:6", "photo:5"]
    assert entries[1].count == 2 and entries[1].sn == "S1" and entries[1].text == "3-й чип"
    assert logic.count_text(entries[1]) == "2 фото" and logic.count_text(entries[2]) == ""
    assert entries[3].kind_text == "Размытое фото" and entries[3].text == "переснять"
    assert logic.title(entries[0]) == "ТИП 1" and logic.title(entries[2]) == "ДЕФЕКТ"


def test_type_sn_empty_when_photos_differ():
    entries = logic.auto_entries([photo(1, "type:1", "A"), photo(2, "type:1", "B")], {})
    assert entries[0].sn == ""


def test_checked_manual():
    assert logic.checked_manual("remark", None, " S1 ", " пятно ") == ("remark", None, "S1", "пятно")
    assert logic.checked_manual("type", 3, "", "x")[1] == 3
    for bad in (("zzz", None, "a", "b"), ("type", 0, "a", "b"), ("remark", None, "", " ")):
        with pytest.raises(logic.DraftError):
            logic.checked_manual(*bad)


# --- в приложении ---------------------------------------------------------------------------
class App:
    def __init__(self, tmp_path, qtbot):
        root = tmp_path / "Атлас"
        (root / "config").mkdir(parents=True)
        shutil.copy(str(REPO / "config" / "app.json"), str(root / "config" / "app.json"))
        (root / "config" / "features.json").write_text(
            json.dumps({"features": [{"id": name} for name in ("compare", "draft")]}), encoding="utf-8")
        (root / "config" / "local.json").write_text(
            json.dumps({"image_cache": {"disk_dir": str(tmp_path / "кэш")}}), encoding="utf-8")
        self.ctx = build_core(AppPaths(root))
        self.qtbot, self.tmp = qtbot, tmp_path
        self.svc = self.ctx.services
        self.registry = start_features(self.ctx)
        assert self.registry.failures == []
        self.window = build_window(self.registry)
        qtbot.addWidget(self.window)
        self.window.show()
        self.ctx.user = self.svc.get("users").add("Петров", lambda count: "#7DB4FF")
        self.feature = next(item.instance for item in self.registry.loaded if item.spec.id == "draft")
        self.screen = self.feature.screen

    def idle(self):
        f = self.feature
        self.qtbot.waitUntil(lambda: not f._reading and not f._again and not f.reload_timer.isActive()
                             and not any(t.is_alive() for t in f._threads), timeout=4000)

    def folder(self):
        part = self.svc.get("parts").ensure("A", "Орион", "N15", "SSD")
        folder = self.svc.get("folders").add(part.id, str(self.tmp / "Сеть" / "SSD" / "2026-10-01"), "2026-10-01")
        self.svc.get("folders").add_photos(folder.id, ["1.jpg", "2.jpg", "3.jpg"])
        return part, folder

    def open(self, part, folder):
        self.ctx.bus.publish("folder.opened", {"folder_id": folder.id, "part_id": part.id})
        self.idle()


@pytest.fixture
def app(tmp_path, qtbot):
    result = App(tmp_path, qtbot)
    yield result
    result.registry.stop_all()


def test_without_folder_nothing_is_enabled(app):
    assert not app.screen.notes.isEnabled() and not app.screen.add_button.isEnabled()


def test_marks_appear_and_comment_persists(app):
    part, folder = app.folder()
    photos = app.svc.get("folders").photos(folder.id)
    app.open(part, folder)
    assert app.screen.entries == []
    app.svc.get("folders").mark_photo(photos[0].id, "type:1", user_id=app.ctx.user.id)
    app.svc.get("folders").mark_photo(photos[1].id, "remark", sn="S5", user_id=app.ctx.user.id)
    app.ctx.bus.publish("photo.marked", {"photo_id": photos[1].id, "mark": "remark", "sn": "S5"})
    app.qtbot.waitUntil(lambda: len(app.screen.entries) == 2, timeout=4000)
    app.idle()
    row = app.screen.list.itemAt(1).widget()
    row.edit.setText("переснять")
    row._finished()
    app.idle()
    snap = app.feature.snapshot(folder.id)
    assert [e.text for e in snap.entries] == ["", "переснять"]


def test_notes_autosave_and_come_back(app):
    part, folder = app.folder()
    app.open(part, folder)
    app.screen.notes.setPlainText("0412 — посмотреть ещё раз")
    app.qtbot.waitUntil(lambda: app.feature.snapshot(folder.id).notes == "0412 — посмотреть ещё раз", timeout=4000)
    app.screen.notes.setPlainText("")
    app.screen.timer.stop()
    app.screen.flush()
    app.qtbot.waitUntil(lambda: app.feature.snapshot(folder.id).notes == "", timeout=4000)


def test_notes_flushed_on_folder_switch(app):
    part, first = app.folder()
    second = app.svc.get("folders").add(part.id, str(app.tmp / "Сеть" / "SSD" / "2026-10-02"), "2026-10-02")
    app.open(part, first)
    app.screen.notes.setPlainText("для первой")
    app.open(part, second)
    app.qtbot.waitUntil(lambda: app.feature.snapshot(first.id).notes == "для первой", timeout=4000)
    assert app.feature.snapshot(second.id).notes == ""
    assert app.screen.notes.toPlainText() == ""


def test_manual_entry_add_edit_remove(app):
    part, folder = app.folder()
    app.open(part, folder)
    app.screen.add_requested.emit("remark", 1, "S7", "блик?")
    app.qtbot.waitUntil(lambda: len(app.screen.entries) == 1, timeout=4000)
    entry = app.screen.entries[0]
    assert entry.sn == "S7" and entry.text == "блик?" and entry.manual_id is not None
    app.screen.add_requested.emit("remark", 1, "", "")  # пусто — не добавляется, ошибка в строке состояния
    assert app.screen.status.text()
    app.feature.remove_manual(entry)
    app.qtbot.waitUntil(lambda: app.screen.entries == [], timeout=4000)


def test_actions_slot_takes_other_features_panels(app):
    from PyQt5.QtWidgets import QPushButton
    assert app.window.slots.has_slot("draft.actions")
    button = QPushButton("Записать в Excel")
    app.window.slots.add_panel("draft.actions", button)
    assert button.parent() is not None
