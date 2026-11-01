"""add_folder: окно «Добавить папку…» и кнопка в compare.left."""
import json
import shutil
from datetime import date
from pathlib import Path

import pytest
from PyQt5.QtWidgets import QPushButton

from atlas.app import build_core, build_window, start_features
from atlas.core.config import AppPaths
from atlas.core.theme import apply_theme
from atlas.features.add_folder import logic
from atlas.features.add_folder.dialog import AddFolderDialog

REPO = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 1)
PATH = "R:\\Однотипность\\Орион-24\\N15\\Плата MB-15\\31.10.2026 (3 фото)"


# --- окно ----------------------------------------------------------------------------------
def make_dialog(qtbot, scan=None, parts=(), kinds=("A", "B")):
    apply_theme(__import__("PyQt5.QtWidgets", fromlist=["QApplication"]).QApplication.instance())
    dialog = AddFolderDialog(kinds, parts, today=TODAY, scan=scan or (lambda path: (["1.jpg", "2.jpg", "3.jpg"], "")))
    qtbot.addWidget(dialog)
    return dialog


def wait_ready(qtbot, dialog, ready=True):
    qtbot.waitUntil(lambda: dialog.add_button.isEnabled() == ready and "Ищу" not in dialog.status.text(), timeout=3000)


def test_pasted_path_fills_fields_and_finds_photos(qtbot):
    dialog = make_dialog(qtbot)
    dialog.set_path('"' + PATH + '"')  # проводник копирует путь в кавычках
    wait_ready(qtbot, dialog)
    assert (dialog.project.currentText(), dialog.device.currentText(), dialog.part.text(), dialog.date.text()) == (
        "Орион-24", "N15", "Плата MB-15", "2026-10-31")
    assert dialog.status.text() == "Фото в папке: 3"
    data = dialog.data()
    assert data.path == PATH and data.photos == ("1.jpg", "2.jpg", "3.jpg") and data.date == "2026-10-31"


def test_add_is_disabled_until_photos_found(qtbot):
    import threading
    gate = threading.Event()

    def slow(path):
        gate.wait(3)
        return ["1.jpg"], ""

    dialog = make_dialog(qtbot, scan=slow)
    dialog.set_path(PATH)
    assert not dialog.add_button.isEnabled() and dialog.status.text() == "Ищу фото…"
    gate.set()
    wait_ready(qtbot, dialog)


def test_missing_folder_and_empty_folder_explain_themselves(qtbot):
    dialog = make_dialog(qtbot, scan=lambda path: (None, "Нет такой папки (или она недоступна): " + path))
    dialog.set_path(PATH)
    wait_ready(qtbot, dialog, ready=False)
    assert "Нет такой папки" in dialog.status.text() and dialog.data() is None
    empty = make_dialog(qtbot, scan=lambda path: ([], ""))
    empty.set_path(PATH)
    wait_ready(qtbot, empty, ready=False)
    assert ".jpg" in empty.status.text()


def test_suggestion_does_not_overwrite_what_person_typed(qtbot):
    dialog = make_dialog(qtbot)
    dialog.part.textEdited.emit("Моя деталь")
    dialog.part.setText("Моя деталь")
    dialog.set_path(PATH)
    wait_ready(qtbot, dialog)
    assert dialog.part.text() == "Моя деталь" and dialog.project.currentText() == "Орион-24"


def test_drive_letter_chooses_kind_and_known_projects_are_offered(qtbot):
    from types import SimpleNamespace
    parts = [SimpleNamespace(kind="B", project="Вега-3", device="K9")]
    dialog = make_dialog(qtbot, parts=parts)
    dialog.set_path("B:\\Однотипность\\Вега-3\\K9\\Деталь\\31.10")
    wait_ready(qtbot, dialog)
    assert dialog.kind.currentData() == "B"
    assert [dialog.project.itemText(i) for i in range(dialog.project.count())] == ["Вега-3"]
    assert [dialog.device.itemText(i) for i in range(dialog.device.count())] == ["K9"]


def test_old_scan_result_is_ignored_after_path_changed(qtbot):
    import threading
    release, answers = threading.Event(), {}

    def scan(path):
        if path.endswith("старая"):
            release.wait(3)
            return ["старое.jpg"], ""
        return ["новое.jpg"], ""

    dialog = make_dialog(qtbot, scan=scan)
    dialog.set_path("R:\\Однотипность\\П\\Д\\старая")
    dialog.set_path("R:\\Однотипность\\П\\Д\\новая")
    wait_ready(qtbot, dialog)
    release.set()
    qtbot.wait(100)
    assert dialog.data().photos == ("новое.jpg",)


def test_browse_puts_chosen_folder_into_field(qtbot):
    dialog = make_dialog(qtbot)
    dialog.choose_directory = lambda start: PATH
    dialog.browse()
    wait_ready(qtbot, dialog)
    assert dialog.path.text() == PATH


def test_bad_date_blocks_add(qtbot):
    dialog = make_dialog(qtbot)
    dialog.set_path(PATH)
    wait_ready(qtbot, dialog)
    dialog.date.setText("31.31")
    assert not dialog.add_button.isEnabled() and "Дата" in dialog.status.text()


def test_real_scan_reads_jpegs_from_disk(qtbot, tmp_path):
    from atlas.features.add_folder.dialog import scan_folder
    folder = tmp_path / "Папка с пробелом"
    (folder / "sub").mkdir(parents=True)
    for name in ("1.jpg", "sub/2.JPEG", "т.txt"):
        (folder / name).write_bytes(b"x")
    assert scan_folder(str(folder)) == (["1.jpg", "sub/2.JPEG"], "")
    photos, error = scan_folder(str(tmp_path / "нет"))
    assert photos is None and "Нет такой папки" in error


# --- в приложении --------------------------------------------------------------------------
class App:
    def __init__(self, tmp_path, qtbot, features=("compare", "folders", "add_folder")):
        root = tmp_path / "Атлас"
        (root / "config").mkdir(parents=True)
        shutil.copy(str(REPO / "config" / "app.json"), str(root / "config" / "app.json"))
        (root / "config" / "features.json").write_text(
            json.dumps({"features": [{"id": name} for name in features]}), encoding="utf-8")
        local = {"image_cache": {"disk_dir": str(tmp_path / "кэш")}, "folders": {"refresh_s": 3600}}
        (root / "config" / "local.json").write_text(json.dumps(local), encoding="utf-8")
        self.ctx = build_core(AppPaths(root))
        self.qtbot = qtbot
        self.svc = self.ctx.services
        self.registry = start_features(self.ctx)
        assert self.registry.failures == []
        self.window = build_window(self.registry)
        qtbot.addWidget(self.window)
        self.window.show()
        self.events = []
        for name in ("folder.copied", "folder.opened"):
            self.ctx.bus.subscribe(name, lambda payload, name=name: self.events.append((name, payload)))
        self.feature = next(item.instance for item in self.registry.loaded if item.spec.id == "add_folder")

    def data(self, **changes):
        values = dict(path=str(Path("/сеть") / "Папка"), kind="A", project="Орион-24", device="N15", part="Плата MB-15",
                      date="2026-10-31", photos=("1.jpg", "2.jpg"))
        values.update(changes)
        return logic.FolderData(**values)

    def click(self, data):
        self.feature.ask_folder = lambda parts: data
        self.feature.button.click()
        self.qtbot.waitUntil(lambda: not self.feature.busy, timeout=5000)

    def stop(self):
        self.registry.stop_all()
        self.svc.get("image_cache").stop()


@pytest.fixture
def app(tmp_path, qtbot):
    result = App(tmp_path, qtbot)
    yield result
    result.stop()


def test_button_sits_in_compare_left_above_folders(app):
    panels = app.window.slots.panels("compare.left")
    assert panels[0] is app.feature.button and app.feature.button.text() == "Добавить папку…"
    assert app.feature.button.focusPolicy() == 0  # Qt.NoFocus: стрелки остаются у экрана сравнения


def test_adding_registers_part_folder_photos_publishes_and_opens(app):
    app.click(app.data())
    folders = app.svc.get("folders").recent()
    assert len(folders) == 1 and folders[0].status == "new" and folders[0].folder_date == "2026-10-31"
    assert [photo.rel_path for photo in app.svc.get("folders").photos(folders[0].id)] == ["1.jpg", "2.jpg"]
    part = app.svc.get("parts").get(folders[0].part_id)
    assert (part.kind, part.project, part.device, part.name) == ("A", "Орион-24", "N15", "Плата MB-15")
    app.qtbot.waitUntil(lambda: any(name == "folder.opened" for name, _ in app.events), timeout=5000)  # compare открыл папку
    assert ("folder.copied", {"folder_id": folders[0].id, "part_id": part.id}) in app.events
    assert app.feature.button.isEnabled()


def test_cancel_adds_nothing_and_frees_button(app):
    app.click(None)
    assert app.svc.get("folders").recent() == [] and app.feature.button.isEnabled() and app.events == []


def test_same_folder_twice_is_not_duplicated_and_says_so(app):
    messages = []
    app.window.statusBar().messageChanged.connect(messages.append)
    app.click(app.data())
    app.click(app.data())
    assert len(app.svc.get("folders").recent()) == 1
    app.qtbot.waitUntil(lambda: any("уже была" in text for text in messages), timeout=3000)


def test_second_run_adds_only_new_photos(app):
    app.click(app.data(photos=("1.jpg",)))
    app.click(app.data(photos=("1.jpg", "2.jpg")))
    folder = app.svc.get("folders").recent()[0]
    assert [photo.rel_path for photo in app.svc.get("folders").photos(folder.id)] == ["1.jpg", "2.jpg"]


def test_failure_is_reported_and_button_recovers(app):
    messages = []
    app.window.statusBar().messageChanged.connect(messages.append)
    app.click(app.data(kind="Z"))  # такого вида проекта нет
    app.qtbot.waitUntil(lambda: any("Не удалось добавить папку" in text for text in messages), timeout=3000)
    assert app.feature.button.isEnabled() and app.svc.get("folders").recent() == []


def test_known_parts_are_passed_to_the_window(app):
    app.click(app.data())
    seen = []
    app.feature.ask_folder = lambda parts: seen.append(list(parts)) or None
    app.feature.button.click()
    app.qtbot.waitUntil(lambda: not app.feature.busy, timeout=3000)
    assert [part.name for part in seen[0]] == ["Плата MB-15"]


def test_works_without_compare(tmp_path, qtbot):
    result = App(tmp_path, qtbot, features=("add_folder",))
    try:
        result.click(result.data())
        assert len(result.svc.get("folders").recent()) == 1
    finally:
        result.stop()


def test_button_added_to_features_config():
    names = [item["id"] for item in json.loads((REPO / "config" / "features.json").read_text(encoding="utf-8"))["features"]]
    assert "add_folder" in names


def test_error_message_is_in_warning_role_and_hint_is_not(qtbot):
    dialog = make_dialog(qtbot, scan=lambda path: ([], "Папка недоступна"))
    assert dialog.status.property("role") == "muted"
    dialog.set_path(PATH)
    qtbot.waitUntil(lambda: dialog.status.text() == "Папка недоступна", timeout=3000)
    assert dialog.status.property("role") == "warn"
    dialog.set_path("")
    assert dialog.status.property("role") == "muted"
