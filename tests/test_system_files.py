"""«._имя.jpeg» — служебные «двойники» macOS (AppleDouble): это не фото, их нельзя ни добавлять, ни показывать."""
import pytest

from atlas.core import domain
from atlas.core.db import Database
from atlas.core.domain.folders import FoldersService, is_system_file
from atlas.core.domain.parts import PartsService
from atlas.shared.fs.photos import photo_paths


@pytest.mark.parametrize("rel,expected", [
    ("._0211070002482_1_AY92063_2.Jpeg", True),
    ("подпапка/._фото.jpg", True),
    ("__MACOSX/подпапка/фото.jpg", True),
    ("0211070002482_1_AY92063_2.Jpeg", False),
    ("подпапка/фото._1.jpg", False),
])
def test_is_system_file(rel, expected):
    assert is_system_file(rel) is expected


def test_scan_skips_macos_sidecars(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "._a.jpg").write_bytes(b"x")  # двойник
    (tmp_path / "Б.Jpeg").write_bytes(b"x")
    (tmp_path / "._Б.Jpeg").write_bytes(b"x")
    (tmp_path / "__MACOSX").mkdir()
    (tmp_path / "__MACOSX" / "в.jpg").write_bytes(b"x")
    assert photo_paths(tmp_path) == ["a.jpg", "Б.Jpeg"]


def test_old_folder_with_sidecars_shows_only_photos(tmp_path):
    db = Database(tmp_path / "база.sqlite")
    domain.migrate(db)
    part = PartsService(db).ensure("A", "Орион-24", "N15", "SSD")
    folders = FoldersService(db)
    row = folders.add(part.id, str(tmp_path), "2026-11-14")
    # папка добавлена до исправления: «._» уже лежат в базе
    db.write(lambda conn: conn.executemany(
        "INSERT INTO photos (id, folder_id, rel_path, rel_key) VALUES (?, ?, ?, ?)",
        [(1, row.id, "1.jpg", "1.jpg"), (2, row.id, "._1.jpg", "._1.jpg")]))
    assert [p.rel_path for p in folders.photos(row.id)] == ["1.jpg"]
    assert folders.add_photos(row.id, ["2.jpg", "._2.jpg"]) == 1
