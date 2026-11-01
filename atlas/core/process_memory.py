"""Пик памяти процесса для отчётов проверок."""
from __future__ import annotations

import sys


def peak_mb():
    """Мегабайты или None, если узнать не удалось."""
    try:
        if sys.platform == "win32":
            from atlas.core.process_memory_win import peak_bytes

            value = peak_bytes()
        else:
            import resource

            usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            value = usage if sys.platform == "darwin" else usage * 1024  # на Mac байты, на Linux килобайты
    except (OSError, ImportError, AttributeError):
        return None
    return None if value is None else value / 1024 / 1024
