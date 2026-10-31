# -*- mode: python ; coding: utf-8 -*-
# Сборка под Windows 7, как в curator (docs/TARGET_MACHINE.md): onedir, без UPX, без консоли.
#   python -m PyInstaller packaging/atlas.spec --noconfirm --distpath dist --workpath build/pyinstaller
#   python scripts/assemble_dist.py dist/atlas    (config/, data/, проверки — рядом с exe)

import os
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, SPECPATH)
from bundle_contents import data_files, hidden_modules  # noqa: E402

a = Analysis(
    [os.path.join(ROOT, "atlas", "__main__.py")],
    pathex=[ROOT],
    datas=data_files(ROOT),
    hiddenimports=hidden_modules(ROOT) + ["PyQt5.QtSvg"],
    excludes=["tkinter", "numpy", "PIL", "pytest"],
    noarchive=False,
)


def _is_system_crt(entry):
    """UCRT берём с целевой машины: копии со сборочной (Windows Server) там не запустятся."""
    name = os.path.basename(entry[0]).lower()
    return name == "ucrtbase.dll" or name.startswith("api-ms-win-")


# Не нужны окну на виджетах. Если что-то понадобится, check_pe_imports.py в CI сообщит о недостающей DLL.
UNUSED_QT = {
    "opengl32sw.dll", "qwebgl.dll", "qtuiotouchplugin.dll", "qt5quick.dll", "qt5qml.dll", "qt5qmlmodels.dll",
    "qt5network.dll", "qt5websockets.dll",
}


def _is_unused_qt(entry):
    return os.path.basename(entry[0]).lower() in UNUSED_QT


def _is_foreign_translation(entry):
    """Из переводов Qt нужны только русские (подписи стандартных кнопок)."""
    path = entry[0].replace("\\", "/")
    return "/translations/" in path and path.endswith(".qm") and "_ru." not in os.path.basename(path)


a.binaries = [entry for entry in a.binaries if not (_is_system_crt(entry) or _is_unused_qt(entry))]
a.datas = [entry for entry in a.datas if not _is_foreign_translation(entry)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="atlas",
    console=False,
    upx=False,
    version=os.path.join(SPECPATH, "version_info.txt"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="atlas",
)
