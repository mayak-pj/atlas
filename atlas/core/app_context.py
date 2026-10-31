"""AppContext: всё, что ядро даёт функции."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class User:
    """Вошедший пользователь. Кладёт в ctx.user функция login."""

    id: int
    name: str
    color: str = "#7DB4FF"


@dataclass
class AppContext:
    config: Any
    paths: Any
    db: Any
    bus: Any
    services: Any
    user: Optional[User] = None  # заполняет функция login
    shell: Optional[Any] = None  # главное окно со слотами (шаг 0.4)
