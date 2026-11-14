"""Барабан номера «Присвоить ТИП» (14.11.2026): колесо, цифры, Enter, Esc, «Снять»."""
from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtTest import QTest

from atlas.shared.widgets.number_drum import NumberDrum


def _drum(qtbot):
    drum = NumberDrum("ТИП", 1, 99, "Снять тип")
    qtbot.addWidget(drum)
    chosen, cleared = [], []
    drum.chosen.connect(chosen.append)
    drum.cleared.connect(lambda: cleared.append(True))
    return drum, chosen, cleared


def _wheel(widget, delta):
    widget.wheelEvent(QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, delta), Qt.NoButton,
                                  Qt.NoModifier, Qt.NoScrollPhase, False))


def test_wheel_scrolls_from_one_and_enter_chooses(qtbot):
    drum, chosen, _ = _drum(qtbot)
    drum.open_at(QPoint(300, 300))
    assert drum.value == 1 and drum.ok_button.text() == "ТИП 1" and drum.clear_button.isHidden()
    _wheel(drum.wheel, 120)  # от себя на первом номере — меньше 1 не бывает
    assert drum.value == 1
    _wheel(drum.wheel, -240)
    _wheel(drum.wheel, -60)
    _wheel(drum.wheel, -60)  # тачпад: мелкие доли складываются в шаг
    assert drum.value == 4
    QTest.keyClick(drum, Qt.Key_Up)
    QTest.keyClick(drum, Qt.Key_Return)
    assert chosen == [3] and not drum.isVisible()


def test_digit_jumps_and_is_chosen_after_a_moment_two_digits_make_twelve(qtbot):
    drum, chosen, _ = _drum(qtbot)
    drum.open_at(QPoint(300, 300))
    QTest.keyClick(drum, Qt.Key_2)
    assert drum.value == 2 and chosen == []
    qtbot.waitUntil(lambda: chosen == [2], timeout=2000)
    drum.open_at(QPoint(300, 300))
    QTest.keyClick(drum, Qt.Key_1)
    QTest.keyClick(drum, Qt.Key_2)
    qtbot.waitUntil(lambda: chosen == [2, 12], timeout=2000)


def test_click_middle_chooses_esc_closes_and_clear(qtbot):
    drum, chosen, cleared = _drum(qtbot)
    drum.open_at(QPoint(300, 300), value=7, can_clear=True)
    assert drum.value == 7 and not drum.clear_button.isHidden()
    QTest.mouseClick(drum.wheel, Qt.LeftButton, pos=QPoint(drum.wheel.width() // 2, 5))  # верхняя строка — 5
    assert drum.value == 5 and chosen == []
    QTest.mouseClick(drum.wheel, Qt.LeftButton, pos=QPoint(drum.wheel.width() // 2, drum.wheel.height() // 2))
    assert chosen == [5]
    drum.open_at(QPoint(300, 300), value=3, can_clear=True)
    QTest.keyClick(drum, Qt.Key_Escape)
    assert chosen == [5] and not drum.isVisible()
    drum.open_at(QPoint(300, 300), value=3, can_clear=True)
    drum.clear_button.click()
    assert cleared == [True]
    drum.grab()
