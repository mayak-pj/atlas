"""Читатель текста (12.6a): рисованная надпись читается, рамка в пикселях кадра, поворот, зона, отказ движка."""
import pytest

from atlas.shared import ocr

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
needs_engine = pytest.mark.skipif(not ocr.engine_available(), reason="нет rapidocr-onnxruntime (requirements-ocr.txt)")

TEXT = "SN74HC595"


def board(width=1200, height=800):
    image = np.full((height, width, 3), (40, 70, 40), np.uint8)
    cv2.putText(image, TEXT, (300, 400), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (230, 230, 230), 4, cv2.LINE_AA)
    return image


def test_unrotate_is_inverse_of_rot90():
    image = np.zeros((4, 7), np.uint8)
    image[1, 5] = 1
    for turns in range(4):
        turned = np.rot90(image, turns)
        y, x = np.argwhere(turned == 1)[0]
        assert ocr.unrotate((x, y), turns, image.shape[1], image.shape[0]) == (5, 1)  # размеры — кадра до поворота


@needs_engine
def test_reads_text_with_box_in_frame_pixels():
    lines = ocr.read_text(board(), rotations=(0,))
    found = [line for line in lines if TEXT in line.text.replace(" ", "")]
    assert found, lines
    x, y, w, h = found[0].bbox
    assert 250 <= x <= 330 and 330 <= y <= 400 and w > 250 and found[0].rotation == 0


@needs_engine
def test_reads_text_turned_on_its_side_and_accepts_qimage():
    from atlas.shared.viewer import enhance

    frame = np.ascontiguousarray(np.rot90(board(), 1))  # надпись «лежит» — нужен проход с поворотом
    lines = ocr.read_text(enhance._to_qimage(frame), rotations=(0, 90, 270))
    assert any(TEXT in line.text.replace(" ", "") for line in lines), lines
    box = next(line for line in lines if TEXT in line.text.replace(" ", ""))
    assert box.bbox[3] > box.bbox[2]  # в кадре рамка высокая; какой проход нашёл — решает сам движок (его классификатор углов узнаёт и 90°)


@needs_engine
def test_zone_reads_only_the_zone_and_keeps_frame_coordinates():
    frame = board()
    cv2.putText(frame, "R408", (50, 700), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (230, 230, 230), 4, cv2.LINE_AA)
    lines = ocr.read_text(frame, zone=(0, 600, 600, 800), rotations=(0,))
    texts = " ".join(line.text for line in lines)
    assert "R408" in texts and TEXT not in texts
    assert all(line.bbox[1] >= 600 - 5 for line in lines)  # координаты — целого кадра, не зоны


def test_unavailable_engine_is_reported_once(monkeypatch):
    monkeypatch.setattr(ocr.reader, "_engines", {})
    monkeypatch.setattr(ocr.reader, "_failed", [])
    import builtins

    real = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "rapidocr_onnxruntime":
            raise ImportError("нет пакета")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(ocr.OcrUnavailable):
        ocr.read_text(board(), rotations=(0,))
    assert not ocr.engine_available()  # повторять загрузку на каждом фото незачем
    with pytest.raises(ocr.OcrUnavailable):
        ocr.read_text(board(), rotations=(0,))
