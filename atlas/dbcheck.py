"""Проверка SQLite на сетевом диске: atlas.exe --dbcheck ПАПКА [--report ПАПКА] [--seconds N] [--label ИМЯ].

Запускается на одном или двух ПК одновременно с одной и той же папкой. Во время работы можно отключить сеть:
программа продолжит попытки и после восстановления проверит, что все подтверждённые записи на месте.
Работает с отдельным файлом atlas_dbcheck.sqlite, рабочую базу не трогает. Qt не нужен.
"""
from __future__ import annotations

import platform
import re
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path

from atlas.core.db import Database, DatabaseBusyError
from atlas.core.report import TextReport

DB_NAME = "atlas_dbcheck.sqlite"
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NO_REPORT = 3
VERIFY_TIMEOUT_S = 120
_ERRORS = (sqlite3.Error, OSError)

_CREATE = (
    "CREATE TABLE IF NOT EXISTS dbcheck_rows ("
    "run_id TEXT NOT NULL, seq INTEGER NOT NULL, label TEXT NOT NULL, at TEXT NOT NULL, "
    "PRIMARY KEY (run_id, seq))"
)


def percentile(values, share):
    """Значение, ниже которого лежит доля share отсортированных замеров."""
    ordered = sorted(values)
    return ordered[min(int(len(ordered) * share), len(ordered) - 1)]


def _timing(name, values):
    if not values:
        return "{}: нет успешных замеров".format(name)
    return "{}: {} раз, медиана {:.0f} мс, 95% {:.0f} мс, максимум {:.0f} мс".format(
        name, len(values), percentile(values, 0.5) * 1000, percentile(values, 0.95) * 1000, max(values) * 1000
    )


class _Load:
    """Чередует чтение и запись, как рабочая программа, и запоминает подтверждённые записи."""

    def __init__(self, db, run_id, label, report, clock, sleep):
        self.db = db
        self.run_id = run_id
        self.label = label
        self.report = report
        self.clock = clock
        self.sleep = sleep
        self.acknowledged = set()
        self.reads = []
        self.writes = []
        self.busy = 0
        self.errors = 0
        self.outages = []
        self._outage_start = None

    def _insert(self, conn, seq):
        at = datetime.now().isoformat()
        conn.execute("INSERT OR IGNORE INTO dbcheck_rows VALUES (?, ?, ?, ?)", (self.run_id, seq, self.label, at))

    def _step(self, seq):
        started = self.clock()
        self.db.read(lambda conn: conn.execute("SELECT 1").fetchone())
        self.reads.append(self.clock() - started)
        started = self.clock()
        self.db.write(lambda conn: self._insert(conn, seq))
        self.writes.append(self.clock() - started)
        self.acknowledged.add(seq)  # только после COMMIT: это запись, которую программа сочла сохранённой

    def run(self, seconds, pause):
        deadline = self.clock() + seconds
        seq = 0
        while self.clock() < deadline:
            seq += 1
            try:
                self._step(seq)
            except DatabaseBusyError:
                self.busy += 1
            except _ERRORS as exc:
                self.errors += 1
                if self._outage_start is None:
                    self._outage_start = self.clock()
                    self.report.line("Сбой: {}".format(exc))
            else:
                self._close_outage()
            self.sleep(pause)
        self._close_outage()

    def _close_outage(self):
        if self._outage_start is not None:
            self.outages.append(self.clock() - self._outage_start)
            self._outage_start = None


def _verify(db, run_id, clock, sleep, timeout):
    """Итог из базы; сеть могла ещё не вернуться, поэтому с повторами."""

    def read(conn):
        rows = conn.execute("SELECT seq FROM dbcheck_rows WHERE run_id=?", (run_id,)).fetchall()
        others = conn.execute("SELECT COUNT(DISTINCT run_id) FROM dbcheck_rows WHERE run_id<>?", (run_id,)).fetchone()
        return {
            "present": {row[0] for row in rows},
            "others": others[0],
            "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "journal": conn.execute("PRAGMA journal_mode").fetchone()[0],
        }

    deadline = clock() + timeout
    while True:
        try:
            return db.read(read)
        except (DatabaseBusyError,) + _ERRORS:
            if clock() >= deadline:
                raise
            sleep(2)


def run_check(folder, report_dir, seconds=60, label=None, pause=0.1, clock=time.monotonic, sleep=time.sleep,
              verify_timeout=VERIFY_TIMEOUT_S):
    """Возвращает код выхода: 0 — данные целы, 1 — проблема, 3 — некуда писать отчёт."""
    label = label or platform.node() or "pc"
    report_dir = Path(report_dir)
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        report = TextReport(report_dir / "dbcheck_{}.txt".format(re.sub(r"[^\w-]", "_", label)))
    except OSError:
        return EXIT_NO_REPORT
    report.line("Проверка SQLite на сетевом диске")
    report.line("ПК: {}. Начало: {}".format(label, datetime.now().isoformat(timespec="seconds")))
    report.line("Папка: {}. SQLite {}. Длительность: {} с".format(folder, sqlite3.sqlite_version, seconds))
    folder = Path(folder)
    if not folder.is_dir():  # сетевую папку не создаём: опечатка дала бы проверку не там
        report.line("ИТОГ: ОШИБКА — папка не найдена")
        return EXIT_FAILED
    db = Database(folder / DB_NAME)
    run_id = "{}-{}".format(label, uuid.uuid4().hex[:8])
    try:
        db.write(lambda conn: conn.execute(_CREATE))
    except (DatabaseBusyError,) + _ERRORS as exc:
        report.line("ИТОГ: ОШИБКА — не удалось создать базу: {}".format(exc))
        return EXIT_FAILED
    load = _Load(db, run_id, label, report, clock, sleep)
    load.run(seconds, pause)
    report.line(_timing("Открытие и чтение", load.reads))
    report.line(_timing("Открытие и запись", load.writes))
    report.line("База занята дольше всех повторов: {}".format(load.busy))
    report.line("Ошибок сети и диска: {}".format(load.errors))
    report.line("Перерывы: {}".format(", ".join("{:.0f} с".format(item) for item in load.outages) or "нет"))
    try:
        result = _verify(db, run_id, clock, sleep, verify_timeout)
    except (DatabaseBusyError,) + _ERRORS as exc:
        report.line("ИТОГ: ОШИБКА — база недоступна после проверки: {}".format(exc))
        return EXIT_FAILED
    lost = sorted(load.acknowledged - result["present"])
    report.line("Подтверждено записей: {}, потеряно: {}".format(len(load.acknowledged), len(lost)))
    report.line("Других запусков в этой базе: {}".format(result["others"]))
    report.line("Целостность: {}. Журнал: {}".format(result["integrity"], result["journal"]))
    ok = bool(load.acknowledged) and not lost and result["integrity"] == "ok" and result["journal"].lower() == "delete"
    report.line("ИТОГ: {}".format("ДАННЫЕ ЦЕЛЫ" if ok else "ОШИБКА"))
    return EXIT_OK if ok else EXIT_FAILED
