"""--photoinfo (14.11.2026): метка поворота EXIF, размер, поворот в Atlas — отчёт вместо самих фото."""
import struct

from PyQt5.QtGui import QColor, QImage

from atlas.core.config import AppPaths
from atlas import photoinfo


def _jpeg(path, width, height, orientation=None, big_endian=False):
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor("gray"))
    assert image.save(str(path), "JPEG")
    data = path.read_bytes()
    if orientation is not None:
        order = ">" if big_endian else "<"
        tiff = (b"MM" if big_endian else b"II") + struct.pack(order + "HI", 42, 8)
        tiff += struct.pack(order + "H", 2)
        tiff += struct.pack(order + "HHIHH", 0x010F, 2, 4, 0, 0)  # другой тег раньше нужного
        tiff += struct.pack(order + "HHIHH", 0x0112, 3, 1, orientation, 0)
        tiff += struct.pack(order + "I", 0)
        body = b"Exif\x00\x00" + tiff
        data = data[:2] + b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body + data[2:]
    path.write_bytes(data)
    return path


def test_jpeg_info_reads_size_and_exif_orientation(tmp_path, qapp):
    assert photoinfo.jpeg_info(_jpeg(tmp_path / "a.jpg", 60, 40)) == (60, 40, None)
    assert photoinfo.jpeg_info(_jpeg(tmp_path / "b.jpg", 60, 40, 6)) == (60, 40, 6)
    assert photoinfo.jpeg_info(_jpeg(tmp_path / "c.jpg", 60, 40, 8, big_endian=True)) == (60, 40, 8)
    (tmp_path / "d.jpg").write_bytes(b"not a jpeg")
    try:
        photoinfo.jpeg_info(tmp_path / "d.jpg")
    except ValueError:
        pass
    else:
        raise AssertionError("не JPEG должен давать ValueError")


def test_describe_counts_orientations_and_atlas_rotation(tmp_path, qapp):
    folder = tmp_path / "Папка"
    folder.mkdir()
    _jpeg(folder / "1.jpg", 60, 40, 6)  # на экране вертикальное
    _jpeg(folder / "2.jpg", 60, 40)  # горизонтальное
    _jpeg(folder / "3.jpg", 60, 40, 1)
    (folder / "4.jpg").write_bytes(b"\xff\xd8\xff")
    text = "\n".join(photoinfo.describe(folder, {"3.jpg": 90}))
    assert "1.jpg | 60×40 | 6 (90° по часовой) | 40×60 | — | вертикальное" in text
    assert "2.jpg | 60×40 | нет | 60×40 | — | горизонтальное" in text
    assert "3.jpg | 60×40 | 1 (как есть) | 60×40 | 90° | вертикальное" in text
    assert "4.jpg | не прочитан" in text
    assert "итог: вертикальное: 2" in text and "повёрнуто в Atlas: 1" in text


def test_run_writes_report_and_reads_rotation_from_atlas(tmp_path, qapp):
    import json
    import shutil
    from pathlib import Path
    from atlas.app import build_core

    root = tmp_path / "Атлас"
    (root / "config").mkdir(parents=True)
    repo = Path(__file__).resolve().parent.parent
    shutil.copy(str(repo / "config" / "app.json"), str(root / "config" / "app.json"))
    (root / "config" / "features.json").write_text(json.dumps({"features": []}), encoding="utf-8")
    paths = AppPaths(root)
    ctx = build_core(paths)
    folder = tmp_path / "Фото"
    folder.mkdir()
    _jpeg(folder / "1.jpg", 60, 40)
    part = ctx.services.get("parts").ensure("A", "Орион", "N15", "Плата")
    folders = ctx.services.get("folders")
    row = folders.add(part.id, str(folder), "2026-11-14")
    folders.add_photos(row.id, ["1.jpg"])
    folders.set_rotation([folders.photos(row.id)[0].id], 270)
    assert photoinfo.run(paths, str(folder)) == photoinfo.OK
    text = (root / "reports" / "photoinfo.txt").read_text(encoding="utf-8-sig")
    assert "1.jpg | 60×40 | нет | 60×40 | 270° | вертикальное" in text
    assert photoinfo.run(paths, str(tmp_path / "нет такой")) == photoinfo.BAD_ARGS
