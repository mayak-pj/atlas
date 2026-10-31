"""Проверка базы: её вердикту будем верить на выезде, поэтому важнее всего, что она ловит потери."""
import sqlite3
import subprocess
import sys
from pathlib import Path

from atlas import dbcheck
from atlas.dbcheck import DB_NAME, percentile, run_check

REPO = Path(__file__).resolve().parent.parent


class FakeTime:
    """Быстрые часы: sleep двигает время, тест не ждёт."""

    def __init__(self):
        self.now = 0.0

    def clock(self):
        self.now += 0.001
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _text(report_dir, label):
    return (report_dir / "dbcheck_{}.txt".format(label)).read_text(encoding="utf-8-sig")


def _check(folder, report_dir, label="pc1", **kwargs):
    fake = FakeTime()
    return run_check(folder, report_dir, 2, label, 0.5, clock=fake.clock, sleep=fake.sleep, **kwargs)


def test_percentile():
    assert percentile([3, 1, 2], 0.5) == 2
    assert percentile([1], 0.95) == 1
    assert percentile([1, 2], 1.0) == 2


def test_clean_run_reports_intact_data(tmp_path):
    folder = tmp_path / "Общая папка"
    folder.mkdir()
    assert _check(folder, tmp_path / "out") == 0
    text = _text(tmp_path / "out", "pc1")
    assert "ДАННЫЕ ЦЕЛЫ" in text
    assert "потеряно: 0" in text
    assert "Журнал: delete" in text
    assert "медиана" in text


def test_missing_folder_is_failure_and_is_not_created(tmp_path):
    folder = tmp_path / "нет такой"
    assert _check(folder, tmp_path / "out") == 1
    assert not folder.exists()
    assert "папка не найдена" in _text(tmp_path / "out", "pc1")


def test_lost_acknowledged_row_is_detected(tmp_path, monkeypatch):
    """Запись подтверждена, но в базе её нет: ровно то, что может случиться при обрыве сети."""
    folder = tmp_path / "папка"
    folder.mkdir()
    real_verify = dbcheck._verify

    def verify_after_loss(db, run_id, clock, sleep, timeout):
        db.write(lambda conn: conn.execute("DELETE FROM dbcheck_rows WHERE seq=1"))
        return real_verify(db, run_id, clock, sleep, timeout)

    monkeypatch.setattr(dbcheck, "_verify", verify_after_loss)
    assert _check(folder, tmp_path / "out") == 1
    text = _text(tmp_path / "out", "pc1")
    assert "потеряно: 1" in text
    assert "ИТОГ: ОШИБКА" in text


def test_network_outage_is_survived_and_timed(tmp_path, monkeypatch):
    folder = tmp_path / "папка"
    folder.mkdir()
    fake = FakeTime()
    real_connect = sqlite3.connect
    calls = {"count": 0}

    def flaky_connect(*args, **kwargs):
        calls["count"] += 1
        if 4 <= calls["count"] <= 7:
            raise sqlite3.OperationalError("disk I/O error")
        return real_connect(*args, **kwargs)

    monkeypatch.setattr("atlas.core.db.sqlite3.connect", flaky_connect)
    code = run_check(folder, tmp_path / "out", 5, "pc1", 0.5, clock=fake.clock, sleep=fake.sleep)
    text = _text(tmp_path / "out", "pc1")
    assert code == 0, text
    assert "Сбой: disk I/O error" in text
    assert "Перерывы: нет" not in text
    assert "ДАННЫЕ ЦЕЛЫ" in text


def test_second_run_is_visible_in_same_database(tmp_path):
    folder = tmp_path / "папка"
    folder.mkdir()
    assert _check(folder, tmp_path / "out", "pc1") == 0
    assert _check(folder, tmp_path / "out", "pc2") == 0
    assert "Других запусков в этой базе: 1" in _text(tmp_path / "out", "pc2")
    assert (folder / DB_NAME).is_file()


def test_two_real_processes_lose_nothing(tmp_path):
    folder = tmp_path / "Общая папка"
    folder.mkdir()
    out = tmp_path / "out"
    processes = [
        subprocess.Popen(
            [sys.executable, "-m", "atlas", "--dbcheck", str(folder), "--report", str(out),
             "--seconds", "3", "--label", label],
            cwd=str(REPO),
        )
        for label in ("pc1", "pc2")
    ]
    codes = [process.wait(timeout=60) for process in processes]
    assert codes == [0, 0], _text(out, "pc1") + _text(out, "pc2")
    assert "потеряно: 0" in _text(out, "pc1")
    assert "потеряно: 0" in _text(out, "pc2")
