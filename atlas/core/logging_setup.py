"""Журнал сессии в папке logs и сбор ошибок для показа в окне (из curator).

В оконном exe sys.stderr = None, поэтому в stderr не пишем: только файл.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime

LOGGER_NAME = "atlas"
FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


class ProblemCollector(logging.Handler):
    """Хранит предупреждения и ошибки сессии."""

    def __init__(self, level=logging.WARNING):
        super().__init__(level=level)
        self.records = []

    def emit(self, record):
        self.records.append({"level": record.levelname, "message": record.getMessage(), "time": record.created})


def configure(log_dir, level="INFO"):
    """Настроить журнал. Возвращает (логгер, сборщик ошибок). Папка недоступна — работаем без файла."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    collector = ProblemCollector()
    logger.addHandler(collector)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        name = datetime.now().strftime("atlas_%Y%m%d_%H%M%S.log")
        handler = logging.FileHandler(str(log_dir / name), encoding="utf-8")
    except OSError as exc:
        logger.warning("Журнал не записывается в файл: %s", exc)
    else:
        handler.setLevel(getattr(logging, level, logging.INFO))
        handler.setFormatter(logging.Formatter(FORMAT))
        logger.addHandler(handler)
    return logger, collector


def install_excepthook():
    """Без своего обработчика PyQt5 завершает программу при исключении в слоте."""

    def hook(exc_type, exc, tb):
        logging.getLogger(LOGGER_NAME).critical("Необработанная ошибка", exc_info=(exc_type, exc, tb))

    sys.excepthook = hook
