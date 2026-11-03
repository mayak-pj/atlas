"""Сервис «defect_kinds» и окно правки списка."""
from __future__ import annotations

import logging

from atlas.core.feature import Feature
from atlas.features.defect_kinds import logic
from atlas.features.defect_kinds.repo import KindsRepo

log = logging.getLogger("atlas.defect_kinds")


class DefectKindsFeature(Feature):
    """Сервис «defect_kinds». Кроме edit — из любого потока, кроме GUI (ходят в базу):
    names() → [имя], add(name), rename(old, new) → сколько отметок фото исправлено, remove(name).
    edit(parent) — открыть окно правки, из GUI-потока. После каждого изменения — событие defect_kinds.changed {kinds}.
    """

    def on_start(self):
        self.repo = KindsRepo(self.ctx.db, logic.seed_names(self.ctx.paths.data))
        self.ctx.services.register("defect_kinds", self)

    def on_stop(self):
        self.ctx.services.unregister("defect_kinds")

    def _user_id(self):
        return self.ctx.user.id if self.ctx.user is not None else None

    def names(self):
        return self.repo.names()

    def add(self, name):
        text = self.repo.add(name, self._user_id())
        self._changed()
        return text

    def rename(self, old, new):
        """Список, затем отметки фото: дашборд и сводка считают старые и новые замечания вместе."""
        text = self.repo.rename(old, new)
        fixed = self.ctx.services.get("folders").rename_defect_kind(old, text)
        self._changed()
        return fixed

    def remove(self, name):
        """Из списка; старые отметки сохраняют свой текст."""
        self.repo.remove(name)
        self._changed()

    def _changed(self):
        self.ctx.bus.publish(logic.EVENT_CHANGED, {"kinds": self.repo.names()})

    def edit(self, parent=None):
        from atlas.features.defect_kinds.dialog import KindsDialog

        KindsDialog(self, parent).exec_()
