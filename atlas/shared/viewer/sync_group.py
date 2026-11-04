"""SyncGroup: окна одной группы смотрят в одно место.

Передаются зум (от «вписать») и центр в долях фото, поэтому фото разного размера показывают одну и ту же часть.
Каждое окно само упирается в края своего фото; это не отражается на остальных: set_state не посылает view_changed.

У окна может быть своё смещение от общего места (`_offsets`: во сколько раз крупнее и на сколько сдвинут центр).
Его запоминает включение синхронности: человек выключил её, подогнал одно окно (фото со второго фотоаппарата),
включил снова — окна двигаются вместе, а подгонка сохраняется (замечание 04.11.2026). «В кадр» (`fit`) снимает смещения.
"""
from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal

from atlas.shared.viewer.view_state import rotated_center

_FIT_STATE = (1.0, 0.5, 0.5)
_SAME = (1.0, 0.0, 0.0)  # смещения нет


def _apply(state, offset):
    zoom, cx, cy = state
    ratio, dx, dy = offset
    return zoom * ratio, cx + dx, cy + dy


def _base_of(state, offset):
    """Общее место по месту окна с этим смещением."""
    zoom, cx, cy = state
    ratio, dx, dy = offset
    return zoom / ratio, cx - dx, cy - dy


def _offset_between(state, base):
    return state[0] / base[0], state[1] - base[1], state[2] - base[2]


def _rotated_offset(offset, delta):
    ratio, dx, dy = offset
    x, y = rotated_center(0.5 + dx, 0.5 + dy, delta)
    return ratio, x - 0.5, y - 0.5


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
        self._offsets = {}  # окно → смещение от общего места; нет записи — смещения нет

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

    @property
    def offsets(self):
        return dict(self._offsets)

    def set_offsets(self, offsets):
        """Смещения окон, сохранённые раньше (у режимов экрана свои). Мест окон не меняет."""
        self._offsets = {view: offset for view, offset in offsets.items() if view in self._views and offset != _SAME}

    def _place(self, view):
        view.set_state(*_apply(self._state, self._offsets.get(view, _SAME)))

    def add(self, view, reference=False):
        def on_changed(zoom, cx, cy):
            self._on_view_changed(view, (zoom, cx, cy))

        def on_shown(path):
            # Новое фото других пропорций могло упереть окно в край: возвращаем общее место
            if self._enabled:
                self._place(view)

        view.view_changed.connect(on_changed)
        view.photo_shown.connect(on_shown)
        self._slots[view] = (on_changed, on_shown)
        self._views.append(view)
        if reference:
            self._reference = view
        if self._enabled:
            self._place(view)

    def remove(self, view):
        if view not in self._views:
            return
        on_changed, on_shown = self._slots.pop(view)
        view.view_changed.disconnect(on_changed)
        view.photo_shown.disconnect(on_shown)
        self._views.remove(view)
        self._offsets.pop(view, None)
        if self._reference is view:
            self._reference = None
        if self._leader is view:
            self._leader = None

    def set_reference(self, view):
        """Эталон не меняется при листании. None — эталона нет."""
        self._reference = view

    def set_enabled(self, enabled, measure=True):
        """Включение запоминает, как окна стоят друг относительно друга, и дальше двигает их вместе; никто не прыгает.

        Общим местом становится место окна, которого касались последним. measure=False — смещения не мерить
        (экран восстанавливает свои, сохранённые вместе с местом режима).
        """
        self._enabled = bool(enabled)
        if not self._enabled or not measure:
            return
        leader = self._leader if self._leader in self._views else (self._views[0] if self._views else None)
        if leader is None:
            return
        self._state = leader.state()
        self._offsets = {}
        for view in self._views:
            if view is not leader:
                offset = _offset_between(view.state(), self._state)
                if offset != _SAME:
                    self._offsets[view] = offset

    def set_state(self, zoom, cx, cy):
        """Задать место всей группе (со смещениями окон). Напрямую view.set_state нельзя: группа вернёт своё, когда придёт новое фото."""
        self._state = (zoom, cx, cy)
        for view in self._views:
            self._place(view)
        self.changed.emit(zoom, cx, cy)

    def reset_offsets(self):
        """Окна снова смотрят в одно место (новая папка)."""
        self._offsets = {}

    def fit(self):
        """Кнопка «В кадр» (раньше «Вписать», «Сбросить»): все окна, в том числе без синхронизации. Подгонка окон друг к другу снимается."""
        self._state = _FIT_STATE
        self._offsets = {}
        for view in self._views:
            view.set_state(*self._state)
        self.changed.emit(*self._state)

    def zoom_by(self, factor):
        """Кнопки −/+: через ведущее окно, остальные получат изменение как обычно."""
        target = self._leader or (self._views[0] if self._views else None)
        if target is not None:
            target.zoom_by(factor)

    def rotate(self, delta, rotations):
        """Повернуть окна вместе на delta градусов; rotations — [(окно, его новый поворот)].

        Группа пересчитывает общее место сама: окно могло упереться в край, а после обратного поворота вернётся туда же.
        """
        zoom, cx, cy = self._state
        self._state = (zoom,) + rotated_center(cx, cy, delta)
        for view, rotation in rotations:
            view.set_rotation(rotation)
            if view in self._offsets:  # сдвиг окна поворачивается вместе с его фото
                self._offsets[view] = _rotated_offset(self._offsets[view], delta)
            if self._enabled:
                self._place(view)

    def touch(self, view):
        """Пользователь выбрал окно кликом: кнопки −/+ теперь действуют на него."""
        if view in self._views:
            self._leader = view

    def active_current(self):
        """Окно, которое листается: текущее, которого касались последним, иначе последнее текущее. Эталон не листается."""
        if self._leader is not None and self._leader is not self._reference:
            return self._leader
        currents = self.currents
        return currents[-1] if currents else None

    def show_photo(self, view, path, rotation=0):
        """Листание: новое фото в одном окне, остальные не меняются."""
        self.show_photos([(view, path, rotation)])

    def show_photos(self, shown):
        """Новые фото сразу в нескольких окнах, [(окно, путь, поворот)], за одну отмену очереди.

        Отмена — здесь, а не в окнах: кэш общий. Она снимает и запросы других окон, поэтому их просим повторить.
        """
        self._cache.cancel_pending()
        for view, path, rotation in shown:
            view.set_photo(path, rotation)
        for item in self._views:
            item.request_again()

    def _on_view_changed(self, source, state):
        self._leader = source
        if not self._enabled:
            self._state = state
            self.changed.emit(*state)
            return
        self._state = _base_of(state, self._offsets.get(source, _SAME))
        for view in self._views:
            if view is not source:
                self._place(view)
        self.changed.emit(*state)
