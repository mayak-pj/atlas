"""Где на фото плата: рамка светлого предмета на тёмном фоне (шаг 12.1, «Выровнять»).

Фото одной детали снимают два фотоаппарата, в разные дни и разные люди — плата стоит в кадре по-разному.
Окно просмотра ставит найденную рамку на одно место и в один масштаб; файл не меняется.

Без opencv и numpy (в сборку не добавляем ~60 МБ): картинка уменьшается до ANALYSIS_SIDE, порог — по методу Оцу,
рамка — по проекциям строк и столбцов. Счёт идёт через bytes.translate/count и срезы с шагом — это скорость C,
единицы миллисекунд на фото. Не нашлось уверенно (светлый фон, плата сливается с фоном) — None: окно показывает
фото как обычно.
"""
from __future__ import annotations

from collections import Counter
from typing import Optional, Tuple

ANALYSIS_SIDE = 256  # сторона уменьшенной копии; точность рамки ~0,4% стороны фото
ROW_SHARE = 0.03  # строка «занята» платой, если светлых в ней не меньше этой доли
GAP_SHARE = 0.04  # разрыв (тёмная полоса поперёк платы) короче этой доли не делит плату
MAX_BACKGROUND_MEAN = 90  # средняя яркость тёмного класса: фон должен быть тёмным
MIN_AREA, MAX_AREA = 0.02, 0.97  # рамка — доля площади кадра
MIN_FILL = 0.25  # доля светлого внутри рамки
MAX_OUTSIDE = 0.12  # доля светлого вне рамки: больше — на фото не одна плата на фоне, а что-то ещё
PAD = 0.04  # поле вокруг платы на экране, доля её стороны

Frame = Tuple[float, float, float, float]  # x, y, ширина, высота — доли фото


def otsu_threshold(histogram):
    """Порог, лучше всего делящий яркости 0–255 на два класса. histogram — 256 чисел."""
    total = sum(histogram)
    if not total:
        return 128
    weighted_total = sum(value * count for value, count in enumerate(histogram))
    best, best_value = 0.0, 0
    dark_count = dark_sum = 0
    for value in range(256):
        dark_count += histogram[value]
        if not dark_count:
            continue
        light_count = total - dark_count
        if not light_count:
            break
        dark_sum += value * histogram[value]
        dark_mean = dark_sum / dark_count
        light_mean = (weighted_total - dark_sum) / light_count
        between = dark_count * light_count * (dark_mean - light_mean) ** 2
        if between > best:
            best, best_value = between, value
    return best_value


def _main_run(counts, minimum, gap):
    """(начало, конец) самой «тяжёлой» полосы, где counts >= minimum; разрывы не длиннее gap сшиваются. Нет — None."""
    best = None
    best_mass = 0
    start = end = None
    mass = 0
    dark = 0
    for index, count in enumerate(counts):
        if count >= minimum:
            if start is None:
                start, mass = index, 0
            end = index + 1
            mass += count
            dark = 0
        elif start is not None:
            dark += 1
            if dark > gap:
                if mass > best_mass:
                    best, best_mass = (start, end), mass
                start = None
                dark = 0
    if start is not None and mass > best_mass:
        best = (start, end)
    return best


def frame_from_gray(pixels, width, height) -> Optional[Frame]:
    """Рамка платы по серой картинке: pixels — width*height байт яркости, строками без выравнивания."""
    if width < 8 or height < 8 or len(pixels) < width * height:
        return None
    histogram = [0] * 256
    for value, count in Counter(pixels).items():
        histogram[value] = count
    threshold = otsu_threshold(histogram)
    dark_count = sum(histogram[:threshold + 1])
    if not dark_count:
        return None
    if sum(value * histogram[value] for value in range(threshold + 1)) / dark_count > MAX_BACKGROUND_MEAN:
        return None  # фон не тёмный
    table = bytes(1 if value > threshold else 0 for value in range(256))
    mask = pixels[:width * height].translate(table)
    left, right, top, bottom = 0, width, 0, height
    for _ in range(2):  # второй проход уточняет строки по найденным столбцам: посторонний предмет сбоку не растянет рамку
        rows = [mask.count(1, y * width + left, y * width + right) for y in range(height)]
        run = _main_run(rows, max(2, ROW_SHARE * (right - left)), max(1, int(GAP_SHARE * height)))
        if run is None:
            return None
        top, bottom = run
        columns = [mask[top * width + x:bottom * width:width].count(1) for x in range(width)]
        run = _main_run(columns, max(2, ROW_SHARE * (bottom - top)), max(1, int(GAP_SHARE * width)))
        if run is None:
            return None
        left, right = run
    area = (right - left) * (bottom - top)
    if not MIN_AREA <= area / float(width * height) <= MAX_AREA:
        return None
    inside = sum(mask.count(1, y * width + left, y * width + right) for y in range(top, bottom))
    if inside < MIN_FILL * area:
        return None
    outside_area = width * height - area
    if outside_area and (mask.count(1) - inside) / float(outside_area) > MAX_OUTSIDE:
        return None
    return left / width, top / height, (right - left) / width, (bottom - top) / height


def find_frame(image) -> Optional[Frame]:
    """Рамка платы на QImage любого уровня (с учётом EXIF, без поворота Atlas). Не из GUI-потока."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QImage

    if image is None or image.isNull():
        return None
    small = image
    if max(image.width(), image.height()) > ANALYSIS_SIDE:
        small = image.scaled(ANALYSIS_SIDE, ANALYSIS_SIDE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    gray = small.convertToFormat(QImage.Format_Grayscale8)
    width, height, stride = gray.width(), gray.height(), gray.bytesPerLine()
    bits = gray.constBits()
    bits.setsize(stride * height)
    data = bytes(bits)
    if stride != width:
        data = b"".join(data[y * stride:y * stride + width] for y in range(height))
    return frame_from_gray(data, width, height)


def rotated_frame(frame, rotation):
    """Рамка в долях фото, повёрнутого на rotation градусов по часовой стрелке (кратно 90)."""
    x, y, w, h = frame
    rotation %= 360
    if rotation == 90:
        return 1.0 - y - h, x, h, w
    if rotation == 180:
        return 1.0 - x - w, 1.0 - y - h, w, h
    if rotation == 270:
        return y, 1.0 - x - w, h, w
    return frame


def padded_frame(frame, photo_w, photo_h, pad=PAD):
    """Рамка с полем вокруг платы: поле одинаковое в пикселях по обеим осям, от большей стороны платы."""
    x, y, w, h = frame
    margin = pad * max(w * photo_w, h * photo_h)
    mx, my = margin / photo_w, margin / photo_h
    return x - mx, y - my, w + 2 * mx, h + 2 * my


BATCH_DISTANCE = 0.06  # рамки ближе этого (доли кадра: центр и стороны) — одна партия: тот же фотоаппарат и стол


def _distance(first, second):
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    return max(abs(ax + aw / 2 - bx - bw / 2), abs(ay + ah / 2 - by - bh / 2), abs(aw - bw), abs(ah - bh))


def batches(frames, distance=BATCH_DISTANCE):
    """Партии: списки номеров фото с похожим положением платы, в порядке первого фото; внутри — прежний порядок.

    frames — рамки по порядку фото (None — плата не нашлась, такие фото не входят ни в одну партию).
    Фото сравнивается со средней рамкой партии, а не с первой.
    """
    groups = []  # [сумма рамок, число, номера]
    for number, frame in enumerate(frames):
        if frame is None:
            continue
        best, best_distance = None, distance
        for group in groups:
            gap = _distance(tuple(value / group[1] for value in group[0]), frame)
            if gap <= best_distance:
                best, best_distance = group, gap
        if best is None:
            groups.append([list(frame), 1, [number]])
        else:
            best[0] = [total + value for total, value in zip(best[0], frame)]
            best[1] += 1
            best[2].append(number)
    return [group[2] for group in groups]


def batch_order(frames, distance=BATCH_DISTANCE):
    """Порядок фото «по партиям»: номера фото партия за партией, фото без рамки — в конце, в прежнем порядке."""
    order = [number for group in batches(frames, distance) for number in group]
    return order + [number for number, frame in enumerate(frames) if frame is None]
