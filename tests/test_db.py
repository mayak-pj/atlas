import sqlite3
import threading

import pytest

from atlas.core.db import Database, DatabaseBusyError, MigrationError, MigrationRunner, split_statements


@pytest.fixture
def db(tmp_path):
    # Кириллица и пробел в пути — как на целевой машине
    folder = tmp_path / "Сетевой диск"
    folder.mkdir()
    return Database(folder / "база.sqlite", busy_timeout_ms=50, retry_delays=(0, 0), sleep=lambda _: None)


def _table(db):
    db.write(lambda c: c.execute("CREATE TABLE t (v INTEGER)"))


def _count(db):
    return db.read(lambda c: c.execute("SELECT COUNT(*) FROM t").fetchone()[0])


def _names(db):
    return db.read(lambda c: {r[0] for r in c.execute("SELECT name FROM sqlite_master")})


def test_journal_mode_is_delete(db):
    assert db.read(lambda c: c.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "delete"


def test_write_commits_and_error_rolls_back(db):
    _table(db)
    db.write(lambda c: c.execute("INSERT INTO t VALUES (1)"))

    def fail(conn):
        conn.execute("INSERT INTO t VALUES (2)")
        raise ValueError("x")

    with pytest.raises(ValueError):
        db.write(fail)
    assert _count(db) == 1


def test_retries_until_lock_released(db):
    _table(db)
    holder = sqlite3.connect(str(db.path), isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    sleeps = []

    def sleep(_):
        sleeps.append(1)
        holder.execute("ROLLBACK")

    db._sleep = sleep
    db.write(lambda c: c.execute("INSERT INTO t VALUES (1)"))
    holder.close()
    assert sleeps == [1]
    assert _count(db) == 1


def test_busy_error_after_retries(db):
    _table(db)
    holder = sqlite3.connect(str(db.path), isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(DatabaseBusyError):
            db.write(lambda c: c.execute("INSERT INTO t VALUES (1)"))
    finally:
        holder.close()


def test_other_errors_are_not_retried(db):
    calls = []

    def bad(conn):
        calls.append(1)
        conn.execute("SELECT * FROM absent")

    with pytest.raises(sqlite3.OperationalError):
        db.read(bad)
    assert calls == [1]


def test_works_from_other_thread(db):
    _table(db)
    errors = []

    def worker():
        try:
            db.write(lambda c: c.execute("INSERT INTO t VALUES (1)"))
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert not errors and _count(db) == 1


def test_split_statements_handles_trigger_strings_comments():
    sql = """
    -- комментарий; с точкой с запятой
    CREATE TABLE a (v TEXT DEFAULT ';');
    CREATE TRIGGER tr AFTER INSERT ON a BEGIN
        UPDATE a SET v = 'x;y';
        DELETE FROM a WHERE v = '';
    END;
    /* конец; */
    INSERT INTO a VALUES ('без точки с запятой')
    -- хвост
    """
    assert len(split_statements(sql)) == 3
    assert split_statements("-- только комментарий\n") == []
    assert split_statements("") == []


def _write(folder, name, text):
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


def test_migrations_apply_in_numeric_order_once(db, tmp_path):
    folder = tmp_path / "m"
    _write(folder, "010_b.sql", "ALTER TABLE a ADD COLUMN y;")
    _write(folder, "002_a.sql", "CREATE TABLE a (x);")
    runner = MigrationRunner(db)
    assert runner.run("f", folder) == [2, 10]
    assert runner.run("f", folder) == []
    _write(folder, "011_c.sql", "CREATE TABLE c (x);")
    assert runner.run("f", folder) == [11]


def test_failed_migration_is_atomic(db, tmp_path):
    folder = tmp_path / "m"
    _write(folder, "001_a.sql", "CREATE TABLE a (x);\nCREATE TABLE b (x);\nNOT SQL;")
    with pytest.raises(sqlite3.Error):
        MigrationRunner(db).run("f", folder)
    assert not {"a", "b"} & _names(db)
    _write(folder, "001_a.sql", "CREATE TABLE a (x);\nCREATE TABLE b (x);")
    assert MigrationRunner(db).run("f", folder) == [1]


def test_owners_are_independent(db, tmp_path):
    _write(tmp_path / "a", "001_a.sql", "CREATE TABLE a (x);")
    _write(tmp_path / "b", "001_b.sql", "CREATE TABLE b (x);")
    runner = MigrationRunner(db)
    assert runner.run("a", tmp_path / "a") == [1]
    assert runner.run("b", tmp_path / "b") == [1]


def test_changed_migration_is_rejected_but_line_endings_are_not(db, tmp_path):
    folder = tmp_path / "m"
    _write(folder, "001_a.sql", "CREATE TABLE a (x);\nCREATE TABLE b (x);\n")
    runner = MigrationRunner(db)
    runner.run("f", folder)
    (folder / "001_a.sql").write_bytes(b"CREATE TABLE a (x);\r\nCREATE TABLE b (x);\r\n")
    assert runner.run("f", folder) == []
    _write(folder, "001_a.sql", "CREATE TABLE changed (x);")
    with pytest.raises(MigrationError):
        runner.run("f", folder)


def test_database_newer_than_program_is_rejected(db, tmp_path):
    folder = tmp_path / "m"
    _write(folder, "001_a.sql", "CREATE TABLE a (x);")
    _write(folder, "002_b.sql", "CREATE TABLE b (x);")
    runner = MigrationRunner(db)
    runner.run("f", folder)
    (folder / "002_b.sql").unlink()
    with pytest.raises(MigrationError):
        runner.run("f", folder)


def test_bad_migration_name_is_rejected(db, tmp_path):
    folder = tmp_path / "m"
    _write(folder, "init.sql", "CREATE TABLE a (x);")
    with pytest.raises(MigrationError):
        MigrationRunner(db).run("f", folder)


def test_concurrent_start_applies_once(tmp_path):
    folder = tmp_path / "m"
    # Без защиты второй поток упадёт на «table a already exists»
    _write(folder, "001_a.sql", "CREATE TABLE a (x);")
    path = tmp_path / "shared.sqlite"
    results, errors = [], []
    barrier = threading.Barrier(4)

    def worker():
        barrier.wait()
        try:
            results.append(MigrationRunner(Database(path)).run("f", folder))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert sorted(results) == [[], [], [], [1]]
