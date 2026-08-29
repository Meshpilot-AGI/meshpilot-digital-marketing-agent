"""Native image editing (Pillow) — pure bytes→bytes ops, in-memory, no network."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from glitch_signal.media.imaging import apply_ops


def _png(w: int, h: int, color=(200, 30, 30, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _dims(data: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(data)).size


def test_resize_exact():
    out = apply_ops(_png(200, 100), [{"op": "resize", "width": 50, "height": 80}])
    assert _dims(out) == (50, 80)


def test_resize_keeps_aspect_when_height_omitted():
    out = apply_ops(_png(200, 100), [{"op": "resize", "width": 100}])
    assert _dims(out) == (100, 50)                       # aspect preserved


def test_fit_crop_to_square():
    out = apply_ops(_png(200, 100), [{"op": "fit", "aspect": "1:1", "mode": "crop"}])
    w, h = _dims(out)
    assert w == h == 100                                 # cropped the wide axis, centered


def test_fit_pad_to_portrait():
    out = apply_ops(_png(200, 100), [{"op": "fit", "aspect": "9:16", "mode": "pad"}])
    w, h = _dims(out)
    assert abs((w / h) - (9 / 16)) < 0.02                # padded to target aspect


def test_text_overlay_produces_valid_image():
    out = apply_ops(_png(300, 200), [{"op": "text", "text": "SALE", "size": 40, "color": "#fff"}])
    assert _dims(out) == (300, 200)                      # same size, still decodable
    Image.open(io.BytesIO(out)).verify()


def test_format_jpeg_drops_alpha_and_encodes_jpeg():
    out = apply_ops(_png(64, 64), [{"op": "format", "format": "jpeg", "quality": 80}])
    im = Image.open(io.BytesIO(out))
    assert im.format == "JPEG" and im.mode == "RGB"      # JPEG has no alpha


def test_pipeline_of_ops():
    out = apply_ops(_png(400, 400), [
        {"op": "fit", "aspect": "16:9", "mode": "crop"},
        {"op": "resize", "width": 320},
        {"op": "format", "format": "webp"},
    ])
    im = Image.open(io.BytesIO(out))
    assert im.format == "WEBP" and im.size[0] == 320


def test_unknown_op_raises():
    with pytest.raises(ValueError, match="unknown image op"):
        apply_ops(_png(10, 10), [{"op": "sharpen"}])
