"""Список выбора типа «Присвоить ТИП» (12.13): три строки, щелчок, колесо, цифры, сдвиг списка, Enter, Esc, «Снять»."""
from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtTest import QTest

from atlas.shared.widgets.type_picker import ROWS, TypePicker


def _picker(qtbot):
    picker = TypePicker("ТИП", 1, 99, "Снять тип")
    qtbot.addWidget(picker)
    chosen, cleared = [], []
    picker.chosen.connect(chosen.append)
    picker.cleared.connect(lambda: cleared.append(True))
    return picker, chosen, cleared


def _wheel(widget, delta):
    widget.wheelEvent(QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, delta), Qt.NoButton,
                                  Qt.NoModifier, Qt.NoScrollPhase, False))


def test_three_rows_top_to_bottom_and_click_chooses(qtbot):
    picker, chosen, _ = _picker(qtbot)
    picker.open_at(QPoint(300, 300))
    assert ROWS == 3 and [t.text() for t in picker.tiles] == ["1", "2", "3"]
    assert picker.tiles[0].isChecked() and picker.clear_button.isHidden()
    assert [t.property("tone") for t in picker.tiles] == ["ok", "type2", "type3"]
    assert picker.height() < 150  # маленькое окошко, не сетка
    picker.tiles[1].click()
    assert chosen == [2] and not picker.isVisible()


def test_wheel_and_arrows_move_value_and_slide_the_list(qtbot):
    picker, chosen, _ = _picker(qtbot)
    picker.open_at(QPoint(300, 300))
    _wheel(picker, 120)  # от себя на первом номере — меньше 1 не бывает
    assert picker.value == 1
    _wheel(picker, -120)
    _wheel(picker, -60)
    _wheel(picker, -60)  # тачпад: мелкие доли складываются в шаг
    assert picker.value == 3 and [t.text() for t in picker.tiles] == ["1", "2", "3"]
    QTest.keyClick(picker, Qt.Key_Down)  # четвёртый тип — список сдвинулся
    assert picker.value == 4 and [t.text() for t in picker.tiles] == ["2", "3", "4"] and picker.tiles[2].isChecked()
    QTest.keyClick(picker, Qt.Key_Up)
    QTest.keyClick(picker, Qt.Key_Return)
    assert chosen == [3]


def test_digits_are_chosen_after_a_moment_two_digits_make_twelve(qtbot):
    picker, chosen, _ = _picker(qtbot)
    picker.open_at(QPoint(300, 300))
    QTest.keyClick(picker, Qt.Key_1)
    QTest.keyClick(picker, Qt.Key_2)
    assert picker.value == 12 and chosen == []
    assert [t.text() for t in picker.tiles] == ["10", "11", "12"]
    qtbot.waitUntil(lambda: chosen == [12], timeout=3000)
    picker.open_at(QPoint(300, 300), 99)
    assert [t.text() for t in picker.tiles] == ["97", "98", "99"]
    QTest.keyClick(picker, Qt.Key_Down)
    assert picker.value == 99


def test_clear_button_and_escape(qtbot):
    picker, chosen, cleared = _picker(qtbot)
    picker.open_at(QPoint(300, 300), 2, can_clear=True)
    assert picker.value == 2 and not picker.clear_button.isHidden()
    QTest.keyClick(picker, Qt.Key_Escape)
    assert not picker.isVisible() and chosen == [] and cleared == []
    picker.open_at(QPoint(300, 300), 2, can_clear=True)
    picker.clear_button.click()
    assert cleared == [True] and not picker.isVisible()
