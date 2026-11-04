"""Карточка правила в сетке вкладки «Правила» (04.11.2026), как карточки «БД».

Обложка — первое фото (заполняет карточку, без полос; клик — все фото правила), заголовок, текст обычным цветом,
автор крупным светящимся тегом — важно видеть, кто добавил. Кнопки: изменить, в архив (печать «В АРХИВЕ»,
как в «БД»), удалить (карточка «сгорает»: краснеет, сжимается и исчезает).
"""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt5.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from atlas.core import theme
from atlas.features.rules import logic
from atlas.shared.widgets import StampAnimation
from atlas.shared.widgets import stamp as stamp_math
from atlas.shared.widgets.icons import set_icon
from atlas.shared.widgets.name_tag import NameTag

COVER_HEIGHT = 220
DESTROY_MS = 650
TEXT_NEW = "НОВОЕ"
TEXT_READ = "Прочитано"
TEXT_ARCHIVED = "В архиве"
TEXT_ARCHIVED_BY = "В архиве · {}"
TIP_LOCKED = "Изменить и удалить можно в течение {} дней после добавления; дальше — только в архив"
TEXT_EDITED = "изменено {}"
TIP_EDIT = "Изменить заголовок, текст и фото"
TIP_ARCHIVE = "В архив: правило остаётся внизу списка, но к детали не показывается"
TIP_RESTORE = "Вернуть из архива"
TIP_DELETE = "Удалить насовсем"
TEXT_MORE = "+{} фото"


def _label(text, role=None, wrap=True):
    label = QLabel(text)
    if role:
        label.setProperty("role", role)
    label.setWordWrap(wrap)
    label.setTextInteractionFlags(Qt.NoTextInteraction)
    return label


def _pill(text, tone):
    pill = QLabel(text)
    pill.setProperty("role", "pill")
    pill.setProperty("tone", tone)
    return pill


def _square(icon_name, tip, color="text_dim"):
    button = QPushButton("")
    button.setProperty("role", "square")
    set_icon(button, icon_name, color)
    button.setToolTip(tip)
    button.setFocusPolicy(Qt.NoFocus)
    return button


class RuleCover(QWidget):
    """Первое фото правила на всю ширину карточки; серость и печать архива; красный налёт при удалении."""

    clicked = pyqtSignal()

    def __init__(self, path, more, parent=None):
        super().__init__(parent)
        self.setObjectName("PhotoView")  # тот же фон и скругление, что у окна просмотра
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(COVER_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        image = QImage(str(path))
        self.image = None if image.isNull() else image
        self._gray = self.image.convertToFormat(QImage.Format_Grayscale8) if self.image is not None else None
        self.more = more
        self.frame = stamp_math.COLOR
        self.burn = 0.0  # 0…1 — удаление

    def show_frame(self, frame):
        self.frame = frame
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        tokens = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        area = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.image is None:
            return
        scale = max(area.width() / self.image.width(), area.height() / self.image.height())
        source_w, source_h = area.width() / scale, area.height() / scale
        source = QRectF((self.image.width() - source_w) / 2, (self.image.height() - source_h) / 2, source_w, source_h)
        painter.drawImage(area, self.image, source)
        if self.frame.gray > 0:
            painter.setOpacity(self.frame.gray)
            painter.drawImage(area, self._gray, source)
            painter.setOpacity(self.frame.gray * stamp_math.DIM)
            painter.fillRect(area, tokens.qcolor("photo_bg"))
            painter.setOpacity(1.0)
        stamp_math.paint_stamp(painter, QRectF(self.rect()), self.frame, tokens.qcolor("defect"))
        if self.burn > 0:
            red = QColor(tokens.qcolor("defect"))
            red.setAlphaF(min(1.0, self.burn * 1.4) * 0.7)
            painter.fillRect(area, red)
        if self.more:
            text = TEXT_MORE.format(self.more)
            metrics = painter.fontMetrics()
            badge = QRectF(area.right() - metrics.horizontalAdvance(text) - 20, area.bottom() - 30,
                           metrics.horizontalAdvance(text) + 12, 22)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            painter.setBrush(tokens.qcolor("bg"))
            painter.drawRoundedRect(badge, 6, 6)
            painter.setPen(tokens.qcolor("text"))
            painter.drawText(badge, Qt.AlignCenter, text)


class RuleTile(QFrame):
    """Правило в сетке. Сама в базу не ходит: только сигналы."""

    read_clicked = pyqtSignal(int)
    photo_clicked = pyqtSignal(object, int)  # все фото правила (относительные пути), номер
    edit_clicked = pyqtSignal(int)
    archive_clicked = pyqtSignal(int, bool)  # правило, True — в архив
    delete_clicked = pyqtSignal(int)
    animation_done = pyqtSignal(int)

    def __init__(self, rule, author, color, root, today=None, parent=None, archiver="", edit_days=logic.EDIT_DAYS):
        super().__init__(parent)
        self.rule = rule
        self.setProperty("role", "type-card")
        self.setProperty("on", False)
        self.setProperty("archived", rule.archived)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.cover = None
        if rule.photos:
            self.cover = RuleCover(Path(root) / logic.thumb_rel(rule.photos[0]), len(rule.photos) - 1)
            self.cover.show_frame(stamp_math.final_frame(rule.archived))
            self.cover.clicked.connect(lambda: self.photo_clicked.emit(tuple(rule.photos), 0))
            outer.addWidget(self.cover)
        body = QVBoxLayout()
        body.setContentsMargins(14, 12, 14, 12)
        body.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(6)
        if not rule.read and not rule.archived:
            head.addWidget(_pill(TEXT_NEW, "type2"))
        head.addWidget(_pill(logic.scope_text(rule), "muted" if rule.scope == logic.SCOPE_GENERAL else "ok"))
        head.addStretch(1)
        self.edit_button = _square("pencil", TIP_EDIT)
        self.edit_button.clicked.connect(lambda _=False: self.edit_clicked.emit(rule.id))
        self.archive_button = _square("archive-restore" if rule.archived else "archive",
                                      TIP_RESTORE if rule.archived else TIP_ARCHIVE, "ok" if rule.archived else "text_dim")
        self.archive_button.clicked.connect(lambda _=False: self.archive_clicked.emit(rule.id, not rule.archived))
        self.delete_button = _square("x", TIP_DELETE)
        self.delete_button.clicked.connect(lambda _=False: self.delete_clicked.emit(rule.id))
        for button in (self.edit_button, self.archive_button, self.delete_button):
            head.addWidget(button)
        self.locked = logic.locked(rule, today, edit_days)
        if self.locked:  # прошло больше edit_days: правило — уже обоснование, только архив
            for button in (self.edit_button, self.delete_button):
                button.setEnabled(False)
                button.setToolTip(TIP_LOCKED.format(edit_days))
        body.addLayout(head)
        body.addWidget(_label(rule.title, "heading"))
        if rule.body:
            body.addWidget(_label(rule.body))  # обычным цветом: это сам текст правила
        foot = QHBoxLayout()
        foot.setSpacing(10)
        self.tag = None
        if author:
            self.tag = NameTag(author, color or "#7DB4FF")
            self.tag.setChecked(True)  # «ореол»: автор правила виден сразу
            self.tag.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.tag.setFocusPolicy(Qt.NoFocus)
            foot.addWidget(self.tag)
        when = logic.short_date(rule.created_at, today)
        if rule.updated_at:
            when += " · " + TEXT_EDITED.format(logic.short_date(rule.updated_at, today))
        foot.addWidget(_label(when, "muted", wrap=False))
        foot.addStretch(1)
        if rule.archived:
            who = ", ".join(part for part in (archiver, logic.short_date(rule.archived_at, today)) if part)
            foot.addWidget(_label(TEXT_ARCHIVED_BY.format(who) if who else TEXT_ARCHIVED, "caption", wrap=False))
        elif not rule.read:
            read = QPushButton(TEXT_READ)
            read.setFocusPolicy(Qt.NoFocus)
            read.clicked.connect(lambda _=False: self.read_clicked.emit(rule.id))
            foot.addWidget(read)
        body.addLayout(foot)
        outer.addLayout(body)
        self._outer = outer
        self._stamp = StampAnimation(self, self._on_frame, lambda: self.animation_done.emit(self.rule.id))
        self._destroy = None
        self._effect = None

    @property
    def animating(self):
        return self._stamp.running or self._destroy is not None

    def set_buttons_enabled(self, enabled):
        self.archive_button.setEnabled(enabled)
        for button in (self.edit_button, self.delete_button):
            button.setEnabled(enabled and not self.locked)

    def play_archive(self, archived):
        """Печать «В АРХИВЕ» (или обратно в цвет), как в «БД». Без фото — сразу конец."""
        self.set_buttons_enabled(False)
        self._stamp.start(restoring=not archived)  # без фото печати не видно, но «удар» есть

    def _on_frame(self, frame):
        if self.cover is not None:
            self.cover.show_frame(frame)
        self._outer.setContentsMargins(0, int(round(frame.thud)), 0, 0)  # «удар» печати: карточка вздрагивает, как в «БД»

    def play_delete(self):
        """«Уничтожение»: фото краснеет, карточка сжимается и тает; в конце — animation_done."""
        self.set_buttons_enabled(False)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        start_height = self.height()
        self._destroy = QVariantAnimation(self)
        self._destroy.setStartValue(0.0)
        self._destroy.setEndValue(1.0)
        self._destroy.setDuration(DESTROY_MS)
        self._destroy.setEasingCurve(QEasingCurve.InCubic)

        def tick(value):
            value = float(value)
            if self.cover is not None:
                self.cover.burn = value
                self.cover.update()
            self._effect.setOpacity(max(0.0, 1.0 - value))
            self.setMaximumHeight(max(1, int(start_height * (1.0 - 0.85 * value))))

        self._destroy.valueChanged.connect(tick)
        self._destroy.finished.connect(lambda: self.animation_done.emit(self.rule.id))
        self._destroy.start()

    def stop_animation(self):
        self._stamp.stop()
        if self._destroy is not None:
            self._destroy.stop()
