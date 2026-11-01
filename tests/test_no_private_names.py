"""Репозиторий публичный: настоящие названия видов проектов (две аббревиатуры) в нём быть не должны.

Шаблон собран из кодов символов (chr), чтобы самих названий не было и в этом файле.
"""
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LETTERS = "{}-{}{}{}".format(chr(0x410), chr(0x44F), chr(0x401), chr(0x451))
NAMES = (chr(0x41A) * 2, chr(0x421) + chr(0x422))
PATTERN = re.compile("(?<![{0}])({1})(?![{0}])".format(LETTERS, "|".join(NAMES)))


def _tracked():
    out = subprocess.check_output(["git", "ls-files", "-z"], cwd=str(REPO)).decode("utf-8")
    return [REPO / name for name in out.split("\0") if name]


def test_no_private_names_in_tracked_files():
    found = []
    for path in _tracked():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # картинки, шрифты
        for number, line in enumerate(text.splitlines(), 1):
            if PATTERN.search(line):
                found.append("{}:{}".format(path.relative_to(REPO), number))
    assert not found, "Настоящие названия видов проектов в репозитории: " + ", ".join(found[:20])


def test_pattern_catches_names_but_not_words():
    assert PATTERN.search("вид " + NAMES[0] + " проект")
    assert PATTERN.search(NAMES[1] + "/x")
    assert not PATTERN.search("слово")
    assert not PATTERN.search("а" + NAMES[0] + "б")  # внутри слова — не название
