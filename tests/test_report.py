"""report (8.2): колонки Excel, запись .xlsx, письмо по шаблону, кнопки в слоте черновика, папка → готово."""
import json
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from atlas.app import build_core, build_window, start_features
from atlas.core.config import AppPaths
from atlas.features.draft.logic import Entry
from atlas.features.report import logic, xlsx

REPO = Path(__file__).resolve().parent.parent
CTX = {"part": "SSD <XS>", "device": "N15", "project": "Орион", "date": "01.10.2026", "photos_total": 5, "user": "Петров"}


def entries():
    return [Entry("type:1", "type", 1, "", 3), Entry("type:2", "type", 2, "S1", 2, text="3-й чип"),
            Entry("photo:9", "defect", None, "S4", 1, text="сбит"),
            Entry("manual:1", "remark", None, "S7", 1, kind_text="Размытое фото", text="переснять", manual_id=1)]


# --- логика ---------------------------------------------------------------------------------
def test_templates_in_repo_are_valid():
    sheet, columns = logic.load_columns(REPO / "templates")
    assert sheet and [c[0] for c in columns][:3] == ["date", "project", "device"]
    assert "${part}" in logic.load_mail(REPO / "templates")
    assert "TODO" not in logic.load_mail(REPO / "templates")  # комментарий вырезан


def test_missing_or_broken_templates_fall_back(tmp_path):
    assert logic.load_columns(tmp_path)[1] == list(logic.DEFAULT_COLUMNS)
    (tmp_path / "excel_columns.json").write_text('{"columns": [{"key": "нет", "title": "x"}]}', encoding="utf-8")
    assert logic.load_columns(tmp_path)[1] == list(logic.DEFAULT_COLUMNS)
    assert logic.load_mail(tmp_path) == logic.DEFAULT_MAIL


def test_rows_follow_column_order():
    columns = [("kind", "Что", 1), ("sn", "SN", 1), ("photos", "Фото", 1)]
    assert logic.rows(entries(), CTX, columns) == [["Тип", "", 3], ["Тип", "S1", 2], ["Дефект", "S4", ""],
                                                   ["Замечание", "S7", ""]]


def test_mail_is_escaped_and_complete():
    html = logic.render(logic.load_mail(REPO / "templates"), logic.mail_values(entries(), CTX, "заметка\nвторая"))
    assert "SSD &lt;XS&gt;" in html and "Тип 1: 3, Тип 2: 2 (3-й чип)" in html
    assert "SN S4 — сбит" in html and "SN S7 — Размытое фото; переснять" in html
    assert "заметка<br>вторая" in html and "Петров" in html and "${" not in html
    assert "типов не отмечено" in logic.mail_values([], CTX)["types_line"]


def test_subject_and_file_name():
    assert logic.subject("RE: ${part}, ${date}", CTX) == "RE: SSD <XS>, 01.10.2026"
    assert logic.file_name(CTX, "120000") == "SSD_XS_01.10.2026_120000.xlsx"
    assert logic.date_text("2026-10-01") == "01.10.2026"


def test_xlsx_is_valid_zip_with_text(tmp_path):
    path = tmp_path / "a.xlsx"
    xlsx.write(path, "Лист:1", ["Деталь", "Фото"], [["A & B\x01", 3]], [20, 8])
    with zipfile.ZipFile(str(path)) as archive:
        assert archive.testzip() is None
        sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        assert "A &amp; B" in sheet and "<v>3</v>" in sheet and "\x01" not in sheet
        assert "Лист 1" in archive.read("xl/workbook.xml").decode("utf-8")
    assert xlsx.column_name(0) == "A" and xlsx.column_name(26) == "AA"


# --- в приложении ---------------------------------------------------------------------------
class App:
    def __init__(self, tmp_path, qtbot, features=("compare", "draft", "report")):
        root = tmp_path / "Атлас"
        (root / "config").mkdir(parents=True)
        shutil.copy(str(REPO / "config" / "app.json"), str(root / "config" / "app.json"))
        (root / "config" / "features.json").write_text(
            json.dumps({"features": [{"id": name} for name in features]}), encoding="utf-8")
        local = {"image_cache": {"disk_dir": str(tmp_path / "кэш")},
                 "report": {"excel_dir": str(tmp_path / "отчёты"), "work_dir": str(tmp_path / "письмо")}}
        (root / "config" / "local.json").write_text(json.dumps(local), encoding="utf-8")
        self.ctx = build_core(AppPaths(root))
        self.qtbot, self.tmp = qtbot, tmp_path
        self.svc = self.ctx.services
        self.registry = start_features(self.ctx)
        assert self.registry.failures == []
        self.window = build_window(self.registry)
        qtbot.addWidget(self.window)
        self.window.show()
        self.ctx.user = self.svc.get("users").add("Петров", lambda count: "#7DB4FF")
        self.feature = next(i.instance for i in self.registry.loaded if i.spec.id == "report")
        self.feature.excel_shown = []
        self.feature._show_file = self.feature.excel_shown.append

    def wait_idle(self):
        f = self.feature
        self.qtbot.waitUntil(lambda: not f._busy and not any(t.is_alive() for t in f._threads), timeout=5000)

    def open_folder(self):
        part = self.svc.get("parts").ensure("A", "Орион", "N15", "SSD")
        folder = self.svc.get("folders").add(part.id, str(self.tmp / "Сеть" / "SSD" / "2026-10-01"), "2026-10-01")
        self.svc.get("folders").add_photos(folder.id, ["1.jpg", "2.jpg"])
        photo = self.svc.get("folders").photos(folder.id)[0]
        self.svc.get("folders").mark_photo(photo.id, "type:1", user_id=self.ctx.user.id)
        self.ctx.bus.publish("folder.opened", {"folder_id": folder.id, "part_id": part.id})
        return folder


@pytest.fixture
def app(tmp_path, qtbot):
    result = App(tmp_path, qtbot)
    yield result
    result.registry.stop_all()


def test_buttons_live_in_draft_slot_and_need_folder(app):
    assert app.feature.panel is not None and app.window.slots.has_slot("draft.actions")
    assert not app.feature.panel.excel_button.isEnabled()
    app.open_folder()
    assert app.feature.panel.mail_button.isEnabled()


def test_preview_shows_letter(app):
    app.open_folder()
    app.qtbot.waitUntil(lambda: "Тип 1: 1" in app.feature.panel.view.toPlainText(), timeout=5000)
    assert app.feature.panel.subject.text().startswith("Тема: RE: SSD, 01.10.2026")


def test_excel_written(app):
    app.open_folder()
    app.feature.write_excel()
    app.wait_idle()
    files = list((app.tmp / "отчёты").glob("*.xlsx"))
    assert len(files) == 1 and app.feature.excel_shown == [str(files[0])]
    with zipfile.ZipFile(str(files[0])) as archive:
        assert "SSD" in archive.read("xl/worksheets/sheet1.xml").decode("utf-8")


def test_mail_opens_and_folder_becomes_done(app):
    folder = app.open_folder()
    done = []
    app.ctx.bus.subscribe("folder.done", done.append)
    app.feature.open_mail()
    app.wait_idle()
    assert (app.tmp / "письмо" / "last_mail.html").read_text(encoding="utf-8").startswith("<!-- Тема: RE: SSD")
    assert app.svc.get("folders").get(folder.id).status == "done"
    assert done == [{"folder_id": folder.id}]


def test_failure_keeps_folder_open(app, monkeypatch):
    folder = app.open_folder()
    from atlas.features.report import outlook_fake

    def boom(*args, **kw):
        raise RuntimeError("Outlook не отвечает")

    monkeypatch.setattr(outlook_fake, "open_mail", boom)
    app.feature.open_mail()
    app.wait_idle()
    assert app.svc.get("folders").get(folder.id).status != "done"


def test_without_draft_no_panel(tmp_path, qtbot):
    result = App(tmp_path, qtbot, features=("compare", "report"))
    try:
        assert result.feature.panel is None
    finally:
        result.registry.stop_all()
