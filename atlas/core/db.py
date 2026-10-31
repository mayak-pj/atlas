"""SQLite на сетевом диске: короткие транзакции, ретраи при блокировке, миграции по функциям.

На каждую операцию — своё подключение: его можно вызывать из любого потока, и после обрыва сети
не остаётся мёртвого соединения. Журнал DELETE: WAL на сетевом диске нельзя.
"""
from __future__ import annotations

import hashlib
import logging
import random
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("atlas.db")

DEFAULT_RETRY_DELAYS = (0.1, 0.25, 0.5, 1.0, 2.0)
_MIGRATION_NAME = re.compile(r"^(\d+)_.+\.sql$")


class DatabaseError(Exception):
    pass


class DatabaseBusyError(DatabaseError):
    """База занята другим пользователем дольше, чем мы готовы ждать."""


class MigrationError(DatabaseError):
    pass


def _is_locked(exc):
    # В Python 3.8 нет sqlite_errorcode, отличить можно только по тексту
    text = str(exc).lower()
    return "database is locked" in text or "database is busy" in text


class Database:
    def __init__(self, path, busy_timeout_ms=5000, retry_delays=DEFAULT_RETRY_DELAYS, sleep=time.sleep):
        self.path = Path(path)
        self.busy_timeout_ms = int(busy_timeout_ms)
        self.retry_delays = tuple(retry_delays)
        self._sleep = sleep

    def _connect(self):
        conn = sqlite3.connect(str(self.path), timeout=self.busy_timeout_ms / 1000.0, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout={}".format(self.busy_timeout_ms))
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA foreign_keys=ON")
        except Exception:
            conn.close()
            raise
        return conn

    def read(self, fn):
        """Выполнить fn(conn) в читающей транзакции и вернуть результат."""
        return self._run(fn, "BEGIN")

    def write(self, fn):
        """Выполнить fn(conn) в пишущей транзакции и вернуть результат.

        При блокировке транзакция откатывается и fn вызывается заново, поэтому fn должна менять
        только базу. Внутри fn нельзя вызывать read/write: второе подключение будет ждать первое.
        """
        return self._run(fn, "BEGIN IMMEDIATE")

    def _run(self, fn, begin):
        attempt = 0
        while True:
            try:
                return self._once(fn, begin)
            except sqlite3.OperationalError as exc:
                if not _is_locked(exc):
                    raise
                if attempt >= len(self.retry_delays):
                    raise DatabaseBusyError("База занята, попробуйте ещё раз: {}".format(self.path)) from exc
                delay = self.retry_delays[attempt]
                attempt += 1
                log.warning("База занята, повтор %d через %.2f с", attempt, delay)
                # Случайная добавка, чтобы два ПК не повторяли запрос одновременно
                self._sleep(delay * (1 + random.random() / 2))

    def _once(self, fn, begin):
        conn = self._connect()
        try:
            conn.execute(begin)
            result = fn(conn)
            conn.execute("COMMIT")
            return result
        except BaseException:
            if conn.in_transaction:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    log.exception("Не удалось откатить транзакцию")
            raise
        finally:
            conn.close()


def split_statements(sql):
    """Разбить скрипт на команды. executescript нельзя: он сам делает COMMIT и ломает атомарность."""
    statements, buffer = [], ""
    chunks = sql.split(";")
    for chunk in chunks[:-1]:
        buffer += chunk + ";"
        if sqlite3.complete_statement(buffer):
            statements.append(buffer)
            buffer = ""
    tail = buffer + chunks[-1]  # последняя команда может быть без «;»
    if _has_code(tail):
        statements.append(tail)
    return statements


def _has_code(sql):
    without_comments = re.sub(r"/\*.*?\*/|--[^\n]*", "", sql, flags=re.S)
    return bool(without_comments.strip())


def _checksum(text):
    # Без учёта переводов строк: git на Windows может заменить LF на CRLF
    normalized = text.replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


class MigrationRunner:
    """Применяет migrations/NNN_*.sql одного владельца. Каждый файл — отдельная транзакция.

    Безопасно при одновременном старте на двух ПК: перед применением версия проверяется под блокировкой записи.
    """

    def __init__(self, db):
        self.db = db

    def run(self, owner, directory):
        """Возвращает список применённых версий."""
        directory = Path(directory)
        files = self._collect(owner, directory)
        known = self.db.read(lambda conn: self._applied(conn, owner))
        if known and max(known) > max(files, default=0):
            raise MigrationError(
                "База новее программы ({}: версия {} > {}). Обновите программу.".format(
                    owner, max(known), max(files, default=0)
                )
            )
        applied = []
        for version in sorted(files):
            path = files[version]
            text = path.read_text(encoding="utf-8-sig")
            checksum = _checksum(text)
            if version in known:
                self._verify(owner, path, known[version], checksum)
                continue
            if self.db.write(lambda conn: self._apply(conn, owner, version, path, text, checksum)):
                applied.append(version)
                log.info("Миграция %s/%s применена", owner, path.name)
        return applied

    @staticmethod
    def _collect(owner, directory):
        files = {}
        if not directory.is_dir():
            return files
        for path in sorted(directory.glob("*.sql")):
            match = _MIGRATION_NAME.match(path.name)
            if not match:
                raise MigrationError("Неверное имя миграции: {}/{}".format(owner, path.name))
            version = int(match.group(1))
            if version in files:
                raise MigrationError("Две миграции {} с версией {}".format(owner, version))
            files[version] = path
        return files

    @staticmethod
    def _applied(conn, owner):
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if not exists:
            return {}
        rows = conn.execute("SELECT version, checksum FROM schema_migrations WHERE owner=?", (owner,))
        return {row["version"]: row["checksum"] for row in rows}

    @staticmethod
    def _verify(owner, path, expected, checksum):
        if expected != checksum:
            raise MigrationError("Применённая миграция изменена: {}/{}".format(owner, path.name))

    def _apply(self, conn, owner, version, path, text, checksum):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "owner TEXT NOT NULL, version INTEGER NOT NULL, name TEXT NOT NULL, "
            "checksum TEXT NOT NULL, applied_at TEXT NOT NULL, PRIMARY KEY (owner, version))"
        )
        # Пока мы ждали блокировку, эту версию мог применить другой ПК
        known = self._applied(conn, owner)
        if version in known:
            self._verify(owner, path, known[version], checksum)
            return False
        for statement in split_statements(text):
            conn.execute(statement)
        conn.execute(
            "INSERT INTO schema_migrations (owner, version, name, checksum, applied_at) VALUES (?, ?, ?, ?, ?)",
            (owner, version, path.name, checksum, datetime.now(timezone.utc).isoformat()),
        )
        return True
