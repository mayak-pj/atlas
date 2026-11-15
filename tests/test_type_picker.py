"""Плитки выбора типа «Присвоить ТИП» (12.13): щелчок, колесо, цифры, страницы, Enter, Esc, «Снять»."""
from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtTest import QTest

from atlas.shared.widgets.type_picker import PAGE, TypePicker


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


def test_tiles_show_first_page_and_click_chooses(qtbot):
    picker, chosen, _ = _picker(qtbot)
    picker.open_at(QPoint(300, 300))
    assert [t.text() for t in picker.tiles] == [str(n) for n in range(1, PAGE + 1)]
    assert picker.tiles[0].isChecked() and picker.clear_button.isHidden()
    assert [t.property("tone") for t in picker.tiles[:3]] == ["ok", "type2", "type3"]
    picker.tiles[6].click()
    assert chosen == [7] and not picker.isVisible()


def test_wheel_and_arrows_move_value_and_turn_pages(qtbot):
    picker, chosen, _ = _picker(qtbot)
    picker.open_at(QPoint(300, 300))
    _wheel(picker, 120)  # от себя на первом номере — меньше 1 не бывает
    assert picker.value == 1
    _wheel(picker, -240)
    _wheel(picker, -60)
    _wheel(picker, -60)  # тачпад: мелкие доли складываются в шаг
    assert picker.value == 4
    for _ in range(PAGE):
        QTest.keyClick(picker, Qt.Key_Right)
    assert picker.value == 4 + PAGE and picker.tiles[0].text() == str(PAGE + 1)
    assert picker.range_label.text() == "13–24" and picker.prev_button.isEnabled()
    picker.prev_button.click()
    assert picker.value == 4 and picker.tiles[3].isChecked()
    QTest.keyClick(picker, Qt.Key_Down)
    QTest.keyClick(picker, Qt.Key_Return)
    assert chosen == [8]


def test_digits_are_chosen_after_a_moment_two_digits_make_twelve(qtbot):
    picker, chosen, _ = _picker(qtbot)
    picker.open_at(QPoint(300, 300))
    QTest.keyClick(picker, Qt.Key_1)
    QTest.keyClick(picker, Qt.Key_2)
    assert picker.value == 12 and chosen == []
    qtbot.waitUntil(lambda: chosen == [12], timeout=3000)
    picker.open_at(QPoint(300, 300))
    QTest.keyClick(picker, Qt.Key_9)
    QTest.keyClick(picker, Qt.Key_9)
    qtbot.waitUntil(lambda: chosen == [12, 99], timeout=3000)
    picker.open_at(QPoint(300, 300), 99)
    assert picker.tiles[2].isVisible() and picker.tiles[3].isHidden()  # страница 97–99: плиток меньше
    assert not picker.next_button.isEnabled()


def test_clear_button_and_escape(qtbot):
    picker, chosen, cleared = _picker(qtbot)
    picker.open_at(QPoint(300, 300), 5, can_clear=True)
    assert picker.value == 5 and not picker.clear_button.isHidden()
    QTest.keyClick(picker, Qt.Key_Escape)
    assert not picker.isVisible() and chosen == [] and cleared == []
    picker.open_at(QPoint(300, 300), 5, can_clear=True)
    picker.clear_button.click()
    assert cleared == [True] and not picker.isVisible()
