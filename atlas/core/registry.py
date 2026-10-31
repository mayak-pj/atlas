"""Реестр функций: читает features.json, сортирует по зависимостям, запускает.

Ошибка одной функции не роняет приложение: она попадает в журнал, в failures и в событие feature.failed.
Отключённая функция не импортируется.
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from atlas.core.db import MigrationRunner

log = logging.getLogger("atlas.registry")

EVENT_FAILED = "feature.failed"


@dataclass(frozen=True)
class FeatureFailure:
    id: str
    stage: str  # import | dependencies | migrations | start
    error: str


@dataclass
class LoadedFeature:
    spec: Any
    instance: Any
    tab: Any = None
    tab_order: Optional[int] = None


class FeatureRegistry:
    def __init__(self, ctx, package="atlas.features"):
        self.ctx = ctx
        self.package = package
        self.loaded = []  # type: List[LoadedFeature]
        self.failures = []  # type: List[FeatureFailure]
        self._modules = {}
        self._tab_orders = {}

    def start_all(self):
        specs = self._import_enabled()
        for spec in self._sorted(specs):
            self._start(spec, specs)

    def tabs(self):
        """Запущенные функции с вкладкой, в порядке вкладок."""
        with_tab = [item for item in self.loaded if item.tab is not None]
        return sorted(with_tab, key=lambda item: item.tab_order if item.tab_order is not None else 0)

    def stop_all(self):
        for item in reversed(self.loaded):
            try:
                item.instance.on_stop()
            except Exception:
                log.exception("Ошибка при остановке функции %s", item.spec.id)
        self.loaded = []

    def _fail(self, feature_id, stage, error):
        text = str(error)
        self.failures.append(FeatureFailure(feature_id, stage, text))
        log.error("Функция %s не запущена (%s): %s", feature_id, stage, text)
        self.ctx.bus.publish(EVENT_FAILED, {"id": feature_id, "stage": stage, "error": text})

    def _import_enabled(self):
        specs = {}
        for entry in self.ctx.config.features:
            if not entry.enabled:
                continue
            if entry.id in specs:
                log.warning("Функция %s указана в features.json дважды", entry.id)
                continue
            try:
                # Отсекает «_template» и обход пакета через точки в id
                if not entry.id.isidentifier() or entry.id.startswith("_"):
                    raise ValueError("недопустимый id")
                module = importlib.import_module("{}.{}".format(self.package, entry.id))
                spec = module.FEATURE
                if spec.id != entry.id:
                    raise ValueError("в папке {} описана функция {}".format(entry.id, spec.id))
            except Exception as exc:
                log.exception("Ошибка импорта функции %s", entry.id)
                self._fail(entry.id, "import", exc)
                continue
            specs[entry.id] = spec
            self._modules[entry.id] = module
            order = entry.tab_order if entry.tab_order is not None else spec.tab_order
            self._tab_orders[entry.id] = order
        return specs

    def _sorted(self, specs):
        """Зависимости раньше зависимых, иначе порядок features.json. Циклы requires — ошибка."""
        remaining = list(specs)
        result = []
        placed = set()

        def ready(feature_id, names):
            return all(dep in placed or dep not in specs for dep in names)

        while remaining:
            pick = next(
                (f for f in remaining if ready(f, specs[f].requires) and ready(f, specs[f].optional)), None
            )
            if pick is None:  # цикл через optional допустим: optional — не жёсткая связь
                pick = next((f for f in remaining if ready(f, specs[f].requires)), None)
            if pick is None:
                for feature_id in remaining:
                    self._fail(feature_id, "dependencies", "цикл в requires: {}".format(", ".join(remaining)))
                break
            remaining.remove(pick)
            placed.add(pick)
            result.append(specs[pick])
        return result

    def _start(self, spec, specs):
        running = {item.spec.id for item in self.loaded}
        missing = [dep for dep in spec.requires if dep not in running]
        if missing:
            self._fail(spec.id, "dependencies", "не запущены: {}".format(", ".join(missing)))
            return
        try:
            self._migrate(spec)
        except Exception as exc:
            log.exception("Ошибка миграций функции %s", spec.id)
            self._fail(spec.id, "migrations", exc)
            return
        instance = None
        try:
            instance = self._create(spec)
            instance.on_start()
            order = self._tab_orders.get(spec.id)
            tab = instance.create_tab() if order is not None else None
        except Exception as exc:
            log.exception("Ошибка запуска функции %s", spec.id)
            if instance is not None:
                self._stop_quietly(spec, instance)
            self._fail(spec.id, "start", exc)
            return
        self.loaded.append(LoadedFeature(spec, instance, tab, order))

    def _migrate(self, spec):
        directory = Path(self._modules[spec.id].__file__).parent / "migrations"
        if directory.is_dir() and any(directory.glob("*.sql")):
            MigrationRunner(self.ctx.db).run(spec.id, directory)

    def _create(self, spec):
        module_name, _, class_name = spec.factory.partition(":")
        cls = getattr(importlib.import_module(module_name), class_name)
        return cls(self.ctx)

    @staticmethod
    def _stop_quietly(spec, instance):
        # on_start мог успеть подписаться на события и зарегистрировать сервис
        try:
            instance.on_stop()
        except Exception:
            log.exception("Ошибка при остановке функции %s", spec.id)
