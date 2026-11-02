"""Пути программы и настройки: config/app.json, config/local.json, config/features.json."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from atlas.core.release import RELEASE_DIR, home_of


class ConfigError(Exception):
    """Настройки не прочитать. Текст показывается пользователю."""


@dataclass(frozen=True)
class AppPaths:
    """root — файлы этой версии программы; home — настройки и данные, они переживают обновление.

    У обычной копии это одна папка. Установка на сетевом диске — см. core/release.py.
    """

    root: Path
    installed_home: Optional[Path] = None

    @classmethod
    def discover(cls):
        if getattr(sys, "frozen", False):
            program = Path(sys.executable).parent
            return cls(program, home_of(program))
        return cls(Path(__file__).resolve().parents[2])

    @property
    def home(self):
        return self.installed_home or self.root

    @property
    def release_dir(self):
        """Папка с версиями; у обычной копии — None."""
        return self.installed_home / RELEASE_DIR if self.installed_home else None

    @property
    def local_config(self):
        return self.home / "config" / "local.json"

    @property
    def user_state_dir(self):
        """Выбор пользователя (тема, панели). В общей установке у каждого свой, иначе люди перебивали бы выбор друг друга."""
        base = os.environ.get("LOCALAPPDATA") if self.installed_home else None
        return Path(base) / "Atlas" if base else self.home / "var"

    @property
    def config(self):
        return self.root / "config"

    @property
    def data(self):
        return self.root / "data"

    @property
    def templates(self):
        return self.root / "templates"

    @property
    def logs(self):
        return self.home / "logs"

    def resolve(self, value):
        """Абсолютный путь и UNC — как есть, относительный — от папки с данными."""
        path = Path(value)
        return path if path.is_absolute() else self.home / path


@dataclass(frozen=True)
class FeatureEntry:
    id: str
    enabled: bool = True
    tab_order: Optional[int] = None


def _read_json(path):
    try:
        # utf-8-sig: Блокнот Win7 сохраняет с BOM
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ConfigError("Не удалось прочитать {}: {}".format(path, exc))
    except ValueError as exc:
        raise ConfigError("Ошибка в файле {}: {}".format(path, exc))


def _merge(base, override):
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


class Config:
    def __init__(self, paths, app, features):
        self.paths = paths
        self.app = app
        self.features = features  # type: List[FeatureEntry]

    @classmethod
    def load(cls, paths):
        app = _read_json(paths.config / "app.json")
        local = paths.local_config  # настройки этой машины, не в git
        if local.exists():
            app = _merge(app, _read_json(local))
        return cls(paths, app, _parse_features(paths.config / "features.json"))

    def get(self, dotted, default=None):
        """config.get("database.path")"""
        node = self.app
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def _parse_features(path):
    raw = _read_json(path)
    items = raw.get("features") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ConfigError('В файле {} нет списка "features"'.format(path))
    entries = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ConfigError("Ошибка в файле {}: неверная запись {!r}".format(path, item))
        entries.append(FeatureEntry(item["id"], bool(item.get("enabled", True)), item.get("tab_order")))
    return entries
