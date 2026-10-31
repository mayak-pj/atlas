"""Запуск: python -m atlas. Пока — пустое окно (шаг 0.2)."""
import sys


def main(argv=None):
    from PyQt5.QtWidgets import QApplication, QMainWindow

    app = QApplication.instance() or QApplication(list(argv if argv is not None else sys.argv))
    win = QMainWindow()
    win.setWindowTitle("Atlas")
    win.resize(1200, 800)
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
