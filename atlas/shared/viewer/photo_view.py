"""PhotoView: одно окно просмотра. Колесо — зум к курсору, перетаскивание — сдвиг, двойной клик — вписать.

Обычный QWidget, а не QGraphicsView: нужна одна картинка без сцены, рисуем только видимую часть.
Любой уровень растягивается на один и тот же прямоугольник из ViewState, поэтому подмена уровня не сдвигает картинку.
"""
from __future__ import annotations

import threading

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QPainter, QPainterPath, QPen, QTransform
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QStyle, QStyleOption, QWidget

from atlas.core import theme
from atlas.shared.viewer import enhance
from atlas.shared.viewer.levels import CURRENT, L0, L1, L3, level_divisor, level_for_scale
from atlas.shared.viewer.object_frame import padded_frame, rotated_frame
from atlas.shared.viewer.view_state import ViewState, rotated_center, rotated_size

SETTLE_MS = 150  # после остановки листания или зума — чёткий уровень (цель: не позже 300 мс)
WHEEL_STEP = 1.2  # за один щелчок колеса, как в макете
_WHEEL_NOTCH = 120.0
_INNER_RADIUS = 7  # скругление QWidget#PhotoView минус рамка
_CAPTION_MARGIN = 10
_SMOOTH_FROM = 2.0  # во сколько раз картинка больше экрана
CURTAIN_GRAB = 10  # px по обе стороны от границы «до/после», за которые её можно схватить
CURTAIN_HANDLE = 30  # диаметр кружка-ручки
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
    _enhanced = pyqtSignal(object, QImage)  # ключ, готовая улучшенная часть; из рабочего потока

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
        self._rotation = 0  # поворот текущего фото, градусы по часовой стрелке
        self._image_rotation = 0  # поворот того, что сейчас на экране: прежнее фото рисуется со своим
        self._level = L0
        self._wanted = L1
        self._full_size = None  # (ширина, высота) исходника; по L0 не вычислить
        self._drag_from = None
        self._failed = False
        self._smoothed = None
        self._smoothed_key = None
        self._overlay = None  # слой фигур (shared/annotate): рисует поверх фото и может забрать мышь
        self._align = False  # «Выровнять»: зум и центр — в долях рамки платы (cache.frame), шаг 12.1
        self._enhance_mode = None  # улучшение при приближении (12.5): None — выключено, иначе id режима из enhance
        self._enh_key = None  # для какой части и размера готова улучшенная копия
        self._enh_image = None
        self._enh_pending = None  # ключ, который сейчас считается в рабочем потоке
        self._show_original = False  # «до»: пока держат клавишу, показываем фото без улучшения
        self._curtain = False  # «до/после»: слева исходное, справа улучшенное, границу можно тянуть
        self._curtain_pos = 0.5  # где граница, доля ширины окна
        self._curtain_drag = False
        self._enhanced.connect(self._on_enhanced)
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
        frame_ready = getattr(cache, "frame_ready", None)
        if frame_ready is not None:
            frame_ready.connect(self._on_frame_ready)

    @property
    def path(self):
        return self._path

    @property
    def shown_level(self):
        """Уровень на экране; None — картинки текущего фото ещё нет."""
        return self._level if self.is_current_shown else None

    @property
    def shown_image_size(self):
        """(ширина, высота) текущего фото на экране: с учётом EXIF и поворота, уровень любой; годится для ориентации. Иначе None."""
        if not self.is_current_shown:
            return None
        return rotated_size(self._image.width(), self._image.height(), self._rotation)

    @property
    def rotation(self):
        return self._rotation

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

    @property
    def aligned(self):
        """Включено «Выровнять» и на текущем фото нашлась плата."""
        return self._state.frame is not None

    def set_align(self, on):
        """«Выровнять»: плата на одном месте и в одном масштабе у всех фото. Файл не меняется, view_changed не посылает.

        Зум и центр остаются теми же числами, но считаются в долях рамки платы. Плата не нашлась — фото целиком, как обычно.
        """
        self._align = bool(on)
        self._apply_frame()

    def _apply_frame(self):
        frame = None
        if self._align:
            if not self.is_current_shown:
                return  # на экране ещё прежнее фото — с прежней рамкой; новая встанет вместе с новой картинкой
            found = getattr(self._cache, "frame", None)
            frame = found(self._path) if found is not None else None
            if frame is not None:
                frame = rotated_frame(frame, self._image_rotation)
                frame = padded_frame(frame, self._state.photo_w, self._state.photo_h)
        if frame != self._state.frame:
            self._state.set_frame(frame)
            self._after_view_change()

    def _on_frame_ready(self, path):
        if path == self._path:
            self._apply_frame()

    def set_enhance(self, mode):
        """Улучшение мелких деталей при приближении: None — выключено, иначе режим ("deblur", "max", "pro"). Файл не меняется."""
        self._enhance_mode = enhance.usable_mode(mode) if mode else None
        self._enh_key = self._enh_image = None
        self._enh_pending = None
        self._after_view_change()

    @property
    def enhance_mode(self):
        return self._enhance_mode

    @property
    def enhanced_shown(self):
        """Улучшенная копия готова и сейчас может быть на экране."""
        return self._enhanced_ready()

    def set_show_original(self, on):
        """«До»: пока true — исходное фото без улучшения (клавиша удерживается). Файл и расчёт не трогаются."""
        if bool(on) != self._show_original:
            self._show_original = bool(on)
            self.update()

    def set_curtain(self, on):
        """«До/после»: слева исходное, справа улучшенное; границу тянут мышью. Видна, только когда улучшенная копия готова."""
        self._curtain = bool(on)
        self._curtain_drag = False
        self.update()

    @property
    def curtain(self):
        return self._curtain

    def set_curtain_pos(self, pos):
        self._curtain_pos = min(0.98, max(0.02, float(pos)))
        self.update()

    @property
    def curtain_pos(self):
        return self._curtain_pos

    def _enhanced_ready(self):
        job = self._enhance_job()
        return job is not None and job[0] == self._enh_key and self._enh_image is not None

    def _curtain_x(self):
        inner = self.inner_rect()
        return inner.left() + inner.width() * self._curtain_pos

    def _paint_geometry(self):
        """(target, visible) в координатах неповёрнутого фото с началом в его центре; None — рисовать нечего. Общее для рисования и улучшения."""
        inner = self.inner_rect()
        target = QRectF(*self._state.target_rect())
        visible = target.intersected(inner)
        if visible.isEmpty():
            return None
        turn = QTransform().translate(target.center().x(), target.center().y()).rotate(self._image_rotation)
        visible = turn.inverted()[0].mapRect(visible)
        width, height = rotated_size(target.width(), target.height(), self._image_rotation)
        return QRectF(-width / 2, -height / 2, width, height), visible

    def _enhance_job(self):
        """Что улучшать сейчас: (ключ, источник в пикселях картинки, размер в пикселях экрана) или None."""
        if self._image is None or not self.is_current_shown or self._level < L1 or self._enhance_mode is None:
            return None
        geometry = self._paint_geometry()
        if geometry is None:
            return None
        target, visible = geometry
        ratio = self.devicePixelRatioF()
        scale = target.width() * ratio / self._image.width()
        if not enhance.wants_enhance(scale, self._enhance_mode) or not self.is_sharp:
            return None  # пока не пришёл уровень, чёткий для этого зума, улучшать нечего
        source = QRectF(
            (visible.left() - target.left()) / target.width() * self._image.width(),
            (visible.top() - target.top()) / target.height() * self._image.height(),
            visible.width() / target.width() * self._image.width(),
            visible.height() / target.height() * self._image.height(),
        )
        size = (max(1, round(visible.width() * ratio)), max(1, round(visible.height() * ratio)))
        if size[0] * size[1] > enhance.MAX_PIXELS:  # большое окно (Retina, полный экран): считаем помельче, на экран растянется
            shrink = (enhance.MAX_PIXELS / (size[0] * size[1])) ** 0.5
            size = (max(1, int(size[0] * shrink)), max(1, int(size[1] * shrink)))
        key = (self._enhance_mode, self._image.cacheKey(), self._image_rotation, tuple(round(v, 2) for v in source.getRect()), size)
        return key, source, size

    def _start_enhance(self):
        job = self._enhance_job()
        if job is None:
            self._enh_key = self._enh_image = None
            return
        key, source, size = job
        if key == self._enh_key or key == self._enh_pending:
            return
        self._enh_pending = key
        image, mode = self._image, self._enhance_mode

        def work():
            try:
                result = enhance.enhanced_crop(image, source, size[0], size[1], mode)
            except Exception:  # улучшение — только украшение: не вышло, остаётся обычная картинка
                result = None
            self._enhanced.emit(key, result if result is not None else QImage())

        threading.Thread(target=work, name="enhance", daemon=True).start()

    def _on_enhanced(self, key, image):
        if key == self._enh_pending:
            self._enh_pending = None
        job = self._enhance_job()
        if image.isNull() or job is None or job[0] != key:
            if job is not None and job[0] != key:
                self._start_enhance()  # пока считалось, окно сдвинули: считаем для нового места
            return
        self._enh_key, self._enh_image = key, image
        self.update()

    def set_overlay(self, overlay):
        """Слой поверх фото: у него методы `paint(painter, view)`, `mouse_press/move/release(view, event) -> bool`, `cursor()`."""
        self._overlay = overlay
        self.refresh_cursor()
        self.update()

    def refresh_cursor(self):
        tool_cursor = self._overlay.cursor() if self._overlay is not None else None
        self.setCursor(tool_cursor if tool_cursor is not None else Qt.OpenHandCursor)

    @property
    def photo_unit(self):
        """Меньшая сторона фото на экране в пикселях окна: от неё считаются толщина линий и размер подписи."""
        return min(self._state.displayed_size())

    def inner_rect(self):
        """Где можно рисовать: окно без рамки."""
        frame = 2 if self.property("active") else 1
        return QRectF(self.rect()).adjusted(frame, frame, -frame, -frame)

    def photo_to_widget(self, x, y):
        """Точка фото (доли неповёрнутого, поворот не важен) → пиксели окна."""
        sx, sy = rotated_center(x, y, self._image_rotation)
        left, top, width, height = self._state.target_rect()
        return QPointF(left + sx * width, top + sy * height)

    def widget_to_photo(self, pos):
        """Пиксели окна → доли неповёрнутого фото; вне фото получаются меньше 0 или больше 1."""
        sx, sy = self._state.to_photo(pos.x(), pos.y())
        return rotated_center(sx, sy, (-self._image_rotation) % 360)

    def set_state(self, zoom, cx, cy):
        """Применить состояние извне (синхронизация). view_changed не посылает."""
        self._state.set_state(zoom, cx, cy)
        self._after_view_change()

    def set_rotation(self, rotation):
        """Человек повернул фото: точка в центре окна остаётся в центре, зум тот же. view_changed не посылает.

        Картинка не пересчитывается: поворачивается только отрисовка, поэтому L3 поворачивается мгновенно, кэш не меняется.
        """
        delta = (rotation - self._rotation) % 360
        if not delta:
            return
        zoom, cx, cy = self._state.state()
        cx, cy = rotated_center(cx, cy, delta)
        self._apply_rotation(rotation)
        self._state.set_state(zoom, cx, cy)

    def _apply_rotation(self, rotation):
        self._rotation = rotation
        if self.is_current_shown:
            self._image_rotation = rotation
            self._state.set_photo_size(*rotated_size(self._image.width(), self._image.height(), rotation))
            self._apply_frame()
        self._after_view_change()

    def set_photo(self, path, rotation=0):
        """Зум и место на экране сохраняются. Сразу — что есть в памяти или L1, через SETTLE_MS — чёткий уровень.

        rotation — сохранённый поворот этого фото. Место не пересчитывается: окна смотрят в одну точку экрана.
        """
        path = str(path)
        if path == self._path:
            if rotation != self._rotation:
                self._apply_rotation(rotation)
            return
        guess = self._needed_level()  # размеры фото в папке одинаковы: уровень нужен тот же, что у прежнего
        self._path = path
        self._rotation = rotation
        self._failed = False
        self._full_size = None
        self._wanted = L1
        self._show_message("")
        # Чёткий уровень уже в памяти (его подготовили заранее) — показываем сразу, без размытого L1 на время SETTLE_MS
        hit = self._cache.peek(path, guess) if guess > L1 else None
        if hit is not None and hit.level >= guess:
            self._adopt(hit.image, hit.level)
        else:
            hit = self._cache.get(path, L1, CURRENT)
            if hit is not None:
                self._adopt(hit.image, hit.level)
        self._settle.start()

    def clear(self):
        self._path = None
        self._image = None
        self._image_path = None
        self._state.set_frame(None)
        self._rotation = 0
        self._image_rotation = 0
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

    @property
    def needed_level(self):
        """Уровень, чёткий для текущего масштаба; соседям его готовят заранее."""
        return self._needed_level()

    def _needed_level(self):
        if self._full_size is None:
            return L1
        width, height = self._state.displayed_size()
        ratio = self.devicePixelRatioF()
        full_w, full_h = rotated_size(*self._full_size, self._rotation)
        return level_for_scale(max(width * ratio / full_w, height * ratio / full_h))

    def _on_settled(self):
        if self._path is None or self._failed:
            return
        if not self.is_current_shown:
            self._show_message(TEXT_LOADING)
            return  # уровень выберем, когда придёт первая картинка: до неё неизвестен размер
        self._wanted = self._needed_level()
        self._start_enhance()
        if self._level != self._wanted:
            hit = self._cache.get(self._path, self._wanted, CURRENT, exact=True)
            if hit is not None and _improves(hit.level, self._level, self._wanted):
                self._adopt(hit.image, hit.level)

    def _adopt(self, image, level):
        first = not self.is_current_shown
        keep_proportions = not first and self._level != L0  # L0 округлён сильно, L1 и выше точны
        self._image = image
        self._image_path = self._path
        self._image_rotation = self._rotation
        self._level = level
        if level != L0:
            divisor = level_divisor(level)
            self._full_size = (image.width() * divisor, image.height() * divisor)
        if not keep_proportions:
            self._state.set_photo_size(*rotated_size(image.width(), image.height(), self._rotation))
        self._apply_frame()
        self._show_message("")
        self.update()
        self._start_enhance()
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
        if self._curtain and event.button() == Qt.LeftButton and self._enhanced_ready() \
                and abs(event.pos().x() - self._curtain_x()) <= CURTAIN_GRAB:
            self._curtain_drag = True  # тянем границу «до/после», а не фото
            self.setCursor(Qt.SplitHCursor)
            return
        if self._overlay is not None and self._overlay.mouse_press(self, event):
            return
        if event.button() == Qt.LeftButton:
            self._drag_from = event.pos()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._curtain_drag:
            inner = self.inner_rect()
            self.set_curtain_pos((event.pos().x() - inner.left()) / max(1.0, inner.width()))
            return
        if self._overlay is not None and self._overlay.mouse_move(self, event):
            return
        if self._drag_from is None:
            return
        delta = event.pos() - self._drag_from
        self._drag_from = event.pos()
        self._user_change(self._state.pan_by, delta.x(), delta.y())

    def mouseReleaseEvent(self, event):
        if self._curtain_drag:
            self._curtain_drag = False
            self.refresh_cursor()
            return
        if self._overlay is not None and self._overlay.mouse_release(self, event):
            return
        if event.button() == Qt.LeftButton:
            self._drag_from = None
            self.refresh_cursor()

    def mouseDoubleClickEvent(self, event):
        if self._overlay is not None and self._overlay.tool is not None and self._overlay.owns(event):
            return  # двойной клик при выбранном инструменте — два быстрых клика рисования, а не «вписать»
        if event.button() == Qt.LeftButton:
            self.fit()

    def paintEvent(self, event):
        painter = QPainter(self)
        option = QStyleOption()
        option.initFrom(self)
        self.style().drawPrimitive(QStyle.PE_Widget, option, painter, self)  # фон и рамка из QSS
        if self._image is None:
            return
        inner = self.inner_rect()  # без рамки из QSS: фото не должно её закрывать
        outline = QPainterPath()
        outline.addRoundedRect(inner, _INNER_RADIUS, _INNER_RADIUS)
        painter.setClipPath(outline)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        geometry = self._paint_geometry()
        if geometry is None:
            return
        target, visible = geometry
        # Дальше координаты неповёрнутого фото с началом в его центре: поворачивается отрисовка, а не пиксели
        left, top, width, height = self._state.target_rect()
        painter.setTransform(QTransform().translate(left + width / 2, top + height / 2).rotate(self._image_rotation))
        ready = self._enhanced_ready() and not self._show_original
        if ready and self._curtain:
            line = self._curtain_x()
            painter.save()
            self._clip_widget_rect(painter, QRectF(inner.left(), inner.top(), line - inner.left(), inner.height()))
            self._draw_plain(painter, target, visible)  # слева — исходное
            painter.restore()
            painter.save()
            self._clip_widget_rect(painter, QRectF(line, inner.top(), inner.right() - line, inner.height()))
            painter.drawImage(visible, self._enh_image)  # справа — улучшенное
            painter.restore()
        elif ready:
            painter.drawImage(visible, self._enh_image)  # улучшенная копия видимой части, шаг 12.5
        else:
            self._draw_plain(painter, target, visible)
        if self._overlay is not None:
            painter.resetTransform()
            painter.setClipping(False)
            self._overlay.paint(painter, self)
        if self._curtain and self._enhanced_ready() and not self._show_original:
            self._paint_curtain_line(painter)

    @staticmethod
    def _clip_widget_rect(painter, rect):
        """Обрезать рисование прямоугольником в координатах окна, хотя painter уже повёрнут и сдвинут (поворот кратен 90°)."""
        painter.setClipRect(painter.transform().inverted()[0].mapRect(rect), Qt.IntersectClip)

    def _draw_plain(self, painter, target, visible):
        """Обычная картинка без улучшения. Только видимая часть: при зуме 12× весь прямоугольник не нужно передавать."""
        image = self._paint_image(target)
        scale_x = image.width() / target.width()
        scale_y = image.height() / target.height()
        offset = visible.topLeft() - target.topLeft()
        source = QRectF(
            QPointF(offset.x() * scale_x, offset.y() * scale_y),
            QPointF((offset.x() + visible.width()) * scale_x, (offset.y() + visible.height()) * scale_y),
        )
        painter.drawImage(visible, image, source)

    def _paint_curtain_line(self, painter):
        """Граница «до/после»: тонкая линия и кружок-ручка посередине. Цвета — из темы."""
        painter.resetTransform()
        painter.setClipping(False)
        painter.setRenderHint(QPainter.Antialiasing, True)
        tokens = theme.current()
        inner = self.inner_rect()
        x = self._curtain_x()
        painter.setPen(QPen(tokens.qcolor("accent"), 2))
        painter.drawLine(QPointF(x, inner.top()), QPointF(x, inner.bottom()))
        center = QPointF(x, inner.center().y())
        painter.setBrush(tokens.qcolor("accent"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(center, CURTAIN_HANDLE / 2, CURTAIN_HANDLE / 2)
        painter.setPen(QPen(tokens.qcolor("bg"), 2))
        for sign in (-1, 1):  # две стрелочки ‹ ›, нарисованные линиями (текстовые символы в интерфейсе нельзя)
            tip = QPointF(x + sign * 7, center.y())
            painter.drawLine(tip, QPointF(x + sign * 3, center.y() - 4))
            painter.drawLine(tip, QPointF(x + sign * 3, center.y() + 4))

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
