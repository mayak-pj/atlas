import json
import threading

import pytest

from atlas.core.bus import EventBus
from atlas.core.config import AppPaths, Config, ConfigError
from atlas.core.services import ServiceRegistry


def test_publish_reaches_subscribers_and_unsubscribe(qapp):
    bus = EventBus()
    got = []
    unsubscribe = bus.subscribe("e", got.append)
    bus.publish("e", {"a": 1})
    unsubscribe()
    bus.publish("e", {"a": 2})
    assert got == [{"a": 1}]


def test_handler_error_does_not_stop_others(qapp):
    bus = EventBus()
    got = []

    def bad(_):
        raise RuntimeError("x")

    bus.subscribe("e", bad)
    bus.subscribe("e", got.append)
    bus.publish("e")
    assert got == [{}]


def test_unsubscribe_during_dispatch(qapp):
    bus = EventBus()
    got = []
    unsubscribe = bus.subscribe("e", lambda _: unsubscribe())
    bus.subscribe("e", got.append)
    bus.publish("e")
    bus.publish("e")
    assert len(got) == 2


def test_publish_from_thread_runs_handler_in_bus_thread(qtbot):
    bus = EventBus()
    threads = []
    bus.subscribe("e", lambda _: threads.append(threading.current_thread()))
    worker = threading.Thread(target=bus.publish, args=("e",))
    worker.start()
    worker.join()
    qtbot.waitUntil(lambda: bool(threads), timeout=2000)
    assert threads == [threading.current_thread()]


def test_services():
    services = ServiceRegistry()
    assert services.get_optional("s") is None
    with pytest.raises(KeyError):
        services.get("s")
    services.register("s", 1)
    assert services.get("s") == 1
    with pytest.raises(ValueError):
        services.register("s", 2)
    services.unregister("s")
    assert services.get_optional("s") is None


def _paths(tmp_path, app='{"a": {"b": 1, "c": 2}}', features='{"features": [{"id": "x"}]}'):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "app.json").write_text(app, encoding="utf-8")
    (tmp_path / "config" / "features.json").write_text(features, encoding="utf-8")
    return AppPaths(tmp_path)


def test_local_overrides_app_deeply_and_bom_is_ok(tmp_path):
    paths = _paths(tmp_path)
    (paths.config / "local.json").write_bytes(json.dumps({"a": {"b": 9}}).encode("utf-8-sig"))
    config = Config.load(paths)
    assert config.get("a.b") == 9
    assert config.get("a.c") == 2
    assert config.get("a.z", "нет") == "нет"
    assert config.features[0].id == "x" and config.features[0].enabled


@pytest.mark.parametrize(
    "app,features",
    [("{плохо", '{"features": []}'), ("{}", "[]"), ("{}", '{"features": [{"enabled": true}]}')],
)
def test_bad_config_raises_config_error(tmp_path, app, features):
    with pytest.raises(ConfigError):
        Config.load(_paths(tmp_path, app, features))


def test_missing_config_raises_config_error(tmp_path):
    with pytest.raises(ConfigError):
        Config.load(AppPaths(tmp_path))


def test_resolve_relative_and_absolute(tmp_path):
    paths = AppPaths(tmp_path)
    assert paths.resolve("var/x") == tmp_path / "var" / "x"
    assert paths.resolve(str(tmp_path / "y")) == tmp_path / "y"
