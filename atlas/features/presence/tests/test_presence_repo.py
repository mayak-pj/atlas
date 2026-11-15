"""Сигнал присутствия не должен падать, если папка уже удалена из базы (журнал 15.11: ~800 «FOREIGN KEY»)."""
from pathlib import Path

from atlas.core import domain
from atlas.core.db import Database, MigrationRunner
from atlas.core.domain.folders import FoldersService
from atlas.core.domain.parts import PartsService
from atlas.core.domain.users import UsersService
from atlas.features.presence import repo as repo_module
from atlas.features.presence.repo import PresenceRepo


def _setup(tmp_path):
    db = Database(tmp_path / "база.sqlite")
    domain.migrate(db)
    MigrationRunner(db).run("presence", Path(repo_module.__file__).parent / "migrations")
    user = UsersService(db).add("Иван", lambda index: "#336699")
    part = PartsService(db).ensure("A", "Орион-24", "N15", "SSD")
    folder = FoldersService(db).add(part.id, str(tmp_path), "2026-11-15")
    return db, user, folder


def test_beat_with_deleted_folder_is_sent_without_folder(tmp_path):
    db, user, folder = _setup(tmp_path)
    repo = PresenceRepo(db)
    repo.beat(user.id, folder.id)
    assert repo.rows()[0].folder_id == folder.id
    FoldersService(db).delete(folder.id)
    repo.beat(user.id, folder.id)  # id папки ещё лежит в памяти окна
    rows = repo.rows()
    assert len(rows) == 1 and rows[0].folder_id is None and rows[0].beat == 2
    repo.beat(user.id, folder.id)  # и повторно: так же без ошибки
    assert repo.rows()[0].beat == 3
