"""Один процесс из tests/test_domain_concurrent.py: python concurrent_writer.py БАЗА ПАПКА_СИГНАЛОВ НОМЕР РАУНДОВ."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atlas.core import domain  # noqa: E402
from atlas.core.db import Database  # noqa: E402
from atlas.core.domain.folders import FoldersService  # noqa: E402
from atlas.core.domain.parts import PartsService  # noqa: E402
from atlas.core.domain.users import UsersService  # noqa: E402


def main(db_path, signals, number, rounds):
    (signals / "ready{}".format(number)).touch()
    while not (signals / "go").exists():
        time.sleep(0.005)
    db = Database(db_path)
    domain.migrate(db)  # все процессы стартуют на пустой базе одновременно
    users, parts, folders = UsersService(db), PartsService(db), FoldersService(db)
    user = users.add("Проверка {}".format(number), lambda count: "#000000")
    users.add("Общий", lambda count: "#111111")
    for index in range(rounds):
        part = parts.ensure("КК", "Орион-24", "N15", "SSD XS-{}".format(index % 3))
        folder = folders.add(part.id, r"\\srv\фото\p{}\r{}".format(number, index), "2026-10-31", user.id)
        shared = folders.add(part.id, r"\\srv\фото\общая", "2026-10-31", user.id)
        names = ["{}_{}_{}.jpg".format(number, index, i) for i in range(5)]
        assert folders.add_photos(folder.id, names) == 5
        folders.add_photos(shared.id, names)
        photo = folders.photos(folder.id)[0]
        folders.mark_photo(photo.id, "defect", "SN{}".format(number), user.id)
        folders.set_status(folder.id, "done", user.id)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
