"""--publish: положить эту версию в папку установки на сетевом диске.

    atlas.exe --publish "R:\\Atlas"

Python на целевой машине нет, поэтому публикует сам exe из распакованной сборки. Порядок защищает работающих людей:
копия во временную папку → сверка файлов → переименование → и только потом version.txt. Сбой на любом шаге
оставляет действующую версию как есть. Итог — reports/publish.txt (у оконного exe нет консоли).
"""
from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

from atlas.core.release import (
    EXE_NAME, RELEASE_DIR, current_version, parse_version, read_active_version, write_active_version,
)

log = logging.getLogger("atlas.publish")

OK, BAD_ARGS, FAILED = 0, 2, 3

INSTALL_FILES = "install"  # подпапка сборки: что положить рядом с release
SKIP_TOP = {"logs", "var", "reports", "__pycache__"}  # следы запусков этой копии


class PublishError(Exception):
    """Текст показывается человеку."""


def _program_files(source):
    """Относительные пути файлов сборки. config/local.json — настройки чужой машины, в версию не идёт."""
    result = []
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source)
        if path.is_file() and rel.parts[0] not in SKIP_TOP and rel != Path("config", "local.json"):
            result.append(rel)
    return result


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_verified(source, target, files):
    for rel in files:
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(source / rel), str(destination))
    for rel in files:  # отдельным проходом: читаем уже то, что дошло до сетевого диска
        if _digest(source / rel) != _digest(target / rel):
            raise PublishError("Файл скопирован с ошибкой: {}".format(rel))


def _install_helpers(source, home):
    """Atlas.bat и ярлык. Сначала во временный файл: кто-то может запускать Atlas.bat прямо сейчас."""
    folder = source / INSTALL_FILES
    if not folder.is_dir():
        return
    for item in sorted(folder.iterdir()):
        part = home / (item.name + ".part")
        shutil.copyfile(str(item), str(part))
        part.replace(home / item.name)


def publish(source, home, version=None):
    """→ (версия, была ли папка версии уже на диске). Ошибка — PublishError или OSError, действующая версия не меняется."""
    source, home, version = Path(source), Path(home), version or current_version()
    if not (source / EXE_NAME).is_file():
        raise PublishError("Рядом нет {}: публиковать можно только собранную программу.".format(EXE_NAME))
    if not home.is_dir():  # опечатка в пути не должна создавать новую установку
        raise PublishError("Нет папки установки: {}. Создайте её и повторите.".format(home))
    release = home / RELEASE_DIR
    active = read_active_version(release)
    if active and parse_version(active) > parse_version(version):
        raise PublishError(
            "Действует более новая версия {}, а публикуется {}. Для отката укажите нужную версию в {}.".format(
                active, version, release / "version.txt"))
    target = release / version
    existed = target.is_dir()
    if not existed:
        part = release / (version + ".part")
        if part.exists():
            shutil.rmtree(str(part))  # остаток прошлой неудачной публикации
        release.mkdir(parents=True, exist_ok=True)
        try:
            _copy_verified(source, part, _program_files(source))
            part.rename(target)
        except Exception:
            shutil.rmtree(str(part), ignore_errors=True)
            raise
    _install_helpers(source, home)
    write_active_version(release, version)  # последним: с этого момента версию видят все
    return version, existed


def _write_report(paths, text):
    report = paths.root / "reports" / "publish.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_bytes(text.replace("\n", "\r\n").encode("utf-8-sig"))  # для Блокнота Win7


def run(paths, home):
    """Код выхода."""
    if not home or home.startswith("--"):
        _write_report(paths, "Не указана папка установки: atlas.exe --publish \"R:\\Atlas\"\n")
        return BAD_ARGS
    try:
        version, existed = publish(paths.root, home)
    except (PublishError, OSError) as exc:
        log.exception("Не удалось опубликовать")
        _write_report(paths, "ОШИБКА: {}\nДействующая версия не изменилась.\n".format(exc))
        return FAILED
    notes = ["Готово: действует версия {}.".format(version)]
    if existed:
        notes.append("Папка этой версии уже была на диске, файлы не копировались.")
    notes.append("Первый раз: запустите {} на каждом ПК, чтобы создать ярлык.".format(Path(home) / "create_shortcut.vbs"))
    if not (Path(home) / "config" / "local.json").is_file():
        notes.append("Нет config\\local.json: база будет создана в {}\\var. Если база уже есть, укажите её там.".format(home))
    _write_report(paths, "\n".join(notes) + "\n")
    return OK
