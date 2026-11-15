"""Цвет типа (12.13): у типов 1–20 свои цвета (токены `ok`, `type2`, `type3` … `type20` темы), дальше цвета повторяются.

Одно место для всех: точка на миниатюре, кнопка «ТИП N», список выбора, «таблетки» в замечаниях и базе типов.
"""
from __future__ import annotations

COLORED_TYPES = 20
FIRST_REPEATED = 4  # 1 и 2 — «ok» и «type2», с 3-го — «typeN»


def type_tone(number):
    """Токен цвета типа; номер больше 20 снова идёт по кругу с 4-го цвета."""
    number = int(number)
    if number <= 1:
        return "ok"
    if number > COLORED_TYPES:
        number = FIRST_REPEATED + (number - FIRST_REPEATED) % (COLORED_TYPES - FIRST_REPEATED + 1)
    return "type{}".format(number)
