#!/usr/bin/env python3
"""Кладёт рядом с atlas.exe то, что меняется без пересборки, и файлы для проверки на выезде.

    python scripts/assemble_dist.py dist/atlas

config/local.json (настройки машины разработчика) в поставку не попадает.
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _to_notepad(text):
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


def assemble(dist, root=ROOT):
    dist = Path(dist)
    for name in ("config", "data", "templates"):
        source = root / name
        target = dist / name
        if target.exists():
            shutil.rmtree(str(target))
        if source.is_dir():
            shutil.copytree(str(source), str(target), ignore=shutil.ignore_patterns("local.json"))
    for bat in sorted((root / "packaging" / "bat").glob("*.bat")):
        # cmd.exe на русской Windows 7 читает .bat в кодировке 866
        (dist / bat.name).write_bytes(_to_notepad(bat.read_text(encoding="utf-8")).encode("cp866"))
    # Файлы папки установки: --publish кладёт их рядом с release
    install = dist / "install"
    install.mkdir(exist_ok=True)
    (install / "Atlas.bat").write_bytes(_to_notepad((root / "packaging" / "install" / "Atlas.bat").read_text(encoding="utf-8")).encode("cp866"))
    # wscript на русской Windows читает .vbs в кодировке 1251
    vbs = (root / "packaging" / "install" / "create_shortcut.vbs").read_text(encoding="utf-8")
    (install / "create_shortcut.vbs").write_bytes(_to_notepad(vbs).encode("cp1251"))
    shutil.copy(str(root / "THIRD_PARTY_LICENSES.txt"), str(dist / "THIRD_PARTY_LICENSES.txt"))
    check = _to_notepad((root / "docs" / "WIN7_CHECK.md").read_text(encoding="utf-8"))
    (dist / "WIN7_CHECK.txt").write_bytes(check.encode("utf-8-sig"))


if __name__ == "__main__":
    assemble(sys.argv[1])
