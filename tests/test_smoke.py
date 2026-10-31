from PyQt5.QtWidgets import QMainWindow


def test_empty_window_opens(qtbot):
    win = QMainWindow()
    win.setWindowTitle("Atlas")
    qtbot.addWidget(win)
    win.show()
    assert win.isVisible()


def test_package_imports():
    import atlas
    assert atlas.__version__
