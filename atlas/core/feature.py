"""Контракт функции: описание FeatureSpec и базовый класс Feature."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class FeatureSpec:
    id: str
    title: str
    factory: str  # "atlas.features.<id>.ui:ClassName"
    version: int = 1
    requires: List[str] = field(default_factory=list)  # жёсткие зависимости
    optional: List[str] = field(default_factory=list)  # есть — запускаем раньше, нет — работаем без них
    tab_order: Optional[int] = None  # None — без вкладки; features.json может переопределить


class Feature:
    """Базовый класс. Все методы необязательны."""

    def __init__(self, ctx):
        self.ctx = ctx

    def on_start(self):
        """Подписки на события, регистрация сервисов."""

    def create_tab(self):
        """QWidget вкладки или None."""
        return None

    def badge(self):
        """Счётчик/подсветка на вкладке или None."""
        return None

    def settings_page(self):
        """Страница в «Настройках» или None."""
        return None

    def on_stop(self):
        """Освобождение ресурсов, отписки."""
