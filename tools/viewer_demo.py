"""Демо просмотра: 1–4 окна, синхронный зум, стрелки листают одно окно.

    python tools/viewer_demo.py [папка с фото]        без папки создаются тестовые платы
    python tools/viewer_demo.py --shots ПАПКА         снимки без экрана и замеры (offscreen)
"""
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget  # noqa: E402

from atlas.shared.viewer.disk_cache import default_cache_dir  # noqa: E402
from atlas.shared.viewer.image_cache import CacheSettings, ImageCache  # noqa: E402
from atlas.shared.viewer.photo_view import PhotoView  # noqa: E402
from atlas.shared.viewer.sync_group import SyncGroup  # noqa: E402

BUTTON_ZOOM = 1.4  # как в макете
PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png")


class ViewerDemo(QWidget):
    def __init__(self, photos, cache, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Atlas — демо просмотра")
        self.photos = [str(photo) for photo in photos]
        self.cache = cache
        self.group = SyncGroup(cache, self)
        self.views = [PhotoView(cache, self) for _ in range(4)]
        self.indexes = {view: number % len(self.photos) for number, view in enumerate(self.views)}
        self.count = 0
        self._layout_buttons = {}

        bar = QHBoxLayout()
        for count in (1, 2, 3, 4):
            button = self._button("{} фото".format(count), lambda _=False, n=count: self.set_layout(n), checkable=True)
            self._layout_buttons[count] = button
            bar.addWidget(button)
        bar.addWidget(self._button("−", lambda: self.group.zoom_by(1 / BUTTON_ZOOM)))
        self.zoom_label = QLabel("100%")
        bar.addWidget(self.zoom_label)
        bar.addWidget(self._button("+", lambda: self.group.zoom_by(BUTTON_ZOOM)))
        bar.addWidget(self._button("Вписать", self.fit))
        self.sync_button = self._button("Синхронно", self.group.set_enabled, checkable=True)
        self.sync_button.setChecked(True)
        bar.addWidget(self.sync_button)
        bar.addStretch(1)
        bar.addWidget(QLabel("Колесо — зум · перетаскивание — сдвиг · двойной клик — вписать · стрелки — листать последнее окно"))

        self.grid = QGridLayout()
        self.grid.setSpacing(10)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 12)
        root.addLayout(bar)
        root.addLayout(self.grid, 1)
        self.group.changed.connect(lambda zoom, cx, cy: self.zoom_label.setText("{:.0f}%".format(zoom * 100)))
        self.set_layout(1)

    def _button(self, text, action, checkable=False):
        button = QPushButton(text)
        button.setFocusPolicy(Qt.NoFocus)  # стрелки должны листать, а не ходить по кнопкам
        button.setCheckable(checkable)
        button.clicked.connect(action)
        return button

    def fit(self):
        self.group.fit()
        self.zoom_label.setText("100%")

    def set_layout(self, count):
        self.count = count
        for number, button in self._layout_buttons.items():
            button.setChecked(number == count)
        for view in self.views:
            self.group.remove(view)
            self.grid.removeWidget(view)
            view.hide()
            view.clear()
        for number, view in enumerate(self.views[:count]):
            self.grid.addWidget(view, 0, number)  # в ряд: вертикальные фото так крупнее, чем в сетке 2×2
            view.show()
            self.group.add(view, reference=count > 1 and number == 0)
        for view in self.views[:count]:
            self.group.show_photo(view, self.photos[self.indexes[view]])
            self._caption(view)

    def flip(self, step):
        view = self.group.active_current()
        self.indexes[view] = (self.indexes[view] + step) % len(self.photos)
        self.group.show_photo(view, self.photos[self.indexes[view]])
        self._caption(view)

    def _caption(self, view):
        name = Path(self.photos[self.indexes[view]]).name
        if view is self.group.reference:
            view.set_caption("ЭТАЛОН", name, reference=True)
        else:
            view.set_caption("ТЕКУЩЕЕ", name)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Right:
            self.flip(1)
        elif event.key() == Qt.Key_Left:
            self.flip(-1)
        else:
            super().keyPressEvent(event)


def make_samples(folder, count=8):
    from samples.photos import save_photo

    variants = ("ssd", "board", "power", "flex")
    photos = []
    for number in range(count):
        path = folder / "плата {}.jpg".format(number + 1)
        save_photo(path, variants[number % 2], 1 + number % 2, "SN S4K2-{:04d}".format(number), number)
        photos.append(path)
    return photos


def _wait(app, condition, limit=20.0):
    from PyQt5.QtTest import QTest

    started = time.perf_counter()
    while not condition() and time.perf_counter() - started < limit:
        QTest.qWait(5)
    return time.perf_counter() - started


def shoot(demo, app, out):
    """Снимки всех раскладок и время до чёткой картинки во всех окнах."""
    from PyQt5.QtTest import QTest

    for count in (1, 2, 3, 4):
        demo.set_layout(count)
        views = demo.group.views
        print("{} окна: первая картинка {:.3f} с".format(count, _wait(app, lambda: all(v.is_current_shown for v in views))))
        QTest.qWait(250)
        demo.grab().save(str(out / "layout_{}_fit.png".format(count)))
        views[-1].set_state(1.0, 0.5, 0.5)
        views[-1].zoom_by(6)
        waited = _wait(app, lambda: all(v.is_sharp for v in views))
        print("  зум 6×: чётко через {:.3f} с, уровни {}".format(waited, [v.shown_level for v in views]))
        started = time.perf_counter()
        for _ in range(10):
            demo.grab()
        print("  отрисовка всего окна {:.1f} мс".format((time.perf_counter() - started) * 100))
        demo.grab().save(str(out / "layout_{}_zoom.png".format(count)))
        demo.fit()


def main(argv):
    from PyQt5.QtWidgets import QApplication

    from atlas.core.qt_runtime import prepare

    shots = Path(argv[argv.index("--shots") + 1]) if "--shots" in argv else None
    if shots is not None:
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    prepare()
    app = QApplication(argv[:1])
    from atlas.core.theme import apply_theme

    apply_theme(app)
    folder = next((Path(item) for item in argv[1:] if not item.startswith("--") and shots is None), None)
    if folder is not None:
        photos = sorted(p for p in folder.iterdir() if p.suffix.lower() in PHOTO_SUFFIXES)
    else:
        photos = make_samples(Path(tempfile.gettempdir()) / "atlas_demo_photos")
    if not photos:
        print("В папке нет фото")
        return 2
    cache = ImageCache(CacheSettings(disk_dir=default_cache_dir()))
    app.aboutToQuit.connect(cache.stop)
    demo = ViewerDemo(photos, cache)
    demo.resize(1280, 760)
    demo.show()
    if shots is not None:
        shots.mkdir(parents=True, exist_ok=True)
        shoot(demo, app, shots)
        cache.stop()
        return 0
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
