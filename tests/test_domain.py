"""Таблицы ядра и сервисы users, parts, folders."""
import sqlite3

import pytest

from atlas.core import domain
from atlas.core.db import Database, MigrationRunner
from atlas.core.domain.folders import FoldersService, clean_rel_path, path_key
from atlas.core.domain.parts import PartsService
from atlas.core.domain.text import normalize_name
from atlas.core.domain.users import UsersService
from atlas.core.services import ServiceRegistry
from atlas.features import login

LOGIN_MIGRATIONS = login.__file__.replace("__init__.py", "migrations")


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "база.sqlite")
    domain.migrate(database)
    return database


@pytest.fixture
def parts(db):
    return PartsService(db)


@pytest.fixture
def folders(db):
    return FoldersService(db)


@pytest.fixture
def part(parts):
    return parts.ensure("A", "Орион-24", "N15", "SSD XS-2280")


def test_tables_exist_and_migration_runs_once(db):
    names = db.read(lambda c: {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")})
    assert {"users", "projects", "devices", "parts", "folders", "photos"} <= names
    assert domain.migrate(db) == []


def test_services_are_registered(db):
    services = ServiceRegistry()
    domain.register_services(db, services)
    assert all(services.get_optional(name) for name in ("users", "parts", "folders"))


@pytest.mark.parametrize("variant", ["SSD XS-2280", "ssd_xs 2280", "  SSDXS2280 ", "ＳＳＤ XS-2280"])
def test_normalize_ignores_case_and_separators(variant):
    assert normalize_name(variant) == "ssdxs2280"


def test_normalize_cyrillic_and_yo():
    assert normalize_name("Плата Ёлка 7") == "платаелка7"
    assert normalize_name("плата елка-7") == "платаелка7"


def test_users_add_is_idempotent_by_name_key(db):
    users = UsersService(db)
    first = users.add("Петров", lambda count: "c{}".format(count))
    again = users.add("петров", lambda count: "c{}".format(count))
    second = users.add("Смирнова", lambda count: "c{}".format(count))
    assert again == first
    assert second.color == "c1"
    users.touch(first.id)
    last_login = dict((user.name, value) for user, value in users.all())
    assert last_login["Петров"] and last_login["Смирнова"] is None
    with pytest.raises(ValueError):
        users.add("   ", lambda count: "c")


def test_parts_ensure_reuses_hierarchy_by_normalized_name(parts, part):
    same = parts.ensure("A", "орион 24", "n15", "ssd xs 2280")
    assert same == part  # имя при показе остаётся первым
    assert same.name == "SSD XS-2280" and same.kind == "A" and same.project == "Орион-24" and same.device == "N15"
    assert parts.ensure("B", "Орион-24", "N15", "SSD XS-2280").id != part.id
    assert parts.ensure("A", "Орион-24", "N16", "SSD XS-2280").id != part.id
    assert len(parts.find("ssdxs-2280")) == 3
    assert parts.get(part.id) == part
    assert parts.get(9999) is None
    assert len(parts.all()) == 3


def test_parts_article_is_filled_but_not_overwritten(parts, part):
    assert parts.ensure("A", "Орион-24", "N15", "SSD XS-2280", "512-XS-A").article == "512-XS-A"
    assert parts.ensure("A", "Орион-24", "N15", "SSD XS-2280", "другой").article == "512-XS-A"
    assert parts.ensure("A", "Орион-24", "N15", "SSD XS-2280").article == "512-XS-A"


@pytest.mark.parametrize(
    "args", [("XX", "а", "б", "в"), ("A", "", "б", "в"), ("A", "а", "--", "в"), ("A", "а", "б", " ")]
)
def test_parts_rejects_bad_input(parts, args):
    with pytest.raises(ValueError):
        parts.ensure(*args)


def test_path_key_treats_spellings_of_unc_as_one():
    assert path_key(r"\\Server\Фото\A") == path_key("//server/фото/a/")
    with pytest.raises(ValueError):
        path_key("  ")


def test_folder_add_is_idempotent_and_keeps_unc(folders, part):
    path = r"\\srv\Фото\A\Деталь\2026-10-31"
    folder = folders.add(part.id, path, "2026-10-31")
    assert folder.path == path and folder.status == "new" and folder.created_by is None
    assert folders.add(part.id, path.upper() + "\\", "2026-11-01") == folder
    assert folders.get(folder.id) == folder
    assert folders.get(9999) is None


def test_folder_rejects_bad_date_and_unknown_part(folders, part):
    with pytest.raises(ValueError):
        folders.add(part.id, "x", "31.10.2026")
    with pytest.raises(sqlite3.IntegrityError):
        folders.add(9999, "x", "2026-10-31")


def test_recent_orders_by_date_and_filters_status(db, folders, part):
    user = UsersService(db).add("Петров", lambda count: "c")
    old = folders.add(part.id, "old", "2026-10-01")
    new = folders.add(part.id, "new", "2026-10-31")
    late_added = folders.add(part.id, "late", "2026-09-01")
    assert [f.id for f in folders.recent()] == [new.id, old.id, late_added.id]
    assert [f.id for f in folders.recent(limit=1)] == [new.id]
    folders.set_status(old.id, "done", user.id)
    assert [f.id for f in folders.recent(status="done")] == [old.id]
    changed = folders.get(old.id)
    assert changed.status_by == user.id and changed.status_at
    with pytest.raises(ValueError):
        folders.set_status(old.id, "готово")
    with pytest.raises(LookupError):
        folders.set_status(9999, "done")


@pytest.mark.parametrize("bad", ["../x.jpg", "/x.jpg", "\\x.jpg", "C:\\x.jpg", "a//b.jpg", ""])
def test_rel_path_cannot_leave_folder(bad):
    with pytest.raises(ValueError):
        clean_rel_path(bad)


def test_photos_are_added_once_with_relative_paths(folders, part):
    folder = folders.add(part.id, "f", "2026-10-31")
    assert folders.add_photos(folder.id, ["b.jpg", "Тип 1\\a.jpg"]) == 2
    assert folders.add_photos(folder.id, ["B.JPG", "c.jpg"]) == 1
    assert [p.rel_path for p in folders.photos(folder.id)] == ["b.jpg", "c.jpg", "Тип 1/a.jpg"]


def test_one_bad_path_adds_no_photos(folders, part):
    folder = folders.add(part.id, "f", "2026-10-31")
    with pytest.raises(ValueError):
        folders.add_photos(folder.id, ["ok.jpg", "../bad.jpg"])
    assert folders.photos(folder.id) == []


def test_marks_sn_and_counts(db, folders, part):
    user = UsersService(db).add("Петров", lambda count: "c")
    folder = folders.add(part.id, "f", "2026-10-31")
    empty = folders.add(part.id, "g", "2026-10-31")
    folders.add_photos(folder.id, ["1.jpg", "2.jpg", "3.jpg", "4.jpg"])
    a, b, c, _ = folders.photos(folder.id)
    folders.mark_photo(a.id, "type:2", user_id=user.id)
    folders.mark_photo(b.id, "defect", "SN-1", user.id)
    folders.mark_photo(c.id, "remark")
    assert folders.counts([folder.id, empty.id]) == {
        folder.id: {"total": 4, "unmarked": 1, "type:2": 1, "defect": 1, "remark": 1},
        empty.id: {"total": 0, "unmarked": 0},
    }
    marked = folders.photos(folder.id)[1]
    assert (marked.mark, marked.sn, marked.marked_by) == ("defect", "SN-1", user.id) and marked.marked_at

    folders.mark_photo(b.id, None)  # снять отметку: SN остаётся у фото
    marked = folders.photos(folder.id)[1]
    assert (marked.mark, marked.sn, marked.marked_by, marked.marked_at) == (None, "SN-1", None, None)
    folders.mark_photo(b.id, "defect", "")
    assert folders.photos(folder.id)[1].sn is None


def test_kind_is_kept_for_remark_and_cleared_by_type(folders, part):
    folder = folders.add(part.id, "f", "2026-10-31")
    folders.add_photos(folder.id, ["1.jpg"])
    photo_id = folders.photos(folder.id)[0].id
    folders.mark_photo(photo_id, "defect", "SN-1", defect_kind="Размытое фото")
    assert folders.photos(folder.id)[0].defect_kind == "Размытое фото"
    folders.mark_photo(photo_id, "defect", "SN-2", defect_kind="")  # вид сняли
    assert folders.photos(folder.id)[0].defect_kind is None
    folders.mark_photo(photo_id, "defect", defect_kind="Размытое фото")
    folders.mark_photo(photo_id, "remark", defect_kind="Размытое фото")
    photo = folders.photos(folder.id)[0]
    assert (photo.mark, photo.defect_kind, photo.sn) == ("remark", "Размытое фото", "SN-2")
    folders.mark_photo(photo_id, "type:1")  # у типа вида нет
    assert folders.photos(folder.id)[0].defect_kind is None


def test_move_photos_is_all_or_nothing(folders, part):
    import sqlite3
    folder = folders.add(part.id, "f", "2026-10-31")
    folders.add_photos(folder.id, ["a.jpg", "b.jpg", "Тип 1/b.jpg"])
    a, b, taken = folders.photos(folder.id)
    folders.mark_photo(a.id, "type:1")
    folders.move_photos([(a.id, "Тип 2/a.jpg")])
    moved = [p for p in folders.photos(folder.id) if p.id == a.id][0]
    assert (moved.rel_path, moved.mark) == ("Тип 2/a.jpg", "type:1")  # отметка при переезде сохраняется
    with pytest.raises(sqlite3.IntegrityError):  # имя занято: вторая пара не должна пройти, первая тоже откатывается
        folders.move_photos([(a.id, "Тип 3/a.jpg"), (b.id, "Тип 1/B.JPG")])
    assert sorted(p.rel_path for p in folders.photos(folder.id)) == sorted(["Тип 1/b.jpg", "Тип 2/a.jpg", "b.jpg"])
    with pytest.raises(ValueError):
        folders.move_photos([(a.id, "../x.jpg")])
    with pytest.raises(LookupError):
        folders.move_photos([(9999, "x.jpg")])


@pytest.mark.parametrize("mark", ["тип", "type:", "type:x", "DEFECT"])
def test_unknown_mark_is_rejected(folders, part, mark):
    folder = folders.add(part.id, "f", "2026-10-31")
    folders.add_photos(folder.id, ["1.jpg"])
    with pytest.raises(ValueError):
        folders.mark_photo(folders.photos(folder.id)[0].id, mark)


def test_mark_of_missing_photo_fails(folders):
    with pytest.raises(LookupError):
        folders.mark_photo(9999, "defect")


def test_counts_handles_more_ids_than_sqlite_variables(folders):
    assert len(folders.counts(range(1, 2500))) == 2499


def test_login_migration_moves_existing_users(tmp_path):
    """База шага 0.4–0.5: пользователи в login_users, ядра ещё нет."""
    database = Database(tmp_path / "старая.sqlite")
    old = tmp_path / "old"
    old.mkdir()
    source = open(LOGIN_MIGRATIONS + "/001_init.sql", encoding="utf-8").read()
    (old / "001_init.sql").write_text(source, encoding="utf-8")
    MigrationRunner(database).run("login", old)
    database.write(
        lambda c: c.execute(
            "INSERT INTO login_users (name, name_key, color, created_at, last_login_at) "
            "VALUES ('Петров', 'петров', '#111111', '2026-10-30 10:00:00', '2026-10-31 09:00:00')"
        )
    )

    domain.migrate(database)
    assert MigrationRunner(database).run("login", LOGIN_MIGRATIONS) == [2]

    [(user, last_login)] = UsersService(database).all()
    assert (user.name, user.color, last_login) == ("Петров", "#111111", "2026-10-31 09:00:00")
    tables = database.read(lambda c: {r[0] for r in c.execute("SELECT name FROM sqlite_master")})
    assert "login_users" not in tables


def _folder_with_photo(parts, folders, kind, project, device, part_name, date_text, photos=1):
    part = parts.ensure(kind, project, device, part_name)
    folder = folders.add(part.id, "\\\\сервер\\{}\\{}\\{}".format(project, part_name, date_text), date_text)
    folders.add_photos(folder.id, ["{}.jpg".format(number) for number in range(photos)])
    return folder


def test_latest_for_part_matches_name_loosely_and_takes_newest(parts, folders, part):
    old = _folder_with_photo(parts, folders, "A", "Орион-24", "N15", "SSD XS-2280", "2026-01-05")
    new = _folder_with_photo(parts, folders, "A", "Орион-24", "N16", "ssd_xs 2280", "2026-03-05")  # другое устройство
    assert folders.latest_for_part("SSD XS-2280").id == new.id
    assert folders.latest_for_part("SSDXS2280", exclude_folder_id=new.id).id == old.id
    assert folders.latest_for_part("другая деталь") is None


def test_latest_for_part_own_project_neighbors_kind_and_date(parts, folders):
    own = _folder_with_photo(parts, folders, "A", "Орион-24", "N15", "SSD", "2026-01-05")
    near = _folder_with_photo(parts, folders, "A", "Лира", "L1", "SSD", "2026-02-01")
    other_kind = _folder_with_photo(parts, folders, "B", "Вега", "V1", "SSD", "2026-05-01")
    project = parts.get(folders.get(own.id).part_id).project_id
    assert folders.latest_for_part("SSD", project_id=project).id == own.id
    found = folders.latest_for_part("SSD", kind="A", exclude_project_id=project)
    assert found.id == near.id and found.id != other_kind.id
    assert folders.latest_for_part("SSD", kind="A", exclude_project_id=project, since="2026-02-02") is None
    assert folders.latest_for_part("SSD", kind="B", exclude_project_id=project).id == other_kind.id


def test_latest_for_part_skips_folders_without_photos(parts, folders):
    _folder_with_photo(parts, folders, "A", "Орион-24", "N15", "SSD", "2026-03-05", photos=0)
    kept = _folder_with_photo(parts, folders, "A", "Орион-24", "N15", "SSD", "2026-01-05")
    assert folders.latest_for_part("SSD").id == kept.id
