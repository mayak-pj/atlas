"""Раскладка по типам в настоящем приложении: файлы, база, журнал, отмена, экран сравнения."""
import pytest

from tests.test_compare_flow import App

NAMES = ["a.jpg", "b.jpg", "c.jpg", "d.jpg"]


@pytest.fixture
def app(tmp_path, qtbot):
    instance = App(tmp_path, qtbot, count=4, names=NAMES, features=("compare", "sort_types"))
    folders = instance.ctx.services.get("folders")
    photos = folders.photos(instance.folder.id)
    folders.mark_photo(photos[0].id, "type:1")
    folders.mark_photo(photos[1].id, "type:2")
    folders.mark_photo(photos[2].id, "defect", "S1")
    instance.feature_sort = next(f.instance for f in instance.registry.loaded if f.spec.id == "sort_types")
    instance.wait_open()
    yield instance
    instance.stop()


def _rel(app):
    return [photo.rel_path for photo in app.ctx.services.get("folders").photos(app.folder.id)]


def _message(app):
    return app.window.statusBar().currentMessage()


def _sort(app, answer=True):
    asked = []
    app.feature_sort._ask = lambda text: asked.append(text) or answer
    app.feature_sort.sort_button.click()
    return asked


def _wait_idle(app):
    app.qtbot.waitUntil(lambda: not app.feature_sort.busy, timeout=5000)


def _wait_reloaded(app, rel):
    app.qtbot.waitUntil(lambda: any(rel in photo.path.replace("\\", "/") for photo in app.screen.model.photos), timeout=5000)


def test_sort_moves_files_database_and_reloads_compare(app):
    asked = _sort(app)
    app.qtbot.waitUntil(lambda: "Тип 1/a.jpg" in _rel(app), timeout=5000)
    _wait_idle(app)
    assert sorted(_rel(app)) == sorted(["c.jpg", "d.jpg", "Тип 1/a.jpg", "Тип 2/b.jpg"])
    assert (app.path / "Тип 1" / "a.jpg").is_file() and (app.path / "Тип 2" / "b.jpg").is_file()
    assert not (app.path / "a.jpg").exists() and (app.path / "c.jpg").is_file()  # дефект и без отметки не тронуты
    assert len(asked) == 1 and "2 фото" in asked[0] and "Тип 1 — 1" in asked[0]
    assert "Перемещено фото: 2" in _message(app)
    _wait_reloaded(app, "Тип 1/a.jpg")
    marks = {photo.name: photo.mark for photo in app.screen.model.photos}
    assert marks["a.jpg"] == "type:1" and marks["c.jpg"] == "defect"  # отметки переехали вместе с фото


def test_declined_confirmation_changes_nothing(app):
    _sort(app, answer=False)
    _wait_idle(app)
    assert (app.path / "a.jpg").is_file() and not (app.path / "Тип 1").exists()
    assert sorted(_rel(app)) == NAMES


def test_undo_restores_everything(app):
    _sort(app)
    app.qtbot.waitUntil(lambda: app.feature_sort.undo_button.isEnabled(), timeout=5000)
    app.feature_sort.undo_button.click()
    app.qtbot.waitUntil(lambda: sorted(_rel(app)) == NAMES, timeout=5000)
    _wait_idle(app)
    assert (app.path / "a.jpg").is_file() and not (app.path / "Тип 1").exists()
    assert "Возвращено фото: 2" in _message(app)
    app.qtbot.waitUntil(lambda: not app.feature_sort.undo_button.isEnabled(), timeout=5000)


def test_undo_leaves_photos_touched_since(app):
    _sort(app)
    app.qtbot.waitUntil(lambda: app.feature_sort.undo_button.isEnabled(), timeout=5000)
    folders = app.ctx.services.get("folders")
    moved = [photo for photo in folders.photos(app.folder.id) if photo.rel_path == "Тип 2/b.jpg"][0]
    (app.path / "Тип 2" / "b.jpg").rename(app.path / "Тип 2" / "b2.jpg")
    folders.move_photos([(moved.id, "Тип 2/b2.jpg")])  # человек переименовал после раскладки
    app.feature_sort.undo_button.click()
    app.qtbot.waitUntil(lambda: "a.jpg" in _rel(app), timeout=5000)
    _wait_idle(app)
    assert "Тип 2/b2.jpg" in _rel(app) and (app.path / "Тип 2" / "b2.jpg").is_file()
    assert "Изменены позже и не тронуты: 1" in _message(app)
    app.qtbot.waitUntil(lambda: not app.feature_sort.undo_button.isEnabled(), timeout=5000)


def test_busy_name_in_target_is_reported_and_others_still_move(app):
    (app.path / "Тип 1").mkdir()
    (app.path / "Тип 1" / "a.jpg").write_text("чужой", encoding="utf-8")
    _sort(app)
    app.qtbot.waitUntil(lambda: "Тип 2/b.jpg" in _rel(app), timeout=5000)
    _wait_idle(app)
    assert (app.path / "a.jpg").is_file() and (app.path / "Тип 1" / "a.jpg").read_text(encoding="utf-8") == "чужой"
    assert "Не удалось: 1" in _message(app) and "a.jpg" in _message(app)
    assert "a.jpg" in _rel(app)  # в базе фото осталось на старом месте


def test_database_failure_puts_files_back(app, monkeypatch):
    folders = app.ctx.services.get("folders")

    def broken(moves):
        raise OSError("база недоступна")

    monkeypatch.setattr(folders, "move_photos", broken)
    _sort(app)
    app.qtbot.waitUntil(lambda: "не удалось" in _message(app).lower(), timeout=5000)
    _wait_idle(app)
    assert (app.path / "a.jpg").is_file() and (app.path / "b.jpg").is_file()
    assert not (app.path / "Тип 1").exists() or not any((app.path / "Тип 1").iterdir())
    assert sorted(_rel(app)) == NAMES


def test_nothing_to_sort_says_so_and_asks_nothing(app):
    _sort(app)
    app.qtbot.waitUntil(lambda: "Перемещено" in _message(app), timeout=5000)
    _wait_idle(app)
    asked = _sort(app)
    app.qtbot.waitUntil(lambda: "нечего" in _message(app), timeout=5000)
    assert asked == []


def test_buttons_do_not_take_keyboard_focus_and_wait_for_folder(tmp_path, qtbot):
    instance = App(tmp_path, qtbot, count=2, features=("compare", "sort_types"))
    try:
        feature = next(f.instance for f in instance.registry.loaded if f.spec.id == "sort_types")
        assert not feature.sort_button.isEnabled() and not feature.undo_button.isEnabled()
        assert feature.sort_button.focusPolicy() == 0
    finally:
        instance.stop()


def test_sort_event_is_published(app):
    events = []
    app.ctx.bus.subscribe("folder.sorted", events.append)
    _sort(app)
    app.qtbot.waitUntil(lambda: bool(events), timeout=5000)
    assert events[0]["moved"] == 2 and events[0]["kind"] == "sort"
