"""Содержимое сборки и запуск проверок через настоящую точку входа. Сам exe проверяется в CI."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _load(relative):
    path = REPO / relative
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(*args, **kwargs):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    return subprocess.run([sys.executable] + list(args), cwd=str(REPO), env=env, timeout=150, **kwargs)


# --- содержимое сборки --------------------------------------------------------------
def test_every_feature_module_is_bundled():
    modules = _load("packaging/bundle_contents.py").hidden_modules(str(REPO))
    for entry in json.loads((REPO / "config" / "features.json").read_text(encoding="utf-8"))["features"]:
        assert "atlas.features.{}".format(entry["id"]) in modules
    assert "atlas.features.login.ui" in modules  # factory: импорт по имени
    assert "atlas.features.login.dialog" in modules
    assert "atlas.selfcheck" in modules and "atlas.dbcheck" in modules


def test_template_and_tests_are_not_bundled():
    contents = _load("packaging/bundle_contents.py")
    names = contents.hidden_modules(str(REPO)) + [src for src, _ in contents.data_files(str(REPO))]
    assert not [name for name in names if "_template" in name or "tests" in name.replace("\\", ".").split(".")]


def test_every_non_code_resource_is_bundled():
    pairs = _load("packaging/bundle_contents.py").data_files(str(REPO))
    targets = {str(Path(dest) / Path(src).name).replace("\\", "/") for src, dest in pairs}
    assert "atlas/core/theme/atlas.qss" in targets
    assert "atlas/core/theme/tokens.json" in targets
    assert "atlas/features/login/migrations/001_init.sql" in targets
    assert "atlas/features/hello/migrations/001_init.sql" in targets


def test_assemble_places_settings_and_checks_next_to_exe(tmp_path):
    root = tmp_path / "исходники"
    for name in ("config", "data", "packaging", "docs"):
        shutil.copytree(str(REPO / name), str(root / name))
    shutil.copy(str(REPO / "THIRD_PARTY_LICENSES.txt"), str(root))
    (root / "config" / "local.json").write_text("{}", encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()

    _load("scripts/assemble_dist.py").assemble(dist, root)

    assert (dist / "config" / "features.json").is_file()
    assert (dist / "data" / "user_colors.json").is_file()
    assert not (dist / "config" / "local.json").exists()
    bat = (dist / "check_db.bat").read_bytes()
    assert b"\r\n" in bat and b"\n" not in bat.replace(b"\r\n", b"")
    assert "Папка" in bat.decode("cp866")
    assert (dist / "WIN7_CHECK.txt").read_bytes().startswith(b"\xef\xbb\xbf")


# --- --selfcheck -----------------------------------------------------------------------
def test_selfcheck_walks_login_and_tabs(tmp_path):
    out = tmp_path / "Отчёт проверки"
    result = _run("-m", "atlas", "--selfcheck", str(out))
    text = (out / "selfcheck.txt").read_text(encoding="utf-8-sig")
    assert result.returncode == 0, text
    assert "ВСЁ РАБОТАЕТ" in text
    for name in ("login_empty", "login", "tab_hello"):
        assert (out / "{}.png".format(name)).stat().st_size > 0
    assert not list(out.glob("work_*")), "временная копия не удалена"


def test_selfcheck_reports_a_broken_feature(tmp_path):
    root = tmp_path / "программа"
    shutil.copytree(str(REPO / "config"), str(root / "config"), ignore=shutil.ignore_patterns("local.json"))
    shutil.copytree(str(REPO / "data"), str(root / "data"))
    features = {"features": [{"id": "login"}, {"id": "hello", "tab_order": 10}, {"id": "no_such_feature"}]}
    (root / "config" / "features.json").write_text(json.dumps(features), encoding="utf-8")
    out = tmp_path / "out"
    code = (
        "import sys; from pathlib import Path; from atlas.core.config import AppPaths; from atlas.selfcheck import run; "
        "sys.exit(run(Path(sys.argv[1]), AppPaths(Path(sys.argv[2]))))"
    )
    result = _run("-c", code, str(out), str(root))
    text = (out / "selfcheck.txt").read_text(encoding="utf-8-sig")
    assert result.returncode == 1, text
    assert "ОШИБКА функция no_such_feature" in text
    assert "ЕСТЬ ОШИБКИ" in text


def test_selfcheck_without_folder_is_a_usage_error():
    assert _run("-m", "atlas", "--selfcheck").returncode == 2


def test_dbcheck_rejects_bad_seconds(tmp_path):
    assert _run("-m", "atlas", "--dbcheck", str(tmp_path), "--seconds", "x").returncode == 2


@pytest.mark.parametrize("name", ["check_win7.bat", "check_db.bat"])
def test_bat_files_fit_cp866(name):
    (REPO / "packaging" / "bat" / name).read_text(encoding="utf-8").encode("cp866")
