#!/usr/bin/env python3
"""Записывает версию в atlas/__init__.py и в ресурс atlas.exe. CI вызывает перед сборкой.

    python scripts/set_version.py 0.10.57
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _replace(path, pattern, value):
    text = path.read_text(encoding="utf-8")
    new, count = re.subn(pattern, value, text)
    if not count:
        raise SystemExit("В {} не найдено: {}".format(path, pattern))
    path.write_text(new, encoding="utf-8")


def set_version(version, root=ROOT):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit("Версия должна быть вида 1.2.3: {}".format(version))
    _replace(root / "atlas" / "__init__.py", r'__version__ = "[^"]*"', '__version__ = "{}"'.format(version))
    info = root / "packaging" / "version_info.txt"
    numbers = "({}, 0)".format(", ".join(version.split(".")))
    _replace(info, r"(filevers|prodvers)=\([^)]*\)", lambda m: "{}={}".format(m.group(1), numbers))
    _replace(info, r"StringStruct\('(FileVersion|ProductVersion)', '[^']*'\)",
             lambda m: "StringStruct('{}', '{}')".format(m.group(1), version))


if __name__ == "__main__":
    set_version(sys.argv[1])
