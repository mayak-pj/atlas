"""SyncGroup: окна одной группы смотрят в одно место.

Передаются зум (от «вписать») и центр в долях фото, поэтому фото разного размера показывают одну и ту же часть.
Каждое окно само упирается в края своего фото; это не отражается на остальных: set_state не посылает view_changed.
"""
from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal

_FIT_STATE = (1.0, 0.5, 0.5)


class SyncGroup(QObject):
    changed = pyqtSignal(float, float, float)  # зум, центр — для панели инструментов

    def __init__(self, cache, parent=None):
        super().__init__(parent)
        self._cache = cache
        self._views = []
        self._slots = {}  # окно → (его обработчики), чтобы отключить при удалении
        self._reference = None
        self._leader = None  # окно, которого пользователь касался последним
        self._enabled = True
        self._state = _FIT_STATE

    @property
    def views(self):
        return list(self._views)

    @property
    def reference(self):
        return self._reference

    @property
    def currents(self):
        return [view for view in self._views if view is not self._reference]

    @property
    def enabled(self):
        return self._enabled

    @property
    def state(self):
        return self._state

    def add(self, view, reference=False):
        def on_changed(zoom, cx, cy):
            self._on_view_changed(view, (zoom, cx, cy))

        def on_shown(path):
            # Новое фото других пропорций могло упереть окно в край: возвращаем общее место
            if self._enabled:
                view.set_state(*self._state)

        view.view_changed.connect(on_changed)
        view.photo_shown.connect(on_shown)
        self._slots[view] = (on_changed, on_shown)
        self._views.append(view)
        if reference:
            self._reference = view
        if self._enabled:
            view.set_state(*self._state)

    def remove(self, view):
        if view not in self._views:
            return
        on_changed, on_shown = self._slots.pop(view)
        view.view_changed.disconnect(on_changed)
        view.photo_shown.disconnect(on_shown)
        self._views.remove(view)
        if self._reference is view:
            self._reference = None
        if self._leader is view:
            self._leader = None

    def set_reference(self, view):
        """Эталон не меняется при листании. None — эталона нет."""
        self._reference = view

    def set_enabled(self, enabled):
        """При включении все выравниваются по окну, которого касались последним."""
        self._enabled = bool(enabled)
        if self._enabled:
            if self._leader is not None:
                self._state = self._leader.state()
            for view in self._views:
                if view is not self._leader:
                    view.set_state(*self._state)

    def fit(self):
        """Кнопка «Вписать»: все окна, в том числе без синхронизации."""
        self._state = _FIT_STATE
        for view in self._views:
            view.set_state(*self._state)
        self.changed.emit(*self._state)

    def zoom_by(self, factor):
        """Кнопки −/+: через ведущее окно, остальные получат изменение как обычно."""
        target = self._leader or (self._views[0] if self._views else None)
        if target is not None:
            target.zoom_by(factor)

    def active_current(self):
        """Окно, которое листается: текущее, которого касались последним, иначе последнее текущее. Эталон не листается."""
        if self._leader is not None and self._leader is not self._reference:
            return self._leader
        currents = self.currents
        return currents[-1] if currents else None

    def show_photo(self, view, path):
        """Листание: новое фото в одном окне, остальные не меняются.

        Отмена очереди — здесь, а не в окнах: кэш общий. Она снимает и запросы других окон, поэтому их просим повторить.
        """
        self._cache.cancel_pending()
        view.set_photo(path)
        for item in self._views:
            item.request_again()

    def _on_view_changed(self, source, state):
        self._leader = source
        self._state = state
        if self._enabled:
            for view in self._views:
                if view is not source:
                    view.set_state(*state)
        self.changed.emit(*state)
