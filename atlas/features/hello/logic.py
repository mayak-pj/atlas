"""Чистая логика — без Qt."""


def greeting(name=None):
    return "Привет, {}!".format(name) if name else "Привет!"
