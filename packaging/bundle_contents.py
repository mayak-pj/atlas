"""Что положить в сборку из пакета atlas. Отдельно от spec, чтобы проверять тестом на Mac.

Функции импортируются по имени из features.json, PyInstaller их сам не видит. Поэтому в сборку идут все модули
всех функций: включить функцию можно будет правкой features.json, без пересборки.
"""
import os

SKIP_DIRS = {"__pycache__", "tests", "_template"}


def _walk(root):
    package = os.path.join(root, "atlas")
    for directory, subdirs, files in os.walk(package):
        subdirs[:] = sorted(name for name in subdirs if name not in SKIP_DIRS)
        for name in sorted(files):
            yield os.path.relpath(directory, root), name


def hidden_modules(root):
    """Имена всех модулей пакета atlas."""
    modules = []
    for directory, name in _walk(root):
        stem, extension = os.path.splitext(name)
        if extension != ".py":
            continue
        parts = directory.split(os.sep)
        modules.append(".".join(parts if stem == "__init__" else parts + [stem]))
    return modules


def data_files(root):
    """Пары (файл, папка в сборке): миграции .sql, atlas.qss, tokens.json и всё прочее, кроме кода."""
    return [
        (os.path.join(root, directory, name), directory)
        for directory, name in _walk(root)
        if os.path.splitext(name)[1] not in (".py", ".pyc")
    ]
