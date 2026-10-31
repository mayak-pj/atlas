"""AppContext: всё, что ядро даёт функции."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class AppContext:
    config: Any
    paths: Any
    db: Any
    bus: Any
    services: Any
    user: Optional[Any] = None  # заполняет функция login (шаг 0.4)
    shell: Optional[Any] = None  # главное окно со слотами (шаг 0.4)
