import itertools
import sys
import textwrap

import pytest

from atlas.core.app_context import AppContext
from atlas.core.bus import EventBus
from atlas.core.config import AppPaths, Config, FeatureEntry
from atlas.core.db import Database
from atlas.core.registry import EVENT_FAILED, FeatureRegistry
from atlas.core.services import ServiceRegistry

_counter = itertools.count()


class Env:
    def __init__(self, tmp_path, monkeypatch):
        self.package = "fakefeats{}".format(next(_counter))
        self.base = tmp_path / self.package
        self.base.mkdir()
        (self.base / "__init__.py").write_text("", encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))
        self.tmp = tmp_path

    def feature(self, fid, requires=(), optional=(), tab_order=None, body="pass", init_extra="", sql=None):
        folder = self.base / fid
        folder.mkdir()
        (folder / "__init__.py").write_text(
            textwrap.dedent(
                """\
                from atlas.core.feature import FeatureSpec
                {extra}
                FEATURE = FeatureSpec(id={fid!r}, title={fid!r}, requires={req!r}, optional={opt!r},
                                      tab_order={order!r}, factory="{pkg}.{fid}.ui:F")
                """
            ).format(extra=init_extra, fid=fid, req=list(requires), opt=list(optional), order=tab_order, pkg=self.package),
            encoding="utf-8",
        )
        (folder / "ui.py").write_text(
            "from atlas.core.feature import Feature\nclass F(Feature):\n" + textwrap.indent(body, "    ") + "\n",
            encoding="utf-8",
        )
        if sql is not None:
            (folder / "migrations").mkdir()
            (folder / "migrations" / "001_init.sql").write_text(sql, encoding="utf-8")

    def registry(self, entries):
        paths = AppPaths(self.tmp)
        config = Config(paths, {}, [e if isinstance(e, FeatureEntry) else FeatureEntry(e) for e in entries])
        db = Database(self.tmp / "t.sqlite", retry_delays=())
        ctx = AppContext(config, paths, db, EventBus(), ServiceRegistry())
        return FeatureRegistry(ctx, package=self.package)


@pytest.fixture
def env(qapp, tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


def ids(registry):
    return [item.spec.id for item in registry.loaded]


def failed(registry):
    return {f.id: f.stage for f in registry.failures}


def test_dependency_order_overrides_config_order(env):
    env.feature("a", requires=["b"])
    env.feature("b")
    registry = env.registry(["a", "b"])
    registry.start_all()
    assert ids(registry) == ["b", "a"]


def test_optional_starts_first_but_may_be_absent(env):
    env.feature("a", optional=["b", "absent"])
    env.feature("b")
    registry = env.registry(["a", "b"])
    registry.start_all()
    assert ids(registry) == ["b", "a"]
    assert not registry.failures


def test_optional_cycle_is_allowed(env):
    env.feature("a", optional=["b"])
    env.feature("b", optional=["a"])
    registry = env.registry(["a", "b"])
    registry.start_all()
    assert sorted(ids(registry)) == ["a", "b"] and not registry.failures


def test_disabled_is_not_imported(env):
    env.feature("off", init_extra="raise RuntimeError('нельзя импортировать')")
    registry = env.registry([FeatureEntry("off", enabled=False)])
    registry.start_all()
    assert not registry.failures
    assert "{}.off".format(env.package) not in sys.modules


def test_import_error_is_isolated_and_reported(env, qtbot):
    env.feature("bad", init_extra="raise RuntimeError('сломано')")
    env.feature("good")
    registry = env.registry(["bad", "good", "missing"])
    received = []
    registry.ctx.bus.subscribe(EVENT_FAILED, received.append)
    registry.start_all()
    assert ids(registry) == ["good"]
    assert failed(registry) == {"bad": "import", "missing": "import"}
    assert [item["id"] for item in received] == ["bad", "missing"]
    assert "сломано" in received[0]["error"]


def test_template_id_is_rejected(env):
    registry = env.registry(["_template", "a.b"])
    registry.start_all()
    assert failed(registry) == {"_template": "import", "a.b": "import"}


def test_wrong_spec_id_fails(env):
    env.feature("a", init_extra="")
    (env.base / "a" / "__init__.py").write_text(
        "from atlas.core.feature import FeatureSpec\nFEATURE = FeatureSpec(id='z', title='z', factory='x:y')\n",
        encoding="utf-8",
    )
    registry = env.registry(["a"])
    registry.start_all()
    assert failed(registry) == {"a": "import"}


def test_on_start_error_stops_dependents_only(env):
    env.feature("bad", body="def on_start(self):\n    raise RuntimeError('x')")
    env.feature("child", requires=["bad"])
    env.feature("ok")
    registry = env.registry(["bad", "child", "ok"])
    registry.start_all()
    assert ids(registry) == ["ok"]
    assert failed(registry) == {"bad": "start", "child": "dependencies"}


def test_missing_requirement_fails(env):
    env.feature("a", requires=["absent"])
    registry = env.registry(["a"])
    registry.start_all()
    assert failed(registry) == {"a": "dependencies"}


def test_requires_cycle_fails_members_and_keeps_others(env):
    env.feature("a", requires=["b"])
    env.feature("b", requires=["a"])
    env.feature("c")
    registry = env.registry(["a", "b", "c"])
    registry.start_all()
    assert ids(registry) == ["c"]
    assert failed(registry) == {"a": "dependencies", "b": "dependencies"}


def test_failed_on_start_gets_on_stop(env):
    # Подписки и сервисы, сделанные до ошибки, не должны остаться висеть
    env.feature(
        "a",
        body=(
            "def on_start(self):\n"
            "    self.ctx.services.register('svc', self)\n"
            "    raise RuntimeError('x')\n"
            "def on_stop(self):\n"
            "    self.ctx.services.unregister('svc')"
        ),
    )
    registry = env.registry(["a"])
    registry.start_all()
    assert registry.ctx.services.get_optional("svc") is None


def test_create_tab_error_is_isolated(qtbot, env):
    env.feature("a", tab_order=1, body="def create_tab(self):\n    raise RuntimeError('x')")
    registry = env.registry(["a"])
    registry.start_all()
    assert failed(registry) == {"a": "start"}


def test_tabs_sorted_with_config_override(qtbot, env):
    tab = "def create_tab(self):\n    from PyQt5.QtWidgets import QWidget\n    return QWidget()"
    env.feature("a", tab_order=1, body=tab)
    env.feature("b", tab_order=2, body=tab)
    env.feature("c", body=tab)  # без tab_order — без вкладки
    registry = env.registry([FeatureEntry("a", tab_order=5), "b", "c"])
    registry.start_all()
    assert [item.spec.id for item in registry.tabs()] == ["b", "a"]
    registry.stop_all()


def test_stop_order_reversed_and_error_isolated(env):
    log_body = (
        "def on_stop(self):\n"
        "    self.ctx.services.get('log').append(type(self).__module__.split('.')[1])\n"
        "    raise RuntimeError('x')"
    )
    env.feature("a", body=log_body)
    env.feature("b", body=log_body)
    registry = env.registry(["a", "b"])
    calls = []
    registry.ctx.services.register("log", calls)
    registry.start_all()
    registry.stop_all()
    assert calls == ["b", "a"]


def test_migration_error_is_isolated(env):
    env.feature("bad", sql="THIS IS NOT SQL;")
    env.feature("good", sql="CREATE TABLE good_t (id INTEGER);")
    registry = env.registry(["bad", "good"])
    registry.start_all()
    assert ids(registry) == ["good"]
    assert failed(registry) == {"bad": "migrations"}
    names = registry.ctx.db.read(lambda c: [r[0] for r in c.execute("SELECT name FROM sqlite_master")])
    assert "good_t" in names
