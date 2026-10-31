"""Слоты оболочки: именованные места, куда функции кладут свои панели.

Слот создаёт тот, кто владеет местом (оболочка или функция): register_slot(имя, layout).
Панель можно добавить раньше, чем появится слот, — она дождётся. Нет слота (функция отключена) — панель просто не показывается.
"""
from __future__ import annotations

import logging

log = logging.getLogger("atlas.shell")


class SlotRegistry:
    def __init__(self):
        self._layouts = {}
        self._panels = {}  # имя слота -> [(order, key, widget)]
        self._counter = 0

    def register_slot(self, name, layout):
        self._layouts[name] = layout
        self._rebuild(name)

    def unregister_slot(self, name):
        self._layouts.pop(name, None)

    def clear_slot(self, name):
        """Забыть панели слота (виджеты не трогаем: их хозяин — тот, кто владеет слотом)."""
        self._panels.pop(name, None)

    def has_slot(self, name):
        return name in self._layouts

    def add_panel(self, name, widget, key=None, order=0):
        """Повторный вызов с тем же key заменяет панель. Возвращает widget."""
        if key is None:
            self._counter += 1
            key = "#{}".format(self._counter)
        panels = self._panels.setdefault(name, [])
        for item in list(panels):
            if item[1] == key:
                panels.remove(item)
                if item[2] is not widget:
                    self._discard(name, item[2])
        panels.append((order, key, widget))
        panels.sort(key=lambda item: item[0])  # устойчивая: при равном order — порядок добавления
        self._rebuild(name)
        return widget

    def remove_panel(self, name, key):
        panels = self._panels.get(name, [])
        for item in list(panels):
            if item[1] == key:
                panels.remove(item)
                self._discard(name, item[2])
        self._rebuild(name)

    def panels(self, name):
        return [item[2] for item in self._panels.get(name, [])]

    def _discard(self, name, widget):
        layout = self._layouts.get(name)
        if layout is not None:
            layout.removeWidget(widget)
        widget.hide()
        widget.deleteLater()

    def _rebuild(self, name):
        layout = self._layouts.get(name)
        if layout is None:
            return
        for _, _, widget in self._panels.get(name, []):
            layout.removeWidget(widget)
        for _, _, widget in self._panels.get(name, []):
            layout.addWidget(widget)
            widget.show()
