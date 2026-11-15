"""Улучшение фото при приближении (12.5): мелкие элементы и надписи на размытом фото. Только из рабочего потока.

Улучшается копия видимой части; файл и кэш не меняются. Ничего не дорисовывается: нейросети сверхразрешения
(ESPCN, FSRCNN, EDSR) на размытых платах почти ничего не дали, а деконволюция Ричардсона–Люси «снимает» размытие
и честно возвращает то, что было в кадре.

Режимы (названия — по библиотекам, значок — уровень; «вес» — в `data/enhance_modes.json`):
  deblur — деконволюция по яркости, степень размытия оценивается по самому фото;
  max    — подавление шума + более сильная деконволюция + местный контраст CLAHE;
  pro    — часть фото растягивается до размера на экране и там снимается размытие (деконволюция с регуляризацией
           по полной вариации, плитки): мелкие элементы остаются чёткими при большом зуме.
Все три нужны opencv и numpy; без них режимы в списке серые, улучшение не включается.
"""
from __future__ import annotations

import json

from PyQt5.QtGui import QImage

from atlas.shared.viewer.enhance_worker import Cancelled

try:  # opencv и numpy на целевой машине есть, но программа без них тоже запускается: режимы «Качества» серые
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover
    cv2 = np = None

MIN_SCALE = 0.0  # улучшаем на любом масштабе: включённая кнопка «Качество» работает и при общем виде
MAX_PIXELS = 4_000_000  # размер результата; окно больше — PhotoView просит меньше и растягивает на окно
MODE_DEBLUR, MODE_MAX, MODE_PRO = "deblur", "max", "pro"
_MODES = {MODE_DEBLUR, MODE_MAX, MODE_PRO}
DEFAULT_MODE = MODE_DEBLUR
_PAD = 16  # запас вокруг части фото: у деконволюции искажается край
_MIN_SIGMA, _MAX_SIGMA = 0.5, 3.5  # меньше — фото и так резкое, больше — деконволюция вернёт в основном шум
# отношение энергии границ после размытия σ=1 к исходной → σ размытия фото (калибровка по плате и текстуре)
_SIGMA_BY_RATIO = ((0.30, 0.5), (0.44, 1.0), (0.60, 1.5), (0.72, 2.0), (0.86, 3.0), (0.92, 4.0))
_SHARP_RATIO = 0.27  # у резкого кадра около 0,22, у слегка смягчённого (общий вид, L1) 0,25–0,3
_ITERATIONS = {MODE_DEBLUR: 25, MODE_MAX: 40, MODE_PRO: 40}
_TILE, _TILE_OVERLAP = 256, 56  # «Pro»: размытие оценивается по плиткам, края плиток сшиваются плавно
_PRO_MAX_SIGMA = 10.0  # «Pro»: потолок размытия на сетке экрана; выше на настоящих фото появляются ложные «бусинки» на штрихах
_PRO_MIN_ITERATIONS, _PRO_MAX_ITERATIONS = 30, 80
_FLAT_RANGE = 0.02  # размах яркости плитки (0…1), меньше которого плитка считается ровной
_TV_WEIGHT = 0.004  # «Pro»: сила регуляризации по полной вариации (меньше шума и «звона» у краёв)

_FALLBACK_MODES = (
    {"id": MODE_DEBLUR, "title": "OpenCV", "icon": "signal-low", "weight": "0,1–1 с"},
    {"id": MODE_MAX, "title": "OpenCV NLM", "icon": "signal-medium", "weight": "1–6 с"},
    {"id": MODE_PRO, "title": "OpenCV Pro", "icon": "signal-high", "weight": "1–10 с"},
)


def load_modes(path):
    """Режимы из data/enhance_modes.json; не прочитался — встроенные."""
    try:
        if path is None:
            return _FALLBACK_MODES
        modes = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(modes, list) and modes and all(isinstance(m, dict) and m.get("id") in _MODES for m in modes):
            return tuple(modes)
    except (OSError, ValueError):
        pass
    return _FALLBACK_MODES


def engine_available():
    """Есть ли opencv и numpy: без них ни один режим не работает."""
    return cv2 is not None


def mode_available(mode_info):
    """Строку режима из `enhance_modes.json` можно выбрать: есть opencv и numpy."""
    return engine_available()


def usable_mode(mode):
    """Режим, который можно выполнить; неизвестный или без opencv — None."""
    return mode if mode in _MODES and cv2 is not None else None


def wants_enhance(scale, mode):
    """Нужно ли улучшать при таком масштабе (пикселей экрана на пиксель фото)."""
    return mode is not None and scale >= MIN_SCALE


def _never():
    return False


def _check(cancelled):
    if cancelled():
        raise Cancelled()


def enhanced_crop(image, source, width, height, mode=DEFAULT_MODE, cancelled=None):
    """Часть фото `source` (QRectF в пикселях `image`), растянутая до width×height и улучшенная; None — не вышло.

    `cancelled()` проверяется между шагами снятия размытия (12.8): True — бросает `Cancelled`, фото уже сменилось.
    """
    width, height = int(width), int(height)
    mode = usable_mode(mode)
    if mode is None or width < 1 or height < 1 or width * height > MAX_PIXELS * 1.01:
        return None
    cancelled = cancelled or _never
    if mode == MODE_PRO:
        return _pro(image, source, width, height, cancelled)
    return _deblur(image, source, width, height, mode, cancelled)


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


def richardson_lucy(gray, sigma, iterations, cancelled=_never):
    """Деконволюция гауссовым ядром; gray — float32 0…1."""
    size = int(sigma * 6) | 1
    estimate = gray.copy()
    for _ in range(iterations):
        _check(cancelled)
        blurred = cv2.GaussianBlur(estimate, (size, size), sigma)
        estimate *= cv2.GaussianBlur(gray / np.maximum(blurred, 1e-4), (size, size), sigma)
    return estimate


def richardson_lucy_tv(gray, sigma, iterations, weight=_TV_WEIGHT, cancelled=_never):
    """Деконволюция Ричардсона–Люси с регуляризацией по полной вариации: границы остаются резкими, шум и «звон» не растут.

    gray — float32 0…1. Ничего не дорисовывает: усиливается только то, что размыто в самом кадре.
    """
    size = int(sigma * 6) | 1
    estimate = gray.copy()
    for _ in range(iterations):
        _check(cancelled)
        blurred = cv2.GaussianBlur(estimate, (size, size), sigma)
        correction = cv2.GaussianBlur(gray / np.maximum(blurred, 1e-4), (size, size), sigma)
        grad_y, grad_x = np.gradient(estimate)
        norm = np.sqrt(grad_x * grad_x + grad_y * grad_y + 1e-6)
        divergence = np.gradient(grad_y / norm, axis=0) + np.gradient(grad_x / norm, axis=1)
        estimate = estimate * correction / np.clip(1.0 - weight * divergence, 0.5, 1.5)
        np.clip(estimate, 0.0, 1.5, out=estimate)
    return estimate


def _pro_luma(luma, sigma, cancelled=_never):
    """Яркость «Pro» на той сетке, которая видна на экране: плитки, RL-TV, плавная сшивка; ровные плитки пропускаются.

    sigma — размытие в пикселях этой сетки. Число шагов растёт с размытием (45…80): дальше на настоящих фото
    появляются ложные «бусинки» на штрихах и двойные края, то есть дорисовка.
    """
    height, width = luma.shape
    source = luma.astype(np.float32) / 255.0 + 1e-4
    total = np.zeros_like(source)
    weight_sum = np.zeros_like(source)
    iterations = int(min(_PRO_MAX_ITERATIONS, _PRO_MIN_ITERATIONS + 6 * sigma))
    step = _TILE - _TILE_OVERLAP
    ramp = np.minimum(1.0, (np.arange(_TILE, dtype=np.float32) + 1) / _TILE_OVERLAP * 2)
    window = np.minimum(ramp, ramp[::-1])
    window = np.outer(window, window)
    for top in range(0, max(1, height - _TILE_OVERLAP), step):
        for left in range(0, max(1, width - _TILE_OVERLAP), step):
            bottom, right = min(height, top + _TILE), min(width, left + _TILE)
            top0, left0 = max(0, bottom - _TILE), max(0, right - _TILE)  # плитка у края — прежнего размера
            tile = source[top0:bottom, left0:right]
            flat = float(tile.max() - tile.min()) < _FLAT_RANGE  # ровное поле: деконволюция добавила бы только шум
            done = tile if flat else richardson_lucy_tv(tile, sigma, iterations, cancelled=cancelled)
            part = window[: tile.shape[0], : tile.shape[1]]
            total[top0:bottom, left0:right] += done * part
            weight_sum[top0:bottom, left0:right] += part
    return np.clip(total / np.maximum(weight_sum, 1e-6) * 255.0, 0, 255).astype(np.uint8)


def _pro(image, source, width, height, cancelled=_never):
    """«Pro»: растянуть часть фото до размера на экране и снимать размытие уже там. Так мелкие элементы остаются чёткими
    при большом зуме, а не растягиваются мягкими. Окно меньше фото — деконволюция в размере фото и уменьшение."""
    rect = source.toAlignedRect().adjusted(-_PAD, -_PAD, _PAD, _PAD).intersected(image.rect())
    if rect.isEmpty():
        return None
    ycc = cv2.cvtColor(_to_bgr(image.copy(rect)), cv2.COLOR_BGR2YCrCb)
    sigma = estimate_sigma(ycc[:, :, 0].astype(np.float32))
    scale_x, scale_y = width / source.width(), height / source.height()
    magnify = min(scale_x, scale_y) >= 1.0
    size = (max(1, round(rect.width() * scale_x)), max(1, round(rect.height() * scale_y)))
    if magnify:
        ycc = cv2.resize(ycc, size, interpolation=cv2.INTER_CUBIC)  # не Lanczos: у него свой «звон» на краях
        if sigma is not None:
            grid = min(scale_x, scale_y)  # размытие фото на сетке экрана плюс сглаживание самого растягивания
            sigma = min(float((sigma ** 2 * grid ** 2 + (0.5 * grid) ** 2) ** 0.5), _PRO_MAX_SIGMA)
    if sigma is not None:
        ycc[:, :, 0] = _pro_luma(ycc[:, :, 0], sigma, cancelled)
    result = cv2.cvtColor(ycc, cv2.COLOR_YCrCb2BGR)
    if not magnify:
        result = cv2.resize(result, size, interpolation=cv2.INTER_AREA)
    left = round((source.left() - rect.left()) * scale_x)
    top = round((source.top() - rect.top()) * scale_y)
    out = result[top:top + height, left:left + width]
    if out.shape[0] != height or out.shape[1] != width:
        out = cv2.resize(out, (width, height), interpolation=cv2.INTER_LINEAR)
    return _to_qimage(np.ascontiguousarray(out))


def _deblur(image, source, width, height, mode, cancelled=_never):
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
        done = richardson_lucy(luma.astype(np.float32) / 255.0 + 1e-4, sigma, _ITERATIONS[mode], cancelled)
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
