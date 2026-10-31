import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from atlas.core.qt_runtime import prepare  # noqa: E402

# До первого окна: иначе тесты падают при запуске из папки с кириллицей
prepare()
