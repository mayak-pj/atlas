"""--addfolder: настоящая папка с фото попадает в базу без импорта из письма."""
import json
import shutil
from pathlib import Path

import pytest

from atlas import addfolder
from atlas.app import _run_check_command
from atlas.core import domain
from atlas.core.config import AppPaths
from atlas.core.db import Database
from atlas.shared.fs.photos import photo_paths

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def paths(tmp_path):
    root = tmp_path / "Атлас программа"
    (root / "config").mkdir(parents=True)
    shutil.copy(str(REPO / "config" / "app.json"), str(root / "config" / "app.json"))
    (root / "config" / "features.json").write_text(json.dumps({"features": []}), encoding="utf-8")
    return AppPaths(root)


@pytest.fixture
def photos(tmp_path):
    folder = tmp_path / "Фото 31.10"
    (folder / "sub").mkdir(parents=True)
    for name in ("b_1_S2.jpg", "a_1_S1.JPG", "sub/c_2_S3.jpeg", "notes.txt"):
        (folder / name).write_bytes(b"x")
    return folder


def rows(paths):
    from atlas.core.config import Config

    db = Database(paths.resolve(Config.load(paths).get("database.path")))
    domain.migrate(db)
    from atlas.core.domain.folders import FoldersService

    return FoldersService(db)


def test_photo_paths_are_jpeg_only_sorted_with_slashes(photos):
    assert photo_paths(photos) == ["a_1_S1.JPG", "b_1_S2.jpg", "sub/c_2_S3.jpeg"]


def test_add_folder_registers_part_folder_and_photos(paths, photos):
    row, added, total = addfolder.add_folder(paths, photos, "A", "Орион-24", "N15", "Плата MB-15", "2026-10-31")
    assert (added, total) == (3, 3) and row.folder_date == "2026-10-31" and row.status == "new"
    service = rows(paths)
    assert [photo.rel_path for photo in service.photos(row.id)] == ["a_1_S1.JPG", "b_1_S2.jpg", "sub/c_2_S3.jpeg"]


def test_second_run_adds_nothing_new(paths, photos):
    addfolder.add_folder(paths, photos, "A", "П", "У", "Д", "2026-10-31")
    row, added, total = addfolder.add_folder(paths, photos, "A", "П", "У", "Д", "2026-10-31")
    assert (added, total) == (0, 3)
    assert len(rows(paths).recent()) == 1


@pytest.mark.parametrize("kind, date, text", [("Z", "2026-10-31", "вид проекта"), ("A", "31.10.2026", "time data")])
def test_bad_values_are_rejected(paths, photos, kind, date, text):
    with pytest.raises(ValueError) as error:
        addfolder.add_folder(paths, photos, kind, "П", "У", "Д", date)
    assert text in str(error.value)


def test_empty_or_missing_folder_is_rejected(paths, tmp_path):
    (tmp_path / "пусто").mkdir()
    for folder in (tmp_path / "пусто", tmp_path / "нет такой"):
        with pytest.raises(ValueError):
            addfolder.add_folder(paths, folder, "A", "П", "У", "Д")


def option(args, name):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None


def test_run_writes_report_and_codes(paths, photos):
    args = ["--addfolder", str(photos), "--kind", "A", "--project", "П", "--device", "У", "--part", "Д"]
    assert addfolder.run(paths, args, option) == addfolder.OK
    assert "Готово" in (paths.root / "reports" / "addfolder.txt").read_text(encoding="utf-8")
    assert addfolder.run(paths, ["--addfolder", str(photos)], option) == addfolder.BAD_ARGS
    assert "--kind" in (paths.root / "reports" / "addfolder.txt").read_text(encoding="utf-8")
    args[1] = str(photos / "нет")
    assert addfolder.run(paths, args, option) == addfolder.FAILED
    assert "ОШИБКА" in (paths.root / "reports" / "addfolder.txt").read_text(encoding="utf-8")


def test_command_line_dispatch(monkeypatch, paths, photos):
    monkeypatch.setattr(AppPaths, "discover", staticmethod(lambda: paths))
    args = ["--addfolder", str(photos), "--kind", "A", "--project", "П", "--device", "У", "--part", "Д"]
    assert _run_check_command(args) == 0
