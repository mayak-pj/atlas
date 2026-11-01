"""Печать «В АРХИВЕ»: кадры анимации (без Qt, считаются от времени) и рисование поверх картинки.

Как в макете: фото за 0,9 с становится чёрно-белым и темнее; с 0,45 с печать «падает» (масштаб 2,6 → 0,9 → 1, поворот
−24° → −12° → −14°, появление), потом карточка делает короткий «удар» вниз. Возврат из архива — обратно в цвет за 0,9 с.
"""
from __future__ import annotations

from dataclasses import dataclass

GRAY_MS = 900
STAMP_START_MS = 450
STAMP_MS = 550
THUD_START_MS = 1000
THUD_MS = 250
THUD_PX = 3.0
ARCHIVE_TOTAL_MS = THUD_START_MS + THUD_MS
RESTORE_TOTAL_MS = GRAY_MS
FINAL_OPACITY = 0.95
FINAL_ROTATION = -14.0
DIM = 0.25  # насколько темнеет фото в архиве (макет: brightness .75)
_STAMP_KEYS = (  # доля пути, прозрачность, масштаб, поворот
    (0.0, 0.0, 2.6, -24.0),
    (0.7, 1.0, 0.9, -12.0),
    (1.0, FINAL_OPACITY, 1.0, FINAL_ROTATION),
)
_THUD_KEYS = ((0.0, 0.0), (0.4, THUD_PX), (1.0, 0.0))


@dataclass(frozen=True)
class Frame:
    gray: float  # 0 — цвет, 1 — чёрно-белое и тёмное
    stamp_opacity: float  # 0 — печати нет
    stamp_scale: float
    stamp_rotation: float  # градусы
    thud: float  # сдвиг карточки вниз, пиксели

    @property
    def has_stamp(self):
        return self.stamp_opacity > 0.0


COLOR = Frame(0.0, 0.0, 1.0, FINAL_ROTATION, 0.0)
ARCHIVED = Frame(1.0, FINAL_OPACITY, 1.0, FINAL_ROTATION, 0.0)


def _clamp(value):
    return min(1.0, max(0.0, value))


def _along(keys, progress):
    """Линейно между ключевыми кадрами: keys — кортежи (доля, значение…)."""
    progress = _clamp(progress)
    for before, after in zip(keys, keys[1:]):
        if progress <= after[0]:
            span = after[0] - before[0]
            k = (progress - before[0]) / span if span else 1.0
            return tuple(a + (b - a) * k for a, b in zip(before[1:], after[1:]))
    return tuple(keys[-1][1:])


def total_ms(restoring):
    return RESTORE_TOTAL_MS if restoring else ARCHIVE_TOTAL_MS


def frame_at(ms, restoring=False):
    """Кадр через ms миллисекунд от нажатия «В архив» (или «Вернуть из архива»); после конца — итоговый."""
    if restoring:
        gray = 1.0 - _clamp(ms / GRAY_MS)
        opacity = FINAL_OPACITY * (1.0 - _clamp(ms / (GRAY_MS / 3.0)))  # печать тает быстрее, чем возвращается цвет
        return Frame(gray, opacity, 1.0, FINAL_ROTATION, 0.0)
    opacity, scale, rotation = _along(_STAMP_KEYS, (ms - STAMP_START_MS) / STAMP_MS)
    (thud,) = _along(_THUD_KEYS, (ms - THUD_START_MS) / THUD_MS)
    return Frame(_clamp(ms / GRAY_MS), opacity, scale, rotation, thud)


def final_frame(archived):
    return ARCHIVED if archived else COLOR


def paint_stamp(painter, rect, frame, color, text="В АРХИВЕ"):
    """Печать по центру rect. Размер — от высоты rect (в макете 164×52 на карточке высотой 150)."""
    from PyQt5.QtCore import QRectF, Qt
    from PyQt5.QtGui import QFont, QPen

    if not frame.has_stamp:
        return
    unit = rect.height() / 150.0
    width, height = 164.0 * unit, 52.0 * unit
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    painter.setOpacity(frame.stamp_opacity)
    painter.translate(rect.center())
    painter.rotate(frame.stamp_rotation)
    painter.scale(frame.stamp_scale, frame.stamp_scale)
    box = QRectF(-width / 2, -height / 2, width, height)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(color, 1.6 * unit))
    painter.drawRoundedRect(box, 8 * unit, 8 * unit)  # «двойная» рамка: две тонкие линии
    painter.drawRoundedRect(box.adjusted(4 * unit, 4 * unit, -4 * unit, -4 * unit), 5 * unit, 5 * unit)
    font = QFont()
    font.setBold(True)
    font.setPixelSize(max(1, round(20 * unit)))
    font.setLetterSpacing(QFont.AbsoluteSpacing, 2.4 * unit)
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(box, Qt.AlignCenter, text)
    painter.restore()


class StampAnimation:
    """Запуск анимации на QVariantAnimation. Кадры отдаёт в `on_frame(Frame)`, в конце зовёт `on_finished()`.

    Класс, а не QObject: нужен один раз на карточку и без собственных сигналов.
    """

    def __init__(self, parent, on_frame, on_finished):
        from PyQt5.QtCore import QEasingCurve, QVariantAnimation

        self._on_frame = on_frame
        self._on_finished = on_finished
        self._restoring = False
        self._animation = QVariantAnimation(parent)
        self._animation.setEasingCurve(QEasingCurve.Linear)
        self._animation.valueChanged.connect(self._tick)
        self._animation.finished.connect(self._done)

    @property
    def running(self):
        from PyQt5.QtCore import QAbstractAnimation

        return self._animation.state() == QAbstractAnimation.Running

    def start(self, restoring):
        self._restoring = restoring
        self._animation.stop()
        self._animation.setStartValue(0)
        self._animation.setEndValue(total_ms(restoring))
        self._animation.setDuration(total_ms(restoring))
        self._animation.start()

    def stop(self):
        self._animation.stop()

    def _tick(self, value):
        self._on_frame(frame_at(float(value), self._restoring))

    def _done(self):
        self._on_frame(final_frame(not self._restoring))
        self._on_finished()
