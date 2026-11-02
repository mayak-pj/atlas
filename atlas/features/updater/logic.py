"""Какую версию предложить и как её запустить. Без Qt."""
from __future__ import annotations

import logging
import os
import subprocess
from collections import namedtuple
from pathlib import Path

from atlas.core.release import EXE_NAME, read_active_version

log = logging.getLogger("atlas.updater")

Offer = namedtuple("Offer", "version exe")


def find_offer(release_dir, running):
    """Offer или None. Другая версия предлагается и если она старше: так работает откат. Сеть: не из GUI-потока."""
    if release_dir is None:
        return None  # обычная копия, не установка
    active = read_active_version(release_dir)
    if active is None or active == running:
        return None
    exe = Path(release_dir) / active / EXE_NAME
    try:
        if not exe.is_file():
            log.warning("В version.txt версия %s, но нет файла %s", active, exe)
            return None
    except OSError as exc:
        log.info("Не проверить %s: %s", exe, exc)
        return None
    return Offer(active, exe)


def launch(exe):
    """Запуск версии отдельным процессом. Ошибка — OSError."""
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")  # иначе новый exe примет настройки запуска этого за свои
    subprocess.Popen(
        [str(exe)], cwd=str(Path(exe).parent), env=env, close_fds=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,  # у оконного exe их нет
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
    )
