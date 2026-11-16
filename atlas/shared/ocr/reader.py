"""Читатель текста: кадр (QImage или массив BGR) → строки с уверенностью и рамкой в пикселях кадра."""
from __future__ import annotations

import logging
import threading
from collections import namedtuple

try:
    import cv2
    import numpy as np
except ImportError:  # без opencv и numpy читать нечем
    cv2 = np = None

log = logging.getLogger("atlas.ocr")

# text — строка; score — уверенность 0..1; bbox — (x, y, ширина, высота) в пикселях исходного кадра; rotation — поворот, 0/90/180/270
TextLine = namedtuple("TextLine", "text score bbox rotation")

DEFAULT_SETTINGS = {
    "max_side": 2000,  # длинная сторона кадра при чтении, px: меньше — быстрее, но мелкие надписи теряются
    "rotations": (0, 90),  # повороты кадра; каждый — отдельный проход (надписи идут в разные стороны)
    "min_score": 0.5,  # строки с меньшей уверенностью не возвращаются
    "zone_min_side": 736,  # узкая зона дополняется полями: иначе PP-OCR растянет её и прочтёт иначе, чем в целом кадре
    "threads": 1,  # потоков onnxruntime; 0 — как решит onnxruntime
    # параметры PP-OCR, проверенные на целевой машине в digger и matcher
    "engine": {"text_score": 0.3, "box_thresh": 0.3, "unclip_ratio": 1.8},
}

_lock = threading.Lock()
_engines = {}  # потоков onnxruntime -> движок
_failed = []  # причина, по которой движок не загрузился: повторять загрузку на каждом фото незачем


class OcrUnavailable(RuntimeError):
    """Движок чтения не загрузился (нет пакета, не прогрузилась DLL или модель)."""


def engine_available():
    """Есть ли пакеты чтения (без загрузки моделей) и не отказал ли движок раньше."""
    if cv2 is None or _failed:
        return False
    import importlib.util

    return all(importlib.util.find_spec(name) is not None for name in ("rapidocr_onnxruntime", "onnxruntime"))


def _engine(threads):
    if _failed:
        raise OcrUnavailable(_failed[0])
    if threads not in _engines:
        options = {"intra_op_num_threads": threads, "inter_op_num_threads": 1} if threads > 0 else {}
        try:
            from rapidocr_onnxruntime import RapidOCR

            _engines[threads] = RapidOCR(**options)
        except Exception as exc:  # на Win7 — ещё и ошибка загрузки DLL или моделей
            _failed.append("{}: {}".format(type(exc).__name__, exc))
            log.error("PP-OCR не загружается: %s", _failed[0], exc_info=True)
            raise OcrUnavailable(_failed[0]) from exc
    return _engines[threads]


def unrotate(point, turns, width, height):
    """Точка кадра, повёрнутого `np.rot90(..., turns)`, → точка кадра до поворота (`width` × `height`)."""
    x, y = float(point[0]), float(point[1])
    turns %= 4
    if turns == 1:
        return width - 1 - y, x
    if turns == 2:
        return width - 1 - x, height - 1 - y
    if turns == 3:
        return y, height - 1 - x
    return x, y


def _as_bgr(image):
    if hasattr(image, "convertToFormat"):  # QImage
        from atlas.shared.viewer import enhance

        return enhance._to_bgr(image)
    return image


def read_text(image, zone=None, **overrides):
    """Строки текста на кадре по всем поворотам из настроек.

    `image` — QImage или массив B,G,R; `zone` — (x0, y0, x1, y1) в пикселях кадра: читать только её (масштаб
    считается по целому кадру, так что надписи видны читателю так же, как при чтении всего кадра).
    `overrides` — любые ключи `DEFAULT_SETTINGS`. Возвращает список `TextLine`, рамки — в пикселях исходного кадра.
    Бросает `OcrUnavailable`, если движок не загрузился.
    """
    if cv2 is None:
        raise OcrUnavailable("нет OpenCV и NumPy")
    settings = dict(DEFAULT_SETTINGS)
    settings.update(overrides)
    settings["engine"] = dict(DEFAULT_SETTINGS["engine"], **dict(overrides.get("engine") or {}))
    frame = _as_bgr(image)
    height, width = frame.shape[:2]
    scale = min(1.0, float(settings["max_side"]) / float(max(height, width)))
    zx = zy = 0
    if zone:
        zx, zy, zx1, zy1 = [max(0, int(v)) for v in zone]
        frame = frame[zy:zy1, zx:zx1]
        if frame.size == 0:
            return []
    small = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1.0 else frame
    side = int(settings["zone_min_side"]) if zone else 0
    if side > min(small.shape[:2]):
        small = cv2.copyMakeBorder(small, 0, max(0, side - small.shape[0]), 0, max(0, side - small.shape[1]),
                                   cv2.BORDER_REPLICATE)
    small_h, small_w = small.shape[:2]
    lines = []
    with _lock:
        engine = _engine(int(settings["threads"]))
        for rotation in settings["rotations"]:
            turns = int(rotation) // 90
            found, _ = engine(np.ascontiguousarray(np.rot90(small, turns)), **settings["engine"])
            for box, text, score in found or []:
                if float(score) < settings["min_score"]:
                    continue
                points = [unrotate(p, turns, small_w, small_h) for p in box]
                xs = [p[0] / scale for p in points]
                ys = [p[1] / scale for p in points]
                x, y = int(min(xs)) + zx, int(min(ys)) + zy
                bbox = (x, y, max(1, int(round(max(xs))) + zx - x), max(1, int(round(max(ys))) + zy - y))
                lines.append(TextLine(str(text), float(score), bbox, int(rotation)))
    return lines
