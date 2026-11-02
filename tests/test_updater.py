"""Установка на сетевом диске: пути, публикация, сверка версии, предложение обновиться."""
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

from atlas import __version__, publish as publish_module
from atlas.app import build_core, start_features
from atlas.core import release, ui_state
from atlas.core.config import AppPaths, Config
from atlas.features.updater import logic

REPO = Path(__file__).resolve().parent.parent


def _load_script(name):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, str(REPO / "scripts" / (name + ".py")))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build(folder):
    """Распакованная сборка, как после assemble_dist."""
    (folder / "_internal" / "Подпапка").mkdir(parents=True)
    (folder / "atlas.exe").write_bytes(b"exe")
    (folder / "_internal" / "Подпапка" / "lib.dll").write_bytes(b"lib" * 1000)
    (folder / "config").mkdir()
    (folder / "config" / "app.json").write_text("{}", encoding="utf-8")
    (folder / "config" / "local.json").write_text('{"чужая": 1}', encoding="utf-8")
    for junk in ("logs", "var", "reports"):
        (folder / junk).mkdir()
        (folder / junk / "след.txt").write_text("x", encoding="utf-8")
    (folder / "install").mkdir()
    (folder / "install" / "Atlas.bat").write_text("новый", encoding="utf-8")
    return folder


@pytest.fixture
def sites(tmp_path):
    source = tmp_path / "Распакованная сборка"
    source.mkdir()
    home = tmp_path / "Общая папка !!!" / "Атлас"
    home.mkdir(parents=True)
    return _build(source), home


# --- пути ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,parsed", [
    ("1.2.3", (1, 2, 3)), (" 0.10.57\r\n", (0, 10, 57)), ("..", None), ("1.2.x", None), ("", None),
    ("../../evil", None), ("1\\2", None), ("١.٢", None),
])
def test_parse_version(text, parsed):
    assert release.parse_version(text) == parsed


def test_home_of_only_inside_release_version_folder(tmp_path):
    assert release.home_of(tmp_path / "Атлас" / "release" / "1.2.3") == tmp_path / "Атлас"
    assert release.home_of(tmp_path / "Атлас" / "release" / "старая") is None
    assert release.home_of(tmp_path / "Атлас" / "1.2.3") is None
    assert release.home_of(tmp_path / "atlas") is None


def test_plain_copy_keeps_everything_in_one_folder(tmp_path):
    paths = AppPaths(tmp_path)
    assert paths.home == tmp_path and paths.release_dir is None
    assert paths.logs == tmp_path / "logs" and paths.resolve("var/a.sqlite") == tmp_path / "var" / "a.sqlite"


def test_installed_settings_and_data_survive_a_new_version(tmp_path):
    """Главное обещание раскладки: относительные пути ведут в папку установки, а не в папку версии."""
    home = tmp_path / "Атлас"
    program = home / "release" / "1.2.3"
    (program / "config").mkdir(parents=True)
    (home / "config").mkdir()
    (program / "config" / "app.json").write_text('{"a": 1, "b": 1}', encoding="utf-8")
    (program / "config" / "features.json").write_text('{"features": []}', encoding="utf-8")
    (home / "config" / "local.json").write_text('{"b": 2}', encoding="utf-8")
    paths = AppPaths(program, release.home_of(program))
    config = Config.load(paths)
    assert (config.get("a"), config.get("b")) == (1, 2)
    assert paths.resolve("var/atlas.sqlite") == home / "var" / "atlas.sqlite"
    assert paths.logs == home / "logs" and paths.data == program / "data" and paths.release_dir == home / "release"


def test_user_choice_is_per_user_in_shared_install(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Мой профиль"))
    paths = AppPaths(tmp_path / "Атлас" / "release" / "1.2.3", tmp_path / "Атлас")
    assert ui_state.save(paths, "theme", "light")
    assert (tmp_path / "Мой профиль" / "Atlas" / "ui_state.json").is_file()
    assert ui_state.load(paths) == {"theme": "light"}
    assert not (tmp_path / "Атлас" / "var").exists()


# --- version.txt --------------------------------------------------------------------
def test_active_version_tolerates_notepad_and_rejects_garbage(tmp_path):
    assert release.read_active_version(tmp_path) is None
    (tmp_path / "version.txt").write_bytes(b"\xef\xbb\xbf1.2.3\r\n")
    assert release.read_active_version(tmp_path) == "1.2.3"
    (tmp_path / "version.txt").write_text("../evil", encoding="utf-8")
    assert release.read_active_version(tmp_path) is None
    (tmp_path / "version.txt").write_bytes(b"\xff\xfe\x00")
    assert release.read_active_version(tmp_path) is None


def test_written_version_is_readable_by_bat(tmp_path):
    release.write_active_version(tmp_path, "1.2.3")
    assert (tmp_path / "version.txt").read_bytes() == b"1.2.3\r\n"  # без BOM: его прочитал бы set /p
    assert [item.name for item in tmp_path.iterdir()] == ["version.txt"]


# --- публикация ----------------------------------------------------------------------
def test_publish_copies_program_without_traces_of_runs(sites):
    source, home = sites
    assert publish_module.publish(source, home, "1.2.3") == ("1.2.3", False)
    target = home / "release" / "1.2.3"
    assert (target / "atlas.exe").read_bytes() == b"exe"
    assert (target / "_internal" / "Подпапка" / "lib.dll").is_file()
    assert (target / "config" / "app.json").is_file()
    assert not (target / "config" / "local.json").exists()
    assert not any((target / junk).exists() for junk in ("logs", "var", "reports"))
    assert release.read_active_version(home / "release") == "1.2.3"
    assert (home / "Atlas.bat").read_text(encoding="utf-8") == "новый"
    assert not list(home.rglob("*.part"))


def test_publish_does_not_touch_settings_and_data_of_install(sites):
    source, home = sites
    (home / "config").mkdir()
    (home / "config" / "local.json").write_text('{"свои": 1}', encoding="utf-8")
    (home / "var").mkdir()
    (home / "var" / "atlas.sqlite").write_bytes(b"db")
    publish_module.publish(source, home, "1.2.3")
    assert (home / "config" / "local.json").read_text(encoding="utf-8") == '{"свои": 1}'
    assert (home / "var" / "atlas.sqlite").read_bytes() == b"db"


def test_new_version_leaves_the_old_one_for_people_working_in_it(sites):
    source, home = sites
    publish_module.publish(source, home, "1.2.3")
    publish_module.publish(source, home, "1.2.4")
    assert (home / "release" / "1.2.3" / "atlas.exe").is_file()
    assert release.read_active_version(home / "release") == "1.2.4"


@pytest.mark.parametrize("step", ["copy", "verify", "rename"])
def test_failed_publish_keeps_active_version(sites, monkeypatch, step):
    source, home = sites
    publish_module.publish(source, home, "1.2.3")

    def boom(*args, **kwargs):
        raise OSError("сеть пропала")

    if step == "copy":
        monkeypatch.setattr(publish_module.shutil, "copyfile", boom)
    elif step == "verify":
        real = publish_module._digest
        monkeypatch.setattr(publish_module, "_digest", lambda path: "другой" if ".part" in str(path) else real(path))
    else:
        monkeypatch.setattr(Path, "rename", boom)
    with pytest.raises((OSError, publish_module.PublishError)):
        publish_module.publish(source, home, "1.2.4")
    assert release.read_active_version(home / "release") == "1.2.3"
    assert not (home / "release" / "1.2.4").exists()
    assert not (home / "release" / "1.2.4.part").exists()


def test_publish_refuses_old_build_and_wrong_folder(sites, tmp_path):
    source, home = sites
    publish_module.publish(source, home, "1.2.10")
    with pytest.raises(publish_module.PublishError, match="более новая"):
        publish_module.publish(source, home, "1.2.9")  # 9 < 10: сравнение числами, а не строками
    assert release.read_active_version(home / "release") == "1.2.10"
    with pytest.raises(publish_module.PublishError, match="Нет папки"):
        publish_module.publish(source, tmp_path / "опечатка", "1.2.11")
    assert not (tmp_path / "опечатка").exists()
    (source / "atlas.exe").unlink()
    with pytest.raises(publish_module.PublishError, match="собранную"):
        publish_module.publish(source, home, "1.2.11")


def test_run_writes_report_for_notepad(sites):
    source, home = sites
    paths = AppPaths(source)
    assert publish_module.run(paths, str(home)) == publish_module.OK
    text = (source / "reports" / "publish.txt").read_bytes()
    assert text.startswith(b"\xef\xbb\xbf") and b"\r\n" in text and __version__.encode() in text
    assert publish_module.run(paths, None) == publish_module.BAD_ARGS
    assert publish_module.run(paths, str(home / "нет")) == publish_module.FAILED
    assert "ОШИБКА" in (source / "reports" / "publish.txt").read_text(encoding="utf-8-sig")


# --- сверка ---------------------------------------------------------------------------
def _published(home, version):
    (home / "release" / version).mkdir(parents=True, exist_ok=True)
    (home / "release" / version / "atlas.exe").write_bytes(b"exe")
    release.write_active_version(home / "release", version)


def test_offer_only_for_another_existing_version(tmp_path):
    assert logic.find_offer(None, "1.0.0") is None
    assert logic.find_offer(tmp_path / "нет диска", "1.0.0") is None
    _published(tmp_path, "1.2.3")
    assert logic.find_offer(tmp_path / "release", "1.2.3") is None
    offer = logic.find_offer(tmp_path / "release", "1.0.0")
    assert offer.version == "1.2.3" and offer.exe == tmp_path / "release" / "1.2.3" / "atlas.exe"
    assert logic.find_offer(tmp_path / "release", "2.0.0").version == "1.2.3"  # откат
    release.write_active_version(tmp_path / "release", "9.9.9")  # в файле версия, которой нет на диске
    assert logic.find_offer(tmp_path / "release", "1.0.0") is None


def test_launch_starts_a_separate_process_in_its_folder(tmp_path):
    marker = tmp_path / "Новая версия" / "запущено.txt"
    marker.parent.mkdir()
    script = marker.parent / "run.py"
    script.write_text(
        "import os, pathlib\npathlib.Path('запущено.txt').write_text(os.environ['PYINSTALLER_RESET_ENVIRONMENT'])\n",
        encoding="utf-8")
    calls = []
    real = logic.subprocess.Popen
    logic.subprocess.Popen = lambda args, **kw: calls.append(real([sys.executable, str(script)], **kw))
    try:
        logic.launch(script)
    finally:
        logic.subprocess.Popen = real
    calls[0].wait(30)
    assert marker.read_text() == "1"


# --- функция в окне ------------------------------------------------------------------
def _app(tmp_path, home_version=None, features=("updater",)):
    home = tmp_path / "Атлас"
    program = home / "release" / __version__
    (program / "config").mkdir(parents=True)
    shutil.copy(str(REPO / "config" / "app.json"), str(program / "config" / "app.json"))
    (program / "config" / "features.json").write_text(
        json.dumps({"features": [{"id": item} for item in features]}), encoding="utf-8")
    if home_version:
        _published(home, home_version)
    return AppPaths(program, home)




def _feature(registry):
    return next(item.instance for item in registry.loaded if item.spec.id == "updater")


def _live_logic():
    """Модуль, который видит функция: другие тесты выгружают функции и загружают заново."""
    return sys.modules["atlas.features.updater.logic"]


def test_asks_only_after_window_is_shown_then_restarts(qtbot, tmp_path, monkeypatch):
    ctx = build_core(_app(tmp_path, "99.0.0"))
    registry = start_features(ctx)
    qtbot.addWidget(ctx.shell)
    feature = _feature(registry)
    qtbot.waitUntil(lambda: feature.offer is not None, timeout=5000)
    assert feature.offer.version == "99.0.0"
    asked, launched = [], []
    monkeypatch.setattr(feature, "_confirm", lambda: asked.append(1) or True)
    monkeypatch.setattr(_live_logic(), "launch", launched.append)
    monkeypatch.setattr("atlas.features.updater.ui.QApplication.quit", lambda: None)
    feature._ask_when_ready()
    assert not asked and feature.timer.isActive()  # окно ещё закрыто: идёт вход
    ctx.shell.show()
    qtbot.waitUntil(lambda: bool(asked), timeout=3000)
    assert launched == [feature.offer.exe] and not feature.timer.isActive()
    registry.stop_all()


def test_later_does_not_restart_and_failed_launch_keeps_working(qtbot, tmp_path, monkeypatch):
    ctx = build_core(_app(tmp_path, "99.0.0"))
    registry = start_features(ctx)
    qtbot.addWidget(ctx.shell)
    feature = _feature(registry)
    qtbot.waitUntil(lambda: feature.offer is not None, timeout=5000)
    launched, quits = [], []
    monkeypatch.setattr(_live_logic(), "launch", launched.append)
    monkeypatch.setattr("atlas.features.updater.ui.QApplication.quit", lambda: quits.append(1))
    monkeypatch.setattr(feature, "_confirm", lambda: False)
    ctx.shell.show()
    feature._ask_when_ready()
    assert not launched and not quits

    def fail(exe):
        raise OSError("нет доступа")

    monkeypatch.setattr(_live_logic(), "launch", fail)
    feature.restart()
    assert not quits and ctx.shell.isVisible()
    registry.stop_all()


def test_same_version_and_plain_copy_are_silent(qtbot, tmp_path):
    ctx = build_core(_app(tmp_path, __version__))
    registry = start_features(ctx)
    qtbot.addWidget(ctx.shell)
    feature = _feature(registry)
    qtbot.wait(200)
    assert feature.offer is None and not feature.timer.isActive()
    registry.stop_all()


# --- файлы поставки -------------------------------------------------------------------
def test_version_is_the_same_everywhere():
    info = (REPO / "packaging" / "version_info.txt").read_text(encoding="utf-8")
    assert "StringStruct('FileVersion', '{}')".format(__version__) in info
    assert "filevers=({}, 0)".format(", ".join(__version__.split("."))) in info
    assert release.parse_version(__version__) is not None


def test_set_version_updates_all_places(tmp_path):
    (tmp_path / "atlas").mkdir()
    (tmp_path / "packaging").mkdir()
    shutil.copy(str(REPO / "atlas" / "__init__.py"), str(tmp_path / "atlas"))
    shutil.copy(str(REPO / "packaging" / "version_info.txt"), str(tmp_path / "packaging"))
    script = _load_script("set_version")
    script.set_version("3.4.567", tmp_path)
    info = (tmp_path / "packaging" / "version_info.txt").read_text(encoding="utf-8")
    assert '__version__ = "3.4.567"' in (tmp_path / "atlas" / "__init__.py").read_text(encoding="utf-8")
    assert len(re.findall(r"vers=\(3, 4, 567, 0\)", info)) == 2 and len(re.findall(r"', '3\.4\.567'\)", info)) == 2
    with pytest.raises(SystemExit):
        script.set_version("1.2", tmp_path)


def test_assemble_adds_install_files_in_windows_encodings(tmp_path):
    root = tmp_path / "исходники"
    for name in ("config", "data", "templates", "packaging", "docs"):
        shutil.copytree(str(REPO / name), str(root / name))
    shutil.copy(str(REPO / "THIRD_PARTY_LICENSES.txt"), str(root))
    dist = tmp_path / "dist"
    dist.mkdir()
    _load_script("assemble_dist").assemble(dist, root)
    bat = (dist / "install" / "Atlas.bat").read_bytes()
    assert b"\r\n" in bat and "не запущен".encode("cp866") in bat
    assert "Ярлык".encode("cp1251") in (dist / "install" / "create_shortcut.vbs").read_bytes()
    assert (dist / "publish.bat").is_file()
