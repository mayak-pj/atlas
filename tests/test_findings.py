"""findings (5.1): логика сводки и панель в слоте compare.right."""
import json
import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from atlas.app import build_core, build_window, start_features
from atlas.core.config import AppPaths
from atlas.core.domain.folders import MarkedPhoto
from atlas.features.findings import logic

REPO = Path(__file__).resolve().parent.parent


# --- логика ---------------------------------------------------------------------------------
def record(number, kind, type_no, text, created, archived=None):
    return SimpleNamespace(id=number, kind=kind, type_no=type_no, description=text, created_at=created, archived_at=archived)


def test_types_one_line_per_number_with_earliest_date_and_newest_text():
    lines = logic.build_types([
        record(1, "type", 2, "с 3-м чипом", "2026-10-14 10:00:00"),
        record(2, "type", 1, "старое описание", "2025-03-01 10:00:00"),
        record(3, "type", 1, "без 3-го чипа", "2025-06-01 10:00:00"),
        record(4, "defect", None, "пример дефекта", "2026-01-01 10:00:00"),
    ])
    assert [(item.type_no, item.text, item.since) for item in lines] == [
        (1, "без 3-го чипа", "2025-03-01"), (2, "с 3-м чипом", "2026-10-14"),
    ]


def test_type_is_archived_only_if_every_record_is():
    both = logic.build_types([record(1, "type", 1, "a", "2025-01-01 00:00:00", "2026-01-01 00:00:00"),
                              record(2, "type", 1, "a", "2025-02-01 00:00:00")])
    one = logic.build_types([record(1, "type", 1, "a", "2025-01-01 00:00:00", "2026-01-01 00:00:00")])
    assert not both[0].archived and one[0].archived


def mark(number, kind, when, sn="S1", defect_kind=None, by=1):
    return MarkedPhoto(number, 1, 1, "2026-10-01", "a.jpg", sn, kind, defect_kind, by, when)


def test_findings_are_limited_but_counted_in_full():
    marks = [mark(3, "defect", "2026-10-14 10:00:00"), mark(2, "remark", "2026-10-09 10:00:00"), mark(1, "defect", "2026-10-02 10:00:00")]
    lines, total, defects, remarks = logic.build_findings(marks, {1: "Петров"}, limit=2)
    assert (len(lines), total, defects, remarks) == (2, 3, 2, 1)
    assert lines[0].author == "Петров" and lines[0].sn == "S1"


def test_dates_show_year_only_when_not_current():
    today = datetime(2026, 11, 1)
    assert logic.short_date("2026-10-14 09:00:00", today) == "14.10"
    assert logic.short_date("2025-10-14", today) == "14.10.2025"
    assert logic.full_date("2025-03-01 10:00:00") == "01.03.2025"
    assert logic.short_date(None) == ""


def test_title_falls_back_to_word_for_mark():
    assert logic.finding_title(logic.FindingLine("defect", "S", "", "2026-10-14", "")) == "дефект"
    assert logic.finding_title(logic.FindingLine("remark", "S", "", "2026-10-14", "")) == "замечание"
    assert logic.finding_title(logic.FindingLine("defect", "S", "Размытое фото", "2026-10-14", "")) == "Размытое фото"


# --- в приложении -------------------------------------------------------------------------------
class App:
    def __init__(self, tmp_path, qtbot, features=("compare", "findings", "type_db")):
        root = tmp_path / "Атлас"
        (root / "config").mkdir(parents=True)
        shutil.copy(str(REPO / "config" / "app.json"), str(root / "config" / "app.json"))
        (root / "config" / "features.json").write_text(
            json.dumps({"features": [{"id": name} for name in features]}), encoding="utf-8")
        local = {"image_cache": {"disk_dir": str(tmp_path / "кэш")}, "type_db": {"dir": str(tmp_path / "типы")}}
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
        self.user = self.svc.get("users").add("Петров", lambda count: "#7DB4FF")

    def feature(self, name):
        return next(item.instance for item in self.registry.loaded if item.spec.id == name)

    def folder(self, name, project="Орион-24", device="N15", date="2026-10-01", photos=("a", "b")):
        part_row = self.svc.get("parts").ensure("A", project, device, name)
        folder = self.svc.get("folders").add(part_row.id, str(self.root / "Сеть" / project / device / name / date), date)
        self.svc.get("folders").add_photos(folder.id, ["{}.jpg".format(item) for item in photos])
        return folder

    def mark(self, folder, index, mark_name, sn="S1", kind=None, when=None):
        service = self.svc.get("folders")
        photo = service.photos(folder.id)[index]
        service.mark_photo(photo.id, mark_name, sn, self.user.id, kind)
        if when:
            self.ctx.db.write(lambda conn: conn.execute("UPDATE photos SET marked_at = ? WHERE id = ?", (when, photo.id)))

    def finish(self, folder, when):
        self.svc.get("folders").set_status(folder.id, "done", self.user.id)
        self.ctx.db.write(lambda conn: conn.execute("UPDATE folders SET status_at = ? WHERE id = ?", (when, folder.id)))

    def open(self, folder):
        self.ctx.bus.publish("folder.opened", {"folder_id": folder.id, "part_id": folder.part_id})
        feature = self.feature("findings")
        self.qtbot.waitUntil(lambda: feature._thread is None and not feature._again and feature.panel.summary is not None
                             and feature.panel.summary.part_id == folder.part_id, timeout=3000)
        return feature.panel.summary

    def stop(self):
        self.registry.stop_all()


@pytest.fixture
def app(tmp_path, qtbot):
    result = App(tmp_path, qtbot)
    yield result
    result.stop()


def test_summary_collects_findings_of_other_folders_and_last_check(app):
    old = app.folder("SSD XS-2280", date="2026-10-01")
    now = app.folder("SSD XS-2280", date="2026-10-20")
    app.mark(old, 0, "defect", "S4K2-0388", "Размытое фото", "2026-10-14 10:00:00")
    app.mark(old, 1, "remark", "S4K2-0352", None, "2026-10-09 10:00:00")
    app.mark(now, 0, "defect", "S4K2-0001", None, "2026-10-20 10:00:00")  # текущая папка в сводку не входит
    app.finish(old, "2026-10-28 18:00:00")
    summary = app.open(now)
    assert [(item.sn, item.kind_text, item.author) for item in summary.findings] == [
        ("S4K2-0388", "Размытое фото", "Петров"), ("S4K2-0352", "", "Петров")]
    assert (summary.total, summary.defects, summary.remarks) == (2, 1, 1)
    assert summary.last_check.when == "2026-10-28 18:00:00" and summary.last_check.author == "Петров"


def test_summary_joins_same_name_from_other_projects_and_devices(app):
    here = app.folder("SSD XS-2280 512GB", project="Орион-24")
    other = app.folder("ssd_xs 2280 512gb", project="Вега-3", device="K9", date="2026-09-01")
    app.mark(other, 0, "defect", "S9", None, "2026-09-05 10:00:00")
    assert app.open(here).total == 1


def test_longer_or_similar_name_is_other_part(app):
    here = app.folder("SSD XS-2280")
    app.mark(app.folder("SSD XS-2280 512GB", project="Вега-3"), 0, "defect", "S9", None, "2026-09-05 10:00:00")
    app.mark(app.folder("SSD XS-2281", project="Вега-4"), 0, "defect", "S8", None, "2026-09-05 10:00:00")
    assert app.open(here).total == 0


def test_summary_days_window(app):
    folder = app.folder("Плата MB-15")
    app.mark(folder, 0, "defect", "S1", None, "2026-01-01 10:00:00")
    app.mark(folder, 1, "defect", "S2", None, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    service = app.svc.get("findings")
    assert service.summary(folder.part_id).total == 2
    assert service.summary(folder.part_id, days=30).total == 1
    assert service.summary(folder.part_id, exclude_folder_id=folder.id).total == 0
    assert service.summary(99999) is None


def test_types_come_from_type_db_with_archive(app):
    folder = app.folder("Плата MB-15")
    repo = app.feature("type_db").repo
    repo.add(folder.part_id, "type", 1, "без 3-го чипа", None, "p1.jpg", None, None, None, app.user.id)
    second = repo.add(folder.part_id, "type", 2, "с 3-м чипом", None, "p2.jpg", None, None, None, app.user.id)
    repo.set_archived(second, True, app.user.id)
    summary = app.open(folder)
    assert [(item.type_no, item.archived) for item in summary.types] == [(1, False), (2, True)]


def test_panel_shows_texts(app):
    folder = app.folder("Плата MB-15")
    app.mark(folder, 0, "defect", "S1", None, "2026-10-14 10:00:00")
    other = app.folder("Плата MB-15", date="2026-10-30")
    summary = app.open(other)
    panel = app.feature("findings").panel
    from PyQt5.QtWidgets import QLabel
    texts = [label.text() for label in panel.findChildren(QLabel)]
    assert "Плата MB-15" in texts and "S1" in texts and "дефект" in texts
    assert panel.last_check_text(summary) == "Раньше эта деталь не проверялась"


def test_panel_lives_in_compare_right_slot(app):
    panel = app.feature("findings").panel
    assert panel in app.window.slots.panels("compare.right")


def test_app_starts_without_type_db(tmp_path, qtbot):
    result = App(tmp_path, qtbot, features=("compare", "findings"))
    try:
        folder = result.folder("Плата MB-15")
        assert result.open(folder).types is None
    finally:
        result.stop()


def test_old_texts_disappear_when_summary_replaced(qtbot):
    from PyQt5.QtWidgets import QLabel
    from atlas.features.findings.ui import FindingsPanel, TEXT_NO_FOLDER
    panel = FindingsPanel()
    qtbot.addWidget(panel)
    panel.show()
    summary = logic.Summary(1, "Плата", (), (), 0, 0, 0, None)
    panel.show_summary(summary)
    assert TEXT_NO_FOLDER not in [label.text() for label in panel.findChildren(QLabel) if label.isVisibleTo(panel)]


# --- «Проблемная деталь» (5.2) ----------------------------------------------------------------
NOW = datetime(2026, 11, 1, 12, 0, 0)


def test_problem_counts_defects_and_remarks_inside_window():
    marks = [mark(4, "defect", "2026-10-30 10:00:00"), mark(3, "remark", "2026-10-29 10:00:00"),
             mark(2, "remark", "2026-05-20 10:00:00"), mark(1, "defect", "2025-01-01 10:00:00")]
    problem = logic.problem_of(marks, 180, 1, NOW)
    assert (problem.count, problem.days, problem.last) == (3, 180, "2026-10-30 10:00:00")


def test_one_remark_or_one_defect_is_enough():
    assert logic.problem_of([mark(1, "remark", "2026-10-30 10:00:00")], 180, 1, NOW).count == 1
    assert logic.problem_of([mark(1, "defect", "2026-10-30 10:00:00")], 180, 1, NOW).count == 1
    assert logic.problem_of([], 180, 1, NOW) is None


def test_problem_respects_minimum_and_old_marks():
    marks = [mark(2, "remark", "2026-10-30 10:00:00"), mark(1, "defect", "2025-01-01 10:00:00")]
    assert logic.problem_of(marks, 180, 2, NOW) is None
    assert logic.problem_of(marks, 1000, 2, NOW).count == 2
    assert logic.problem_of(marks, 180, 0, NOW).count == 1  # 0 в настройке считается как 1


def test_default_window_is_180_days():
    assert logic.DEFAULT_PROBLEM_DAYS == 180


def test_settings_numbers_are_checked():
    assert logic.positive_int("7", 30) == 7
    assert logic.positive_int(0, 30) == 30 and logic.positive_int("x", 30) == 30 and logic.positive_int(None, 30) == 30


@pytest.mark.parametrize("number, word", [(1, "замечание"), (2, "замечания"), (5, "замечаний"), (11, "замечаний"), (21, "замечание"), (112, "замечаний")])
def test_plural(number, word):
    assert logic.plural(number, logic.MARK_FORMS) == word


def test_texts():
    problem = logic.Problem(3, 180, "2026-10-14 10:00:00")
    assert logic.problem_text(problem, NOW) == "3 замечания за 180 дней · последнее 14.10"
    assert logic.notice_text("SSD", problem, NOW) == "SSD: ранее были замечания — 3 замечания за 180 дней, последнее 14.10. Будьте внимательнее."


def recent_stamp(days_ago):
    from datetime import timedelta
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


def alert_texts(panel):
    from PyQt5.QtWidgets import QLabel
    return [label.text() for label in panel.findChildren(QLabel) if label.property("role") in ("alert-title", "alert-text")
            and label.isVisibleTo(panel)]


def test_banner_and_notice_for_part_with_recent_marks(app):
    old = app.folder("Плата MB-15", date="2026-10-01")
    app.mark(old, 0, "defect", "S1", None, recent_stamp(3))
    app.mark(old, 1, "remark", "S2", None, recent_stamp(100))
    messages = []
    app.window.statusBar().messageChanged.connect(messages.append)
    summary = app.open(app.folder("Плата MB-15", date="2026-10-30"))
    assert summary.problem.count == 2
    texts = alert_texts(app.feature("findings").panel)
    assert texts[0] == "Ранее были замечания — будьте внимательнее" and texts[1].startswith("2 замечания за 180 дней")
    app.qtbot.waitUntil(lambda: any("Будьте внимательнее" in text for text in messages), timeout=2000)


def test_no_banner_when_marks_are_older_than_window(app):
    old = app.folder("Плата MB-15", date="2026-10-01")
    app.mark(old, 0, "defect", "S1", None, recent_stamp(200))
    app.mark(old, 1, "remark", "S2", None, recent_stamp(400))
    messages = []
    app.window.statusBar().messageChanged.connect(messages.append)
    summary = app.open(app.folder("Плата MB-15", date="2026-10-30"))
    assert summary.problem is None and alert_texts(app.feature("findings").panel) == []
    assert not any("Будьте внимательнее" in text for text in messages)


def test_notice_once_per_opening_not_per_reload(app):
    old = app.folder("Плата MB-15", date="2026-10-01")
    app.mark(old, 0, "defect", "S1", None, recent_stamp(2))
    opened = app.folder("Плата MB-15", date="2026-10-30")
    messages = []
    app.window.statusBar().messageChanged.connect(messages.append)
    app.open(opened)
    feature = app.feature("findings")
    app.ctx.bus.publish("folder.done", {"folder_id": old.id})
    app.qtbot.waitUntil(lambda: feature._thread is None and not feature._again, timeout=3000)
    app.qtbot.wait(100)
    assert len([text for text in messages if "Будьте внимательнее" in text]) == 1


def test_current_folder_marks_do_not_make_part_problem(app):
    folder = app.folder("Плата MB-15")
    app.mark(folder, 0, "defect", "S1", None, recent_stamp(0))
    assert app.open(folder).problem is None


def test_problem_window_from_config(app):
    old = app.folder("Плата MB-15", date="2026-10-01")
    app.mark(old, 0, "defect", "S1", None, recent_stamp(250))
    app.ctx.config.app.setdefault("findings", {})["problem_days"] = 365
    assert app.open(app.folder("Плата MB-15", date="2026-10-30")).problem.days == 365


def test_last_check_not_duplicated_under_banner(app):
    from PyQt5.QtWidgets import QLabel
    old = app.folder("Плата MB-15", date="2026-10-01")
    app.mark(old, 0, "defect", "S1", None, recent_stamp(2))
    app.finish(old, recent_stamp(1))
    app.open(app.folder("Плата MB-15", date="2026-10-30"))
    texts = [label.text() for label in app.feature("findings").panel.findChildren(QLabel) if label.isVisibleTo(app.feature("findings").panel)]
    assert len([text for text in texts if text.startswith("Последняя проверка")]) == 1
