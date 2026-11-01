"""Четыре настоящих процесса пишут в один файл БД, начиная с пустой базы."""
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKER = Path(__file__).resolve().parent / "concurrent_writer.py"
PROCESSES = 4
ROUNDS = 15


def test_four_processes_write_to_one_file(tmp_path):
    folder = tmp_path / "Сетевой диск"
    folder.mkdir()
    path = folder / "база.sqlite"
    workers = [
        subprocess.Popen(
            [sys.executable, str(WORKER), str(path), str(tmp_path), str(number), str(ROUNDS)],
            stderr=subprocess.PIPE,
        )
        for number in range(PROCESSES)
    ]
    # Сигнал старта — когда все уже загрузились: иначе процессы отработают по очереди и борьбы за файл не будет
    deadline = time.monotonic() + 60
    while len(list(tmp_path.glob("ready*"))) < PROCESSES and time.monotonic() < deadline:
        time.sleep(0.01)
    (tmp_path / "go").touch()
    errors = [(worker.communicate(timeout=120)[1], worker.returncode) for worker in workers]
    assert [code for _, code in errors] == [0] * PROCESSES, b"\n".join(text for text, _ in errors).decode("utf-8", "replace")

    conn = sqlite3.connect(str(path))
    try:
        def one(sql):
            return conn.execute(sql).fetchone()[0]

        assert one("PRAGMA integrity_check") == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert one("PRAGMA journal_mode").lower() == "delete"
        # Каждая миграция ядра применена один раз, несмотря на гонку
        core_files = len(list((REPO / "atlas" / "core" / "domain" / "migrations").glob("*.sql")))
        assert one("SELECT COUNT(*) FROM schema_migrations WHERE owner = 'core'") == core_files
        assert one("SELECT COUNT(*) FROM users") == PROCESSES + 1
        assert one("SELECT COUNT(*) FROM projects") == 1
        assert one("SELECT COUNT(*) FROM devices") == 1
        assert one("SELECT COUNT(*) FROM parts") == 3
        # Ни одна подтверждённая запись не потеряна
        assert one("SELECT COUNT(*) FROM folders") == PROCESSES * ROUNDS + 1
        assert one("SELECT COUNT(*) FROM folders WHERE status = 'done'") == PROCESSES * ROUNDS
        assert one("SELECT COUNT(*) FROM photos") == 2 * PROCESSES * ROUNDS * 5
        assert one("SELECT COUNT(*) FROM photos WHERE mark = 'defect'") == PROCESSES * ROUNDS
    finally:
        conn.close()
