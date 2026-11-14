"""Замер запуска (14.11.2026): части запуска и время до Python пишутся в журнал одной строкой."""
import logging

from atlas.core import startup


def test_timer_counts_steps_and_time_before_python(caplog):
    ticks = iter([10.0, 12.5, 13.0, 20.0])
    timer = startup.StartupTimer(clock=lambda: next(ticks), age=lambda: 4.0)
    timer.mark("Qt")
    timer.mark("база и ядро")
    timer.mark("функции")
    assert timer.steps == [("Qt", 2.5), ("база и ядро", 0.5), ("функции", 7.0)]
    assert timer.total() == 14.0
    with caplog.at_level(logging.INFO, logger="atlas.startup"):
        timer.log()
    assert "до Python 4.0 с, Qt 2.5 с, база и ядро 0.5 с, функции 7.0 с; всего 14.0 с" in caplog.text


def test_timer_without_process_age():
    timer = startup.StartupTimer(clock=iter([1.0, 2.0]).__next__, age=lambda: None)
    timer.mark("Qt")
    assert timer.text() == "Запуск: Qt 1.0 с; всего 1.0 с"


def test_process_age_is_none_off_windows(monkeypatch):
    monkeypatch.setattr(startup.sys, "platform", "darwin")
    assert startup.process_age() is None


def test_registry_records_start_time_of_each_feature(tmp_path, qtbot):
    from tests.test_rules import App
    app = App(tmp_path, qtbot)
    try:
        assert set(app.registry.timings) >= {"compare", "rules"}
        assert all(seconds >= 0 for seconds in app.registry.timings.values())
    finally:
        app.stop()


def test_home_from_env_only_for_real_installation(tmp_path):
    from atlas.core.config import home_from_env
    home = tmp_path / "Атлас"
    assert home_from_env({}) is None and home_from_env({"ATLAS_HOME": "  "}) is None
    assert home_from_env({"ATLAS_HOME": str(home)}) is None  # нет release\version.txt — не установка
    (home / "release").mkdir(parents=True)
    (home / "release" / "version.txt").write_text("0.10.31", encoding="utf-8")
    assert home_from_env({"ATLAS_HOME": '"{}"'.format(home)}) == home


def test_local_launcher_is_published_next_to_atlas_bat():
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / "packaging" / "install" / "Atlas_local.bat").read_bytes()
    assert b"\r\n" in text and b"ATLAS_HOME" in text and b"robocopy" in text
