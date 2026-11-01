"""presence в настоящем приложении: два «ПК» на одной базе."""
import json
import shutil
import threading
from pathlib import Path

import pytest

from atlas.app import build_core, build_window, start_features
from atlas.core.app_context import User
from atlas.core.config import AppPaths

REPO = Path(__file__).resolve().parent.parent


def _app(tmp_path, name, db_path, qtbot):
    root = tmp_path / name
    (root / "config").mkdir(parents=True)
    shutil.copy(str(REPO / "config" / "app.json"), str(root / "config" / "app.json"))
    entries = [{"id": "presence"}]
    (root / "config" / "features.json").write_text(json.dumps({"features": entries}), encoding="utf-8")
    local = {"database": {"path": str(db_path)}, "presence": {"heartbeat_s": 3600}}
    (root / "config" / "local.json").write_text(json.dumps(local), encoding="utf-8")
    ctx = build_core(AppPaths(root))
    registry = start_features(ctx)
    assert registry.failures == []
    window = build_window(registry)
    qtbot.addWidget(window)
    return ctx, registry


def _login(ctx, name):
    user = ctx.services.get("users").add(name, lambda count: "#7DB4FF")
    ctx.user = user
    ctx.bus.publish("user.logged_in", {"user": user})
    return user


def _idle(feature):
    return feature._thread is None and not feature._again


@pytest.fixture
def two(tmp_path, qtbot):
    db_path = tmp_path / "база.sqlite"
    first = _app(tmp_path, "пк1", db_path, qtbot)
    second = _app(tmp_path, "пк2", db_path, qtbot)
    yield first, second
    for _, registry in (first, second):
        registry.stop_all()


def _feature(registry):
    return registry.loaded[0].instance


def _beat(qtbot, registry):
    feature = _feature(registry)
    qtbot.waitUntil(lambda: _idle(feature), timeout=3000)
    feature._tick()
    qtbot.waitUntil(lambda: _idle(feature), timeout=3000)
    return feature


def test_sees_other_user_and_their_folder(two, qtbot):
    (ctx1, reg1), (ctx2, reg2) = two
    _login(ctx1, "Петров")
    _login(ctx2, "Кузнецова")
    part = ctx2.services.get("parts").ensure("СТ", "Вега", "В7", "Плата PWR-7")
    folder = ctx2.services.get("folders").add(part.id, r"\\srv\ф\1", "2026-10-30")
    ctx2.bus.publish("folder.opened", {"folder_id": folder.id, "part_id": part.id})
    _beat(qtbot, reg2)
    feature = _beat(qtbot, reg1)

    assert feature.label.text() == "Онлайн: Кузнецова"  # себя не показываем
    assert feature.label.toolTip() == "Кузнецова — СТ · Вега · Плата PWR-7 · 2026-10-30"
    assert [item.name for item in feature.working_on(folder.id)] == ["Кузнецова"]
    assert {item.name for item in feature.online()} == {"Петров", "Кузнецова"}
    assert ctx1.services.get_optional("presence") is feature


def test_alone_shows_nothing(two, qtbot):
    (ctx1, reg1), _ = two
    _login(ctx1, "Петров")
    feature = _beat(qtbot, reg1)
    assert feature.label.isHidden()


def test_exit_removes_user_for_others(two, qtbot):
    (ctx1, reg1), (ctx2, reg2) = two
    _login(ctx1, "Петров")
    _login(ctx2, "Кузнецова")
    _beat(qtbot, reg2)
    feature = _beat(qtbot, reg1)
    assert feature.label.text() == "Онлайн: Кузнецова"
    reg2.stop_all()
    _beat(qtbot, reg1)
    assert feature.label.isHidden()
    assert feature.online()[0].name == "Петров"


def test_folder_done_clears_folder(two, qtbot):
    (ctx1, reg1), _ = two
    _login(ctx1, "Петров")
    feature = _feature(reg1)
    feature.folder_id = 7
    ctx1.bus.publish("folder.done", {"folder_id": 8})
    assert feature.folder_id == 7
    ctx1.bus.publish("folder.done", {"folder_id": 7})
    assert feature.folder_id is None


def test_heartbeat_runs_off_gui_thread(two, qtbot, monkeypatch):
    (ctx1, reg1), _ = two
    feature = _feature(reg1)
    threads = []
    original = feature.repo.beat

    def spy(user_id, folder_id):
        threads.append(threading.current_thread())
        original(user_id, folder_id)

    monkeypatch.setattr(feature.repo, "beat", spy)
    _login(ctx1, "Петров")
    qtbot.waitUntil(lambda: _idle(feature) and bool(threads), timeout=3000)
    assert threads[0] is not threading.main_thread()


def test_database_failure_keeps_program_and_list(two, qtbot, monkeypatch):
    (ctx1, reg1), (ctx2, reg2) = two
    _login(ctx1, "Петров")
    _login(ctx2, "Кузнецова")
    _beat(qtbot, reg2)
    feature = _beat(qtbot, reg1)

    def broken(user_id, folder_id):
        raise OSError("сеть пропала")

    monkeypatch.setattr(feature.repo, "beat", broken)
    _beat(qtbot, reg1)
    assert feature.label.text() == "Онлайн: Кузнецова"


def test_no_login_means_no_heartbeat(two, qtbot):
    (ctx1, reg1), _ = two
    feature = _feature(reg1)
    feature._tick()
    assert feature._thread is None
    assert feature.repo.rows() == []
