"""Улучшение фото при приближении (12.5): мелкие элементы и надписи на размытом фото. Только из рабочего потока.

Улучшается копия видимой части; файл и кэш не меняются. Ничего не дорисовывается: нейросети сверхразрешения
(ESPCN, FSRCNN, EDSR) на размытых платах почти ничего не дали, а деконволюция Ричардсона–Люси «снимает» размытие
и честно возвращает то, что было в кадре.

Режимы (названия — по библиотекам, значок — уровень; «вес» — в `data/enhance_modes.json`):
  light  — усиление границ на чистом Qt (high-pass + «жёсткий свет»), работает всегда;
  deblur — деконволюция по яркости, степень размытия оценивается по фото (нужны opencv и numpy);
  max    — подавление шума + более сильная деконволюция + местный контраст CLAHE;
  pro    — только Mac (презентация): плитки со своей оценкой размытия, деконволюция с регуляризацией по полной
           вариации (меньше шума и «звона»), шумоподавление, контраст. На Windows в списке серый, включить нельзя.
"""
from __future__ import annotations

import json
import sys

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QImage, QPainter

try:  # opencv и numpy на целевой машине есть, но программа без них тоже работает: останется «Лёгкая»
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover
    cv2 = np = None

MIN_SCALE = 0.0  # улучшаем на любом масштабе: включённая кнопка «Качество» работает и при общем виде
MAX_PIXELS = 4_000_000  # размер результата; окно больше — PhotoView просит меньше и растягивает на окно
MODE_LIGHT, MODE_DEBLUR, MODE_MAX, MODE_PRO = "light", "deblur", "max", "pro"
DEFAULT_MODE = MODE_DEBLUR
_PAD = 16  # запас вокруг части фото: у деконволюции искажается край
_MIN_SIGMA, _MAX_SIGMA = 0.5, 3.5  # меньше — фото и так резкое, больше — деконволюция вернёт в основном шум
# отношение энергии границ после размытия σ=1 к исходной → σ размытия фото (калибровка по плате и текстуре)
_SIGMA_BY_RATIO = ((0.30, 0.5), (0.44, 1.0), (0.60, 1.5), (0.72, 2.0), (0.86, 3.0), (0.92, 4.0))
_SHARP_RATIO = 0.27  # у резкого кадра около 0,22, у слегка смягчённого (общий вид, L1) 0,25–0,3
_ITERATIONS = {MODE_DEBLUR: 25, MODE_MAX: 40, MODE_PRO: 40}
_TILE, _TILE_OVERLAP = 224, 48  # «Pro»: размытие оценивается по плиткам, края плиток сшиваются плавно
_PRO_PASSES = 1  # «Pro»: проходов оценки и снятия размытия на плитку; на втором проходе появлялись ореолы и искажения букв
_TV_WEIGHT = 0.004  # «Pro»: сила регуляризации по полной вариации (меньше шума и «звона» у краёв)
PLATFORMS = {MODE_PRO: ("darwin",)}  # режимы, которые считаются только на этих платформах (sys.platform); остальные — везде

_FALLBACK_MODES = (
    {"id": MODE_LIGHT, "title": "Qt", "icon": "signal-low", "weight": "мгновенно"},
    {"id": MODE_DEBLUR, "title": "OpenCV", "icon": "signal-medium", "weight": "0,1–1 с"},
    {"id": MODE_MAX, "title": "OpenCV NLM", "icon": "signal-high", "weight": "1–6 с"},
    {"id": MODE_PRO, "title": "OpenCV Pro", "icon": "signal", "weight": "1–5 с", "platforms": ["darwin"], "unavailable": "только Mac"},
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


_ITERATIONS_OR_LIGHT = {MODE_LIGHT, MODE_DEBLUR, MODE_MAX, MODE_PRO}


def engine_available():
    """Есть ли opencv и numpy для режимов deblur и max."""
    return cv2 is not None


def platform_ok(mode_info):
    """Режим из `enhance_modes.json` можно включить на этой машине: поле `platforms` (sys.platform) его не запрещает."""
    platforms = mode_info.get("platforms")
    return not platforms or sys.platform in platforms


def usable_mode(mode):
    """Режим, который можно выполнить: без opencv — «Лёгкая»; «Pro» не на своей платформе — «OpenCV NLM»."""
    if mode == MODE_PRO and sys.platform not in PLATFORMS[MODE_PRO]:
        mode = MODE_MAX
    if mode in (MODE_DEBLUR, MODE_MAX, MODE_PRO) and cv2 is None:
        return MODE_LIGHT
    return mode if mode in _ITERATIONS_OR_LIGHT else None


def wants_enhance(scale, mode):
    """Нужно ли улучшать при таком масштабе (пикселей экрана на пиксель фото)."""
    return mode is not None and scale >= MIN_SCALE


def enhanced_crop(image, source, width, height, mode=DEFAULT_MODE):
    """Часть фото `source` (QRectF в пикселях `image`), растянутая до width×height и улучшенная; None — не вышло."""
    width, height = int(width), int(height)
    mode = usable_mode(mode)
    if mode is None or width < 1 or height < 1 or width * height > MAX_PIXELS * 1.01:
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
    if ratio < _SHARP_RATIO:
        return None  # граней осталось много: фото резкое, деконволюция добавила бы только шум
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


def richardson_lucy_tv(gray, sigma, iterations, weight=_TV_WEIGHT):
    """Деконволюция Ричардсона–Люси с регуляризацией по полной вариации: границы остаются резкими, шум и «звон» не растут.

    gray — float32 0…1. Ничего не дорисовывает: усиливается только то, что размыто в самом кадре.
    """
    size = int(sigma * 6) | 1
    estimate = gray.copy()
    for _ in range(iterations):
        blurred = cv2.GaussianBlur(estimate, (size, size), sigma)
        correction = cv2.GaussianBlur(gray / np.maximum(blurred, 1e-4), (size, size), sigma)
        grad_y, grad_x = np.gradient(estimate)
        norm = np.sqrt(grad_x * grad_x + grad_y * grad_y + 1e-6)
        divergence = np.gradient(grad_y / norm, axis=0) + np.gradient(grad_x / norm, axis=1)
        estimate = estimate * correction / np.clip(1.0 - weight * divergence, 0.5, 1.5)
        np.clip(estimate, 0.0, 1.5, out=estimate)
    return estimate


def _pro_luma(luma):
    """Яркость «Pro»: плитки со своей оценкой размытия (резкие места не трогаются), RL-TV, шумоподавление, контраст."""
    height, width = luma.shape
    source = luma.astype(np.float32) / 255.0 + 1e-4
    total = np.zeros_like(source)
    weight_sum = np.zeros_like(source)
    step = _TILE - _TILE_OVERLAP
    ramp = np.minimum(1.0, (np.arange(_TILE, dtype=np.float32) + 1) / _TILE_OVERLAP * 2)
    window = np.minimum(ramp, ramp[::-1])
    window = np.outer(window, window)
    for top in range(0, max(1, height - _TILE_OVERLAP), step):
        for left in range(0, max(1, width - _TILE_OVERLAP), step):
            bottom, right = min(height, top + _TILE), min(width, left + _TILE)
            top0, left0 = max(0, bottom - _TILE), max(0, right - _TILE)  # плитка у края — прежнего размера
            tile = source[top0:bottom, left0:right]
            done = tile
            for _ in range(_PRO_PASSES):  # после прохода размытие оценивается заново: ещё мягко — ещё проход, резко — стоп
                sigma = estimate_sigma(done * 255.0)
                if sigma is None:
                    break
                done = richardson_lucy_tv(done, sigma, _ITERATIONS[MODE_PRO])
            part = window[: tile.shape[0], : tile.shape[1]]
            total[top0:bottom, left0:right] += done * part
            weight_sum[top0:bottom, left0:right] += part
    result = np.clip(total / np.maximum(weight_sum, 1e-6) * 255.0, 0, 255).astype(np.uint8)
    result = cv2.fastNlMeansDenoising(result, None, 3, 5, 15)
    return cv2.createCLAHE(clipLimit=1.5, tileGridSize=(4, 4)).apply(result)


def _deblur(image, source, width, height, mode):
    rect = source.toAlignedRect().adjusted(-_PAD, -_PAD, _PAD, _PAD).intersected(image.rect())
    if rect.isEmpty():
        return None
    bgr = _to_bgr(image.copy(rect))
    ycc = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    luma = ycc[:, :, 0]
    if mode == MODE_PRO:
        ycc[:, :, 0] = _pro_luma(luma)
        sigma = None
    else:
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
    shrinking = scale_x < 1 and scale_y < 1  # окно меньше фото: INTER_AREA не даёт ряби
    full = cv2.resize(
        result, (max(1, round(rect.width() * scale_x)), max(1, round(rect.height() * scale_y))),
        interpolation=cv2.INTER_AREA if shrinking else cv2.INTER_LANCZOS4)
    left = round((source.left() - rect.left()) * scale_x)
    top = round((source.top() - rect.top()) * scale_y)
    out = full[top:top + height, left:left + width]
    if out.shape[0] != height or out.shape[1] != width:  # округления у края: подгоняем
        out = cv2.resize(out, (width, height), interpolation=cv2.INTER_LINEAR)
    return _to_qimage(np.ascontiguousarray(out))
