"""Улучшение фото при приближении (12.5): мелкие элементы и надписи на размытом фото. Только из рабочего потока.

Улучшается копия видимой части; файл и кэш не меняются. Ничего не дорисовывается: нейросети сверхразрешения
(ESPCN, FSRCNN, EDSR) на размытых платах почти ничего не дали, а деконволюция Ричардсона–Люси «снимает» размытие
и честно возвращает то, что было в кадре.

Режимы (названия и «вес» — `data/enhance_modes.json`):
  light  — усиление границ на чистом Qt (high-pass + «жёсткий свет»), работает всегда;
  deblur — деконволюция по яркости, степень размытия оценивается по фото (нужны opencv и numpy);
  max    — подавление шума + более сильная деконволюция + местный контраст CLAHE.
"""
from __future__ import annotations

import json

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QImage, QPainter

try:  # opencv и numpy на целевой машине есть, но программа без них тоже работает: останется «Лёгкая»
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover
    cv2 = np = None

MIN_SCALE = 1.25  # пикселей экрана на пиксель фото, с которого улучшаем: меньше — картинка и так чёткая
MAX_PIXELS = 4_000_000  # размер результата на экране; больше не делаем
MODE_LIGHT, MODE_DEBLUR, MODE_MAX = "light", "deblur", "max"
DEFAULT_MODE = MODE_DEBLUR
_PAD = 16  # запас вокруг части фото: у деконволюции искажается край
_MIN_SIGMA, _MAX_SIGMA = 0.7, 3.5  # меньше — фото и так резкое, больше — деконволюция вернёт в основном шум
# отношение энергии границ после размытия σ=1 к исходной → σ размытия фото (калибровка по плате и текстуре)
_SIGMA_BY_RATIO = ((0.30, 0.5), (0.44, 1.0), (0.60, 1.5), (0.72, 2.0), (0.86, 3.0), (0.92, 4.0))
_ITERATIONS = {MODE_DEBLUR: 25, MODE_MAX: 40}

_FALLBACK_MODES = (
    {"id": MODE_LIGHT, "title": "Лёгкая", "weight": "мгновенно", "tip": ""},
    {"id": MODE_DEBLUR, "title": "Снять размытие", "weight": "0,1–1 с", "tip": ""},
    {"id": MODE_MAX, "title": "Максимум", "weight": "1–6 с", "tip": ""},
)


def load_modes(path):
    """Режимы из data/enhance_modes.json; не прочитался — встроенные."""
    try:
        if path is None:
            return _FALLBACK_MODES
        modes = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(modes, list) and all(isinstance(m, dict) and m.get("id") in _ITERATIONS_OR_LIGHT for m in modes):
            return tuple(modes)
    except (OSError, ValueError):
        pass
    return _FALLBACK_MODES


_ITERATIONS_OR_LIGHT = {MODE_LIGHT, MODE_DEBLUR, MODE_MAX}


def engine_available():
    """Есть ли opencv и numpy для режимов deblur и max."""
    return cv2 is not None


def usable_mode(mode):
    """Режим, который можно выполнить: без opencv — «Лёгкая»."""
    if mode in (MODE_DEBLUR, MODE_MAX) and cv2 is None:
        return MODE_LIGHT
    return mode if mode in _ITERATIONS_OR_LIGHT else None


def wants_enhance(scale, mode):
    """Нужно ли улучшать при таком масштабе (пикселей экрана на пиксель фото)."""
    return mode is not None and scale >= MIN_SCALE


def enhanced_crop(image, source, width, height, mode=DEFAULT_MODE):
    """Часть фото `source` (QRectF в пикселях `image`), растянутая до width×height и улучшенная; None — не вышло."""
    width, height = int(width), int(height)
    mode = usable_mode(mode)
    if mode is None or width < 1 or height < 1 or width * height > MAX_PIXELS:
        return None
    if mode == MODE_LIGHT:
        return _light(image, source, width, height)
    return _deblur(image, source, width, height, mode)


# --- «Лёгкая»: Qt -------------------------------------------------------------------------------------

def _light(image, source, width, height):
    crop = image.copy(source.toAlignedRect().intersected(image.rect()))
    if crop.isNull():
        return None
    base = crop.convertToFormat(QImage.Format_RGB32).scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    small = base.scaled(
        max(1, crop.width() // 3), max(1, crop.height() // 3), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    blurred = small.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    blurred.invertPixels()  # 255 − размытое
    high = QImage(width, height, QImage.Format_RGB32)
    high.fill(0)
    painter = QPainter(high)
    painter.setCompositionMode(QPainter.CompositionMode_Plus)
    painter.setOpacity(0.5)
    painter.drawImage(0, 0, base)
    painter.drawImage(0, 0, blurred)  # 0,5·(фото − размытое) + 127,5
    painter.end()
    result = QImage(base)
    result.detach()
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode_HardLight)
    painter.drawImage(0, 0, high)
    painter.drawImage(0, 0, high)
    painter.end()
    return result


# --- «Снять размытие» и «Максимум»: opencv ---------------------------------------------------------------

def _to_bgr(image):
    """QImage → массив B,G,R (копия)."""
    image = image.convertToFormat(QImage.Format_RGB32)
    ptr = image.constBits()
    ptr.setsize(image.byteCount())
    rows = np.frombuffer(ptr, np.uint8).reshape(image.height(), image.bytesPerLine())
    return np.ascontiguousarray(rows[:, : image.width() * 4].reshape(image.height(), image.width(), 4)[:, :, :3])


def _to_qimage(bgr):
    height, width = bgr.shape[:2]
    bgra = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
    image = QImage(bgra.data, width, height, bgra.strides[0], QImage.Format_RGB32)
    return image.copy()  # данные принадлежат массиву, который сейчас исчезнет


def _edge_energy(gray):
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1)
    return float(np.mean(gx * gx + gy * gy))


def estimate_sigma(gray):
    """σ размытия фото в его пикселях по доле границ, которая пропадает при ещё одном размытии; None — фото и так резкое."""
    energy = _edge_energy(gray)
    if energy < 1.0:
        return None  # ровное поле: оценить нечего
    ratio = _edge_energy(cv2.GaussianBlur(gray, (0, 0), 1.0)) / energy
    if ratio <= _SIGMA_BY_RATIO[0][0]:
        sigma = _SIGMA_BY_RATIO[0][1]
    elif ratio >= _SIGMA_BY_RATIO[-1][0]:
        sigma = _SIGMA_BY_RATIO[-1][1]
    else:
        sigma = _SIGMA_BY_RATIO[-1][1]
        for (r0, s0), (r1, s1) in zip(_SIGMA_BY_RATIO, _SIGMA_BY_RATIO[1:]):
            if r0 <= ratio <= r1:
                sigma = s0 + (s1 - s0) * (ratio - r0) / (r1 - r0)
                break
    return None if sigma < _MIN_SIGMA else min(sigma, _MAX_SIGMA)


def richardson_lucy(gray, sigma, iterations):
    """Деконволюция гауссовым ядром; gray — float32 0…1."""
    size = int(sigma * 6) | 1
    estimate = gray.copy()
    for _ in range(iterations):
        blurred = cv2.GaussianBlur(estimate, (size, size), sigma)
        estimate *= cv2.GaussianBlur(gray / np.maximum(blurred, 1e-4), (size, size), sigma)
    return estimate


def _deblur(image, source, width, height, mode):
    rect = source.toAlignedRect().adjusted(-_PAD, -_PAD, _PAD, _PAD).intersected(image.rect())
    if rect.isEmpty():
        return None
    bgr = _to_bgr(image.copy(rect))
    ycc = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    luma = ycc[:, :, 0]
    sigma = estimate_sigma(luma.astype(np.float32))
    if sigma is not None:
        if mode == MODE_MAX:
            luma = cv2.fastNlMeansDenoising(luma, None, 4, 5, 15)
        done = richardson_lucy(luma.astype(np.float32) / 255.0 + 1e-4, sigma, _ITERATIONS[mode])
        luma = np.clip(done * 255.0, 0, 255).astype(np.uint8)
        if mode == MODE_MAX:
            luma = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(4, 4)).apply(luma)
        ycc[:, :, 0] = luma
    result = cv2.cvtColor(ycc, cv2.COLOR_YCrCb2BGR)
    scale_x, scale_y = width / source.width(), height / source.height()
    full = cv2.resize(
        result, (max(1, round(rect.width() * scale_x)), max(1, round(rect.height() * scale_y))),
        interpolation=cv2.INTER_LANCZOS4)
    left = round((source.left() - rect.left()) * scale_x)
    top = round((source.top() - rect.top()) * scale_y)
    out = full[top:top + height, left:left + width]
    if out.shape[0] != height or out.shape[1] != width:  # округления у края: подгоняем
        out = cv2.resize(out, (width, height), interpolation=cv2.INTER_LINEAR)
    return _to_qimage(np.ascontiguousarray(out))
