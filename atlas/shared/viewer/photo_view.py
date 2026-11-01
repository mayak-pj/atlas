"""PhotoView: одно окно просмотра. Колесо — зум к курсору, перетаскивание — сдвиг, двойной клик — вписать.

Обычный QWidget, а не QGraphicsView: нужна одна картинка без сцены, рисуем только видимую часть.
Любой уровень растягивается на один и тот же прямоугольник из ViewState, поэтому подмена уровня не сдвигает картинку.
"""
from __future__ import annotations

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPainter, QPainterPath
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QStyle, QStyleOption, QWidget

from atlas.shared.viewer.levels import CURRENT, L0, L1, level_divisor, level_for_scale
from atlas.shared.viewer.view_state import ViewState

SETTLE_MS = 150  # после остановки листания или зума — чёткий уровень (цель: не позже 300 мс)
WHEEL_STEP = 1.2  # за один щелчок колеса, как в макете
_WHEEL_NOTCH = 120.0
_INNER_RADIUS = 7  # скругление QWidget#PhotoView минус рамка
_CAPTION_MARGIN = 10
_SMOOTH_FROM = 2.0  # во сколько раз картинка больше экрана
TEXT_LOADING = "Загрузка…"
TEXT_FAILED = "Не удалось открыть фото"


def _improves(level, shown, wanted):
    """Лучше ли level, чем показанный: стремимся к wanted, не показываем зря больший уровень."""
    if shown < wanted:
        return level > shown
    return wanted <= level < shown


class _Caption(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("PhotoViewCaption")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._tag = QLabel()
        self._tag.setObjectName("PhotoViewTag")
        self._text = QLabel()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(6)
        layout.addWidget(self._tag)
        layout.addWidget(self._text)
        self.move(_CAPTION_MARGIN, _CAPTION_MARGIN)
        self.hide()

    def set_content(self, tag, text, reference):
        self._tag.setText(tag)
        self._tag.setProperty("reference", bool(reference))
        self._tag.style().unpolish(self._tag)
        self._tag.style().polish(self._tag)
        self._text.setText(text)
        self._text.setVisible(bool(text))
        self.adjustSize()
        self.setVisible(bool(tag))


class PhotoView(QWidget):
    view_changed = pyqtSignal(float, float, float)  # зум, центр x, y — только от действий пользователя
    photo_shown = pyqtSignal(str)  # на экране появилась картинка именно этого фото
    photo_failed = pyqtSignal(str, str)  # путь, текст ошибки

    def __init__(self, cache, parent=None, settle_ms=SETTLE_MS):
        super().__init__(parent)
        self.setObjectName("PhotoView")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.OpenHandCursor)
        self._cache = cache
        self._state = ViewState()
        self._path = None
        self._image = None
        self._image_path = None  # пока новое фото не пришло, на экране остаётся прежнее
        self._level = L0
        self._wanted = L1
        self._full_size = None  # (ширина, высота) исходника; по L0 не вычислить
        self._drag_from = None
        self._failed = False
        self._smoothed = None
        self._smoothed_key = None
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(settle_ms)
        self._settle.timeout.connect(self._on_settled)
        self._message = QLabel(self)
        self._message.setObjectName("PhotoViewMessage")
        self._message.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._message.hide()
        layout = QHBoxLayout(self)
        layout.addWidget(self._message, 0, Qt.AlignCenter)
        self._caption = _Caption(self)
        cache.ready.connect(self._on_ready)
        cache.failed.connect(self._on_failed)

    @property
    def path(self):
        return self._path

    @property
    def shown_level(self):
        """Уровень на экране; None — картинки текущего фото ещё нет."""
        return self._level if self.is_current_shown else None

    @property
    def shown_image_size(self):
        """(ширина, высота) картинки текущего фото с учётом EXIF, уровень любой; годится для ориентации. Иначе None."""
        return (self._image.width(), self._image.height()) if self.is_current_shown else None

    @property
    def is_current_shown(self):
        """False, пока на экране прежнее фото: отмечать сейчас нельзя, это проверит экран сравнения."""
        return self._image is not None and self._image_path == self._path

    @property
    def is_sharp(self):
        """На экране текущее фото нужного масштабу уровня."""
        return self.is_current_shown and self._level == self._needed_level()

    def state(self):
        return self._state.state()

    def set_state(self, zoom, cx, cy):
        """Применить состояние извне (синхронизация). view_changed не посылает."""
        self._state.set_state(zoom, cx, cy)
        self._after_view_change()

    def set_photo(self, path):
        """Зум и место сохраняются. Сразу — что есть в памяти или L1, через SETTLE_MS — чёткий уровень."""
        path = str(path)
        if path == self._path:
            return
        self._path = path
        self._failed = False
        self._full_size = None
        self._wanted = L1
        self._show_message("")
        hit = self._cache.get(path, L1, CURRENT)
        if hit is not None:
            self._adopt(hit.image, hit.level)
        self._settle.start()

    def clear(self):
        self._path = None
        self._image = None
        self._image_path = None
        self._full_size = None
        self._failed = False
        self._settle.stop()
        self._show_message("")
        self.update()

    def show_missing(self, text):
        """Фото нет и не будет (например, у SN нет этого ракурса): пустое окно с подписью. Зум и место сохраняются."""
        self.clear()
        self._show_message(text)

    def request_again(self):
        """Очередь кэша отменена: повторить запросы этого окна, иначе «Загрузка…» осталась бы навсегда."""
        if self._path is None or self._failed:
            return
        if not self.is_current_shown:
            hit = self._cache.get(self._path, L1, CURRENT)
            if hit is not None:
                self._adopt(hit.image, hit.level)
        self._settle.start()

    def set_caption(self, tag, text="", reference=False):
        """Подпись в углу окна, как в макете: пилюля (ЭТАЛОН, ТЕКУЩЕЕ) и текст. Пустой tag — без подписи."""
        self._caption.set_content(tag, text, reference)

    def fit(self):
        self._user_change(self._state.fit)

    def zoom_by(self, factor):
        """Кнопки −/+: зум к центру окна."""
        self._user_change(self._state.zoom_at, factor, self._state.view_w / 2, self._state.view_h / 2)

    def _user_change(self, action, *args):
        before = self._state.state()
        action(*args)
        if self._state.state() != before:
            self._after_view_change()
            self.view_changed.emit(*self._state.state())

    def _after_view_change(self):
        self.update()
        if self._path is not None:
            self._settle.start()

    def _needed_level(self):
        if self._full_size is None:
            return L1
        width, height = self._state.displayed_size()
        ratio = self.devicePixelRatioF()
        return level_for_scale(max(width * ratio / self._full_size[0], height * ratio / self._full_size[1]))

    def _on_settled(self):
        if self._path is None or self._failed:
            return
        if not self.is_current_shown:
            self._show_message(TEXT_LOADING)
            return  # уровень выберем, когда придёт первая картинка: до неё неизвестен размер
        self._wanted = self._needed_level()
        if self._level != self._wanted:
            hit = self._cache.get(self._path, self._wanted, CURRENT, exact=True)
            if hit is not None and _improves(hit.level, self._level, self._wanted):
                self._adopt(hit.image, hit.level)

    def _adopt(self, image, level):
        first = not self.is_current_shown
        keep_proportions = not first and self._level != L0  # L0 округлён сильно, L1 и выше точны
        self._image = image
        self._image_path = self._path
        self._level = level
        if level != L0:
            divisor = level_divisor(level)
            self._full_size = (image.width() * divisor, image.height() * divisor)
        if not keep_proportions:
            self._state.set_photo_size(image.width(), image.height())
        self._show_message("")
        self.update()
        if first:
            self.photo_shown.emit(self._path)

    def _on_ready(self, path, level, image):
        if path != self._path:
            return
        if not self.is_current_shown or _improves(level, self._level, self._wanted):
            self._adopt(image, level)
            if not self._settle.isActive():
                self._on_settled()  # первая картинка пришла позже таймера

    def _on_failed(self, path, level, text):
        if path != self._path or self.is_current_shown:
            return  # чёткий уровень не прочитался, а L1 на экране есть: продолжаем работать с ним
        self._failed = True
        self._image = None
        self._image_path = None
        self._settle.stop()
        self._show_message(TEXT_FAILED)
        self.update()
        self.photo_failed.emit(path, text)

    def _show_message(self, text):
        self._message.setText(text)
        self._message.setVisible(bool(text))

    def resizeEvent(self, event):
        self._state.set_view_size(self.width(), self.height())
        self._after_view_change()
        super().resizeEvent(event)

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / _WHEEL_NOTCH
        if self._image is None or not steps:
            event.ignore()
            return
        self._user_change(self._state.zoom_at, WHEEL_STEP ** steps, event.pos().x(), event.pos().y())
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_from = event.pos()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._drag_from is None:
            return
        delta = event.pos() - self._drag_from
        self._drag_from = event.pos()
        self._user_change(self._state.pan_by, delta.x(), delta.y())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_from = None
            self.setCursor(Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.fit()

    def paintEvent(self, event):
        painter = QPainter(self)
        option = QStyleOption()
        option.initFrom(self)
        self.style().drawPrimitive(QStyle.PE_Widget, option, painter, self)  # фон и рамка из QSS
        if self._image is None:
            return
        frame = 2 if self.property("active") else 1  # толщина рамки из QSS: фото не должно её закрывать
        inner = QRectF(self.rect()).adjusted(frame, frame, -frame, -frame)
        outline = QPainterPath()
        outline.addRoundedRect(inner, _INNER_RADIUS, _INNER_RADIUS)
        painter.setClipPath(outline)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        target = QRectF(*self._state.target_rect())
        visible = target.intersected(inner)
        if visible.isEmpty():
            return
        # Только видимая часть: при зуме 12× весь прямоугольник в десятки тысяч пикселей не нужно передавать
        image = self._paint_image(target)
        scale_x = image.width() / target.width()
        scale_y = image.height() / target.height()
        offset = visible.topLeft() - target.topLeft()
        source = QRectF(
            QPointF(offset.x() * scale_x, offset.y() * scale_y),
            QPointF((offset.x() + visible.width()) * scale_x, (offset.y() + visible.height()) * scale_y),
        )
        painter.drawImage(visible, image, source)

    def _paint_image(self, target):
        """Билинейная отрисовка при уменьшении больше чем вдвое пропускает пиксели: тонкая царапина исчезла бы с экрана.

        Поэтому маленьким окнам — заранее сглаженная копия. Только L0/L1: пересчёт L3 в GUI-потоке был бы заметен,
        а большие уровни и так сменятся на L1 после остановки.
        """
        ratio = self.devicePixelRatioF()
        width, height = max(1, round(target.width() * ratio)), max(1, round(target.height() * ratio))
        if self._level > L1 or self._image.height() < height * _SMOOTH_FROM:
            return self._image
        key = (self._image.cacheKey(), width, height)
        if self._smoothed_key != key:
            self._smoothed_key = key
            self._smoothed = self._image.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        return self._smoothed
