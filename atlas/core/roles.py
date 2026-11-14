"""Роли людей (14.11.2026). Пока одна: «администратор» — пара человек, которые держат рабочую среду в порядке;
им можно то, что остальным нельзя, и их возможности будут расти.

Список фамилий — `roles.admins` в `config/local.json` на месте (в git — пустой). Сравнение по ключу человека
(`name_key`: только регистр), как при входе. Ролей будет больше — добавлять сюда, не в функции.
"""
from __future__ import annotations

from atlas.core.domain.text import clean_name, name_key


def admins(config):
    """Ключи фамилий администраторов из настроек; неверное значение — никого."""
    raw = config.get("roles.admins", [])
    if not isinstance(raw, (list, tuple)):
        return frozenset()
    return frozenset(name_key(clean_name(item)) for item in raw if clean_name(item))


def is_admin(config, user):
    """user — User ядра или None (никто не вошёл)."""
    return user is not None and name_key(clean_name(user.name)) in admins(config)
