"""Замер скорости: расчёты, полный короткий прогон, отказы, папка с фото только читается."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from atlas.core.process_memory import peak_mb
from atlas.viewbench import BenchError, _find_photos, summarize

REPO = Path(__file__).resolve().parent.parent


def _run(*args):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    return subprocess.run([sys.executable, "-m", "atlas"] + list(args), cwd=str(REPO), env=env, timeout=170,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def _report(folder):
    return (folder / "viewbench_t.txt").read_text(encoding="utf-8-sig")


def test_summarize():
    assert summarize([]) is None
    assert summarize([5]) == (5, 5, 5)
    median, p95, top = summarize(list(range(1, 101)))
    assert median == 50.5 and p95 == 95 and top == 100


def test_peak_memory_is_known():
    assert peak_mb() > 1


def test_find_photos_recursive_sorted_limited(tmp_path):
    for name in ("b.JPG", "a.jpg", "папка/c.jpeg", "x.txt"):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"x")
    assert {p.name for p in _find_photos(tmp_path, 10)} == {"b.JPG", "a.jpg", "c.jpeg"}
    assert len(_find_photos(tmp_path, 2)) == 2
    (tmp_path / "a.jpg").unlink()
    (tmp_path / "b.JPG").unlink()
    with pytest.raises(BenchError):
        _find_photos(tmp_path, 10)


def test_short_run_with_generated_photos(tmp_path):
    result = _run("--viewbench", "--report", str(tmp_path), "--photos", "6", "--flips", "1", "--label", "t")
    assert result.returncode == 0, result.stdout
    text = _report(tmp_path)
    assert "ИТОГ: ЗАМЕР ЗАВЕРШЁН" in text
    for part in ("кэш пуст", "после прогрева", "Прогрев L0", "4 окна, зум 12×", "Пик памяти", "ЦЕЛЬ: чётко за 300"):
        assert part in text, text
    assert "ОШИБКА" not in text
    assert "4 окна, зум 12× (L3,L3,L3,L3)" in text  # зум не сбросился: чёткий уровень правда читался
    assert " 0.0 с, 0 мс" not in text  # прогрев делал работу, а не нашёл готовый кэш


def test_empty_folder_is_reported(tmp_path):
    empty = tmp_path / "Пустая папка"
    empty.mkdir()
    out = tmp_path / "out"
    result = _run("--viewbench", str(empty), "--report", str(out), "--label", "t")
    assert result.returncode == 1
    assert "меньше двух фото" in _report(out)
    assert list(empty.iterdir()) == []


def test_real_folder_stays_unchanged(tmp_path):
    photos = tmp_path / "Фото"
    photos.mkdir()
    code = (
        "from PyQt5.QtGui import QImage, QColor\n"
        "from pathlib import Path\n"
        "import sys\n"
        "for n in range(3):\n"
        "    i = QImage(400, 600, QImage.Format_RGB32); i.fill(QColor('#404040')); i.save(str(Path(sys.argv[1]) / '{}.jpg'.format(n)), 'JPEG')\n"
    )
    subprocess.run([sys.executable, "-c", code, str(photos)], check=True)
    before = {path.name: path.stat().st_mtime_ns for path in photos.iterdir()}
    out = tmp_path / "out"
    result = _run("--viewbench", str(photos), "--report", str(out), "--flips", "1", "--label", "t")
    assert result.returncode == 0, result.stdout
    assert {path.name: path.stat().st_mtime_ns for path in photos.iterdir()} == before
    assert "Фото: 3" in _report(out)


def test_bad_number_is_usage_error():
    assert _run("--viewbench", "--photos", "x").returncode == 2
