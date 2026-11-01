"""Базовые данные ядра: пользователи, проекты, устройства, детали, папки, фото.

Таблицы принадлежат ядру, функции работают с ними только через сервисы users, parts, folders.
Нет Qt: можно вызывать из любого потока, кроме GUI.
"""
from __future__ import annotations

from pathlib import Path

from atlas.core.db import MigrationRunner
from atlas.core.domain.folders import FoldersService
from atlas.core.domain.parts import PartsService
from atlas.core.domain.users import UsersService

OWNER = "core"
MIGRATIONS = Path(__file__).parent / "migrations"


def migrate(db):
    """Миграции ядра. Идут раньше миграций функций: те могут ссылаться на таблицы ядра."""
    return MigrationRunner(db).run(OWNER, MIGRATIONS)


def register_services(db, services, kinds=None):
    """kinds — допустимые виды проектов из настройки project_kinds."""
    services.register("users", UsersService(db))
    services.register("parts", PartsService(db, kinds))
    services.register("folders", FoldersService(db))
