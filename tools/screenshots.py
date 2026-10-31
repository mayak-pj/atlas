"""Снимки окон для проверки вида: python tools/screenshots.py [папка]. Работает без экрана (offscreen)."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp())
    out.mkdir(parents=True, exist_ok=True)
    from atlas.core.qt_runtime import prepare

    prepare()
    from PyQt5.QtWidgets import QApplication

    app = QApplication([])
    from atlas.core.theme import apply_theme

    apply_theme(app)
    from atlas.app import build_core, build_window, start_features
    from atlas.core.config import AppPaths
    from atlas.features.login.dialog import LoginDialog

    import shutil

    work = Path(tempfile.mkdtemp()) / "Атлас снимки"
    for sub in ("config", "data"):
        shutil.copytree(str(ROOT / sub), str(work / sub))
    ctx = build_core(AppPaths(work))
    registry = start_features(ctx)
    login = ctx.services.get("login")
    for name in ("Смирнова", "Петров", "Иванова", "Кузнецова", "Соколов", "Морозова"):
        user = login.repo.add(name, login._colors())
    window = build_window(registry)
    login.sign_in(user)
    window.set_context(kind="КК", project="Орион-24", device="SSD XS-2280", part="Плата", path="\\\\srv\\photo\\2026-10-31")
    window.resize(1280, 720)
    window.show()
    window.grab().save(str(out / "shell.png"))
    dialog = LoginDialog(login.repo, login._colors(), ctx.shell)
    dialog.attach_slots()
    dialog.resize(1080, 560)
    dialog.show()
    dialog.grab().save(str(out / "login.png"))
    print(out)
    registry.stop_all()


if __name__ == "__main__":
    main()
