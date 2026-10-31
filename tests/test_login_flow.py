"""Вход: диалог, пользователи в БД, тег в верхней полосе, событие."""
import json
import shutil
from pathlib import Path

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QDialog, QInputDialog

from atlas.app import build_core, build_window, run_login, start_features
from atlas.core.config import AppPaths

REPO = Path(__file__).resolve().parent.parent


def _root(tmp_path, entries):
    root = tmp_path / "Атлас вход"
    (root / "config").mkdir(parents=True)
    (root / "data").mkdir()
    shutil.copy(str(REPO / "config" / "app.json"), str(root / "config" / "app.json"))
    shutil.copy(str(REPO / "data" / "user_colors.json"), str(root / "data" / "user_colors.json"))
    (root / "config" / "features.json").write_text(json.dumps({"features": entries}), encoding="utf-8")
    return AppPaths(root)


def _start(tmp_path, entries=None):
    entries = entries or [{"id": "login"}, {"id": "hello", "tab_order": 10}]
    ctx = build_core(_root(tmp_path, entries))
    registry = start_features(ctx)
    return ctx, registry


def _dialog():
    for widget in QApplication.topLevelWidgets():
        if widget.__class__.__name__ == "LoginDialog" and widget.isVisible():
            return widget
    return None


def test_first_run_add_self_and_login(qtbot, tmp_path, monkeypatch):
    ctx, registry = _start(tmp_path)
    window = build_window(registry)
    qtbot.addWidget(window)
    events = []
    ctx.bus.subscribe("user.logged_in", events.append)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("смирнова", True)))

    def drive():
        dialog = _dialog()
        assert dialog is not None
        assert not dialog.go_button.isEnabled()  # список пуст
        dialog.add_button.click()
        assert dialog.go_button.text() == "Войти как Смирнова"
        dialog.go_button.click()

    QTimer.singleShot(50, drive)
    assert run_login(ctx, window) is True
    qtbot.waitUntil(lambda: bool(events), timeout=1000)
    assert ctx.user.name == "Смирнова"
    assert events[0]["user"].name == "Смирнова"
    tags = window.slots.panels("shell.user")
    assert len(tags) == 1 and tags[0].name == "Смирнова"
    assert window.tab_titles() == ["Привет"]  # вкладка hello на месте
    registry.stop_all()


def test_second_run_preselects_last_user_and_cancel(qtbot, tmp_path):
    ctx, registry = _start(tmp_path)
    login = ctx.services.get("login")
    a = login.repo.add("Петров", [])
    b = login.repo.add("Иванова", [])
    login.repo.touch(b.id)
    window = build_window(registry)
    qtbot.addWidget(window)

    def cancel():
        dialog = _dialog()
        assert dialog.selected.name == "Иванова"  # входила последней
        assert "Последний вход: сегодня" in dialog.last_label.text()
        assert dialog.add_button.isVisible()
        dialog.reject()

    QTimer.singleShot(50, cancel)
    assert run_login(ctx, window) is False
    assert ctx.user is None
    assert a.id != b.id
    registry.stop_all()


def test_add_same_name_twice_gives_one_user(qtbot, tmp_path):
    ctx, registry = _start(tmp_path)
    repo = ctx.services.get("login").repo
    one = repo.add("Петров", [])
    two = repo.add("петров", [])
    assert one.id == two.id and len(repo.all()) == 1
    registry.stop_all()


def test_works_without_login_feature(qtbot, tmp_path):
    ctx, registry = _start(tmp_path, [{"id": "hello", "tab_order": 10}])
    window = build_window(registry)
    qtbot.addWidget(window)
    assert run_login(ctx, window) is True and ctx.user is None
    registry.stop_all()


def test_dialog_screenshot_renders(qtbot, tmp_path):
    from atlas.core.theme import apply_theme

    apply_theme(QApplication.instance())
    ctx, registry = _start(tmp_path)
    repo = ctx.services.get("login").repo
    for name in ("Смирнова", "Петров", "Иванова", "Кузнецова", "Соколов", "Морозова"):
        repo.add(name, [])
    from atlas.features.login.dialog import LoginDialog

    dialog = LoginDialog(repo, [], ctx.shell)
    qtbot.addWidget(dialog)
    dialog.show()
    assert len(dialog._tags) == 6
    assert dialog.grab().width() > 0
    registry.stop_all()
