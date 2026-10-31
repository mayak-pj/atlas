"""Функция импортирует только core, shared и себя. Ядро и shared не знают о функциях."""
import ast
from pathlib import Path

import atlas

ATLAS_DIR = Path(atlas.__file__).parent
FEATURES_DIR = ATLAS_DIR / "features"


def _module_parts(path, root):
    parts = list(path.relative_to(root).with_suffix("").parts)
    return parts[:-1] if parts[-1] == "__init__" else parts


def _is_package_file(path):
    return path.name == "__init__.py"


def imported_modules(path, root):
    """Абсолютные имена всего, что импортирует файл, включая import_module("...")."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parts = _module_parts(path, root)
    package = parts if _is_package_file(path) else parts[:-1]
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                prefix = ".".join(base + ([node.module] if node.module else []))
            else:
                prefix = node.module
            found.append(prefix)
            found.extend("{}.{}".format(prefix, alias.name) for alias in node.names)
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if name in ("import_module", "__import__") and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.append(arg.value)
    return found


def feature_violations(path, root, feature_id):
    own = "atlas.features.{}".format(feature_id)
    bad = []
    for name in imported_modules(path, root):
        if name == "atlas.features" or (name.startswith("atlas.features.") and not (
            name == own or name.startswith(own + ".")
        )):
            bad.append(name)
    return bad


def _feature_dirs():
    return [p for p in FEATURES_DIR.iterdir() if p.is_dir() and p.name != "__pycache__"]


def test_features_import_only_core_and_shared():
    root = ATLAS_DIR.parent
    problems = []
    for directory in _feature_dirs():
        for path in directory.rglob("*.py"):
            for name in feature_violations(path, root, directory.name):
                problems.append("{}: {}".format(path, name))
    assert not problems, "\n".join(problems)


def test_core_and_shared_do_not_import_features():
    root = ATLAS_DIR.parent
    problems = []
    for layer in ("core", "shared"):
        for path in (ATLAS_DIR / layer).rglob("*.py"):
            for name in imported_modules(path, root):
                if name.startswith("atlas.features"):
                    problems.append("{}: {}".format(path, name))
    assert not problems, "\n".join(problems)


def test_windows_only_imports_are_in_win_files():
    root = ATLAS_DIR.parent
    problems = []
    for path in ATLAS_DIR.rglob("*.py"):
        if path.stem.endswith("_win"):
            continue
        for name in imported_modules(path, root):
            if name.split(".")[0] in ("win32com", "pythoncom", "pywintypes", "win32api"):
                problems.append("{}: {}".format(path, name))
    assert not problems, "\n".join(problems)


def _check(tmp_path, source, feature="a", name="ui.py"):
    path = tmp_path / "atlas" / "features" / feature / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return feature_violations(path, tmp_path, feature)


def test_detector_catches_all_import_forms(tmp_path):
    assert _check(tmp_path, "import atlas.features.b")
    assert _check(tmp_path, "from atlas.features.b import x")
    assert _check(tmp_path, "from atlas.features import b")
    assert _check(tmp_path, "from ..b import x")
    assert _check(tmp_path, "from .. import b")
    assert _check(tmp_path, "import importlib\nimportlib.import_module('atlas.features.b')")


def test_detector_allows_own_and_core(tmp_path):
    assert not _check(tmp_path, "from atlas.core.feature import Feature")
    assert not _check(tmp_path, "from atlas.shared import x")
    assert not _check(tmp_path, "from atlas.features.a.logic import x")
    assert not _check(tmp_path, "from .logic import x")
    assert not _check(tmp_path, "from . import logic")
