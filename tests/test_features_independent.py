"""Приложение стартует с выключенной любой функцией."""
import json
import shutil
import sys
from pathlib import Path

import pytest

from atlas.app import build_core, build_window, start_features
from atlas.core.config import AppPaths

REPO = Path(__file__).resolve().parent.parent


def _entries():
    return json.loads((REPO / "config" / "features.json").read_text(encoding="utf-8"))["features"]


def _make_root(tmp_path, entries):
    # Кириллица и пробел в пути — как на целевой машине
    root = tmp_path / "Атлас тест"
    (root / "config").mkdir(parents=True)
    shutil.copy(str(REPO / "config" / "app.json"), str(root / "config" / "app.json"))
    (root / "config" / "features.json").write_text(json.dumps({"features": entries}), encoding="utf-8")
    return AppPaths(root)


def _start(paths):
    ctx = build_core(paths)
    return ctx, start_features(ctx)


def _forget_features():
    for name in list(sys.modules):
        if name.startswith("atlas.features."):
            del sys.modules[name]


def test_starts_with_all_features(qtbot, tmp_path):
    _, registry = _start(_make_root(tmp_path, _entries()))
    assert registry.failures == []
    window = build_window(registry)
    qtbot.addWidget(window)
    window.show()
    assert window.isVisible()
    registry.stop_all()


@pytest.mark.parametrize("disabled", [entry["id"] for entry in _entries()])
def test_starts_without_feature(qtbot, tmp_path, disabled):
    _forget_features()
    entries = [dict(entry, enabled=entry["id"] != disabled) for entry in _entries()]
    _, registry = _start(_make_root(tmp_path, entries))
    # Зависимая через requires функция может не запуститься, остальные ошибки недопустимы
    assert not [f for f in registry.failures if f.stage != "dependencies"]
    assert disabled not in [item.spec.id for item in registry.loaded]
    assert "atlas.features.{}".format(disabled) not in sys.modules
    window = build_window(registry)
    qtbot.addWidget(window)
    window.show()
    registry.stop_all()


def test_starts_with_no_features(qtbot, tmp_path):
    _, registry = _start(_make_root(tmp_path, []))
    window = build_window(registry)
    qtbot.addWidget(window)
    assert window.centralWidget().count() == 0


def test_hello_tab_follows_features_json(qtbot, tmp_path):
    entries = [{"id": "hello", "enabled": True}]
    _, registry = _start(_make_root(tmp_path / "on", entries))
    window = build_window(registry)
    qtbot.addWidget(window)
    assert window.centralWidget().tabText(0) == "Привет"
    registry.stop_all()

    _, registry = _start(_make_root(tmp_path / "off", []))
    window = build_window(registry)
    qtbot.addWidget(window)
    assert window.centralWidget().count() == 0
