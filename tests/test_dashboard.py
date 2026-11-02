"""dashboard (9.1): границы периода, сбор цифр, экран в приложении, столбики."""
import json
import shutil
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from atlas.app import build_core, build_window, start_features
from atlas.core.config import AppPaths
from atlas.core.domain.folders import Activity
from atlas.features.dashboard import logic
from atlas.features.dashboard.charts import BarChart

REPO = Path(__file__).resolve().parent.parent


def part(pid, name, kind="A"):
    return SimpleNamespace(id=pid, name=name, kind=kind)


# --- логика ---------------------------------------------------------------------------------
def test_period_ranges():
    today = date(2026, 10, 15)  # четверг
    assert logic.period_range(logic.WEEK, today)[:2] == ("2026-10-12 00:00:00", "2026-10-19 00:00:00")
    assert logic.period_range(logic.MONTH, today) == ("2026-10-01 00:00:00", "2026-11-01 00:00:00", "Октябрь 2026")
    assert logic.period_range(logic.MONTH, date(2026, 12, 3))[1] == "2027-01-01 00:00:00"
    assert logic.period_range(logic.YEAR, today)[:2] == ("2026-01-01 00:00:00", "2027-01-01 00:00:00")
    assert logic.clean_range(today)[1] == "2026-10-16 00:00:00"


def test_build_counts_top_kinds_and_clean_parts():
    parts = {1: part(1, "SSD"), 2: part(2, "Дисплей"), 3: part(3, "Wi-Fi", "B"), 4: part(4, "Динамик")}
    period = Activity(done=[(10, 1, 20), (11, 2, 5), (12, 3, 7)],
                      problems=[(1, "Размытое фото"), (1, "Размытое фото"), (2, None), (3, "Царапина")])
    clean = Activity(done=[(10, 1, 20), (11, 2, 5), (12, 3, 7), (13, 4, 9)], problems=[(1, "x"), (2, None)])
    everything = logic.build(parts, period, clean, [1, 3, 3], logic.ALL_KINDS, "Октябрь 2026", "за месяц")
    assert (everything.folders, everything.photos, everything.problems, everything.problem_parts) == (3, 32, 4, 3)
    assert everything.new_types == 3
    assert everything.top_parts[0] == ("SSD", 2)
    assert dict(everything.kinds) == {"Размытое фото": 2, logic.NO_KIND: 1, "Царапина": 1}
    assert everything.clean_parts == ["Wi-Fi", "Динамик"]
    only_b = logic.build(parts, period, clean, [1, 3, 3], "B")
    assert (only_b.folders, only_b.problems, only_b.new_types, only_b.clean_parts) == (1, 1, 2, ["Wi-Fi"])


def test_clean_list_is_limited():
    parts = {i: part(i, "Д{:03d}".format(i)) for i in range(1, 41)}
    clean = Activity(done=[(i, i, 1) for i in range(1, 41)], problems=[])
    stats = logic.build(parts, Activity([], []), clean, [])
    assert len(stats.clean_parts) == logic.CLEAN_LIMIT and stats.clean_more == 10


# --- столбики -------------------------------------------------------------------------------
def test_bar_chart_paints_rows_and_empty(qtbot):
    chart = BarChart()
    qtbot.addWidget(chart)
    chart.resize(500, 40)
    chart.set_rows([("SSD", 9), ("Дисплей", 3)])
    assert chart.height() == 2 * 26 and chart.rows() == [("SSD", 9), ("Дисплей", 3)]
    assert not chart.grab().isNull()
    chart.set_rows([])
    assert not chart.grab().isNull()


# --- в приложении ---------------------------------------------------------------------------
class App:
    def __init__(self, tmp_path, qtbot):
        root = tmp_path / "Атлас"
        (root / "config").mkdir(parents=True)
        shutil.copy(str(REPO / "config" / "app.json"), str(root / "config" / "app.json"))
        (root / "config" / "features.json").write_text(json.dumps({"features": [{"id": "dashboard"}]}),
                                                       encoding="utf-8")
        (root / "config" / "local.json").write_text(
            json.dumps({"image_cache": {"disk_dir": str(tmp_path / "кэш")}}), encoding="utf-8")
        self.ctx = build_core(AppPaths(root))
        self.qtbot, self.svc = qtbot, self.ctx.services
        self.registry = start_features(self.ctx)
        assert self.registry.failures == []
        self.window = build_window(self.registry)
        qtbot.addWidget(self.window)
        self.window.show()
        self.feature = next(item.instance for item in self.registry.loaded if item.spec.id == "dashboard")
        self.screen = self.feature.screen

    def idle(self):
        f = self.feature
        self.qtbot.waitUntil(lambda: not f._reading and not f._again and not f.reload_timer.isActive(), timeout=4000)


@pytest.fixture
def app(tmp_path, qtbot):
    result = App(tmp_path, qtbot)
    yield result
    result.registry.stop_all()


def test_screen_shows_numbers_without_type_db(app):
    part_ = app.svc.get("parts").ensure("A", "Орион", "N15", "SSD")
    folders = app.svc.get("folders")
    folder = folders.add(part_.id, "/x/SSD/2026", "2026-10-01")
    folders.add_photos(folder.id, ["1.jpg", "2.jpg"])
    photo = folders.photos(folder.id)[0]
    folders.mark_photo(photo.id, "remark", sn="S1", user_id=None, defect_kind="Размытое фото")
    folders.set_status(folder.id, "done")
    app.feature.reload()
    app.idle()
    screen = app.screen
    assert screen.kpi_folders.value.text() == "1" and screen.kpi_photos.value.text() == "2"
    assert screen.kpi_problems.value.text() == "1" and screen.kpi_types.value.text() == "0"
    assert screen.top_chart.rows() == [("SSD", 1)] and screen.kinds_chart.rows() == [("Размытое фото", 1)]
    assert not screen.clean_empty.isHidden()  # у детали замечание — «без проблем» пусто
    screen.kind_buttons["B"].click()
    app.idle()
    assert screen.kpi_folders.value.text() == "0"
    screen.period_buttons[logic.WEEK].click()
    app.idle()
    assert screen.title.text().startswith("Неделя")


def test_bus_event_refreshes_visible_tab(app):
    part_ = app.svc.get("parts").ensure("A", "Орион", "N15", "SSD")
    folder = app.svc.get("folders").add(part_.id, "/x/SSD/2026", "2026-10-01")
    app.feature.reload()
    app.idle()
    assert app.screen.kpi_folders.value.text() == "0"
    app.svc.get("folders").set_status(folder.id, "done")
    app.ctx.bus.publish("folder.done", {"folder_id": folder.id})
    app.qtbot.waitUntil(lambda: app.screen.kpi_folders.value.text() == "1", timeout=4000)
