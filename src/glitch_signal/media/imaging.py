"""Native, deterministic image editing (Pillow) — complements AI media generation.

AI image models are great at *creating* but weak at exact, repeatable edits (crop to a platform
aspect, resize to spec, stamp a caption/watermark, convert format). This module does those
precisely and cheaply. Pure bytes→bytes so it unit-tests with in-memory images and never touches
the network; the agent's `edit_image` tool wraps it with download + bucket upload.

`apply_ops(data, ops)` runs a sequence of ops:
    {"op": "resize", "width": 1080, "height": 1080}     # height optional → keep aspect
    {"op": "fit", "aspect": "9:16", "mode": "crop"|"pad", "bg": "#000000"}
    {"op": "text", "text": "…", "x": 40, "y": 40, "size": 48, "color": "#fff", "anchor": "la"}
    {"op": "format", "format": "jpeg"|"png"|"webp", "quality": 90}
"""
from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageColor, ImageDraw, ImageFont

_PIL_FORMAT = {"jpeg": "JPEG", "jpg": "JPEG", "png": "PNG", "webp": "WEBP"}


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)   # Pillow ≥10.1: scalable default
    except TypeError:
        return ImageFont.load_default()


def _parse_aspect(aspect: str) -> float:
    a, _, b = str(aspect).partition(":")
    return float(a) / float(b)


def _op_resize(img: Image.Image, op: dict) -> Image.Image:
    w = int(op["width"])
    h = op.get("height")
    if h is None:
        h = round(img.height * (w / img.width))
    return img.resize((w, int(h)), Image.LANCZOS)


def _op_fit(img: Image.Image, op: dict) -> Image.Image:
    target = _parse_aspect(op.get("aspect", "1:1"))
    cur = img.width / img.height
    mode = op.get("mode", "crop")
    if mode == "pad":
        bg = ImageColor.getcolor(op.get("bg", "#000000"), "RGBA")
        if cur > target:  # too wide → pad top/bottom
            new_h = round(img.width / target)
            canvas = Image.new("RGBA", (img.width, new_h), bg)
            canvas.paste(img, (0, (new_h - img.height) // 2))
        else:             # too tall → pad sides
            new_w = round(img.height * target)
            canvas = Image.new("RGBA", (new_w, img.height), bg)
            canvas.paste(img, ((new_w - img.width) // 2, 0))
        return canvas
    # crop (cover): trim the long axis to hit the target ratio, centered
    if cur > target:      # too wide → crop width
        new_w = round(img.height * target)
        left = (img.width - new_w) // 2
        return img.crop((left, 0, left + new_w, img.height))
    new_h = round(img.width / target)  # too tall → crop height
    top = (img.height - new_h) // 2
    return img.crop((0, top, img.width, top + new_h))


def _op_text(img: Image.Image, op: dict) -> Image.Image:
    draw = ImageDraw.Draw(img)
    color = ImageColor.getcolor(op.get("color", "#ffffff"), img.mode)
    draw.text((int(op.get("x", 20)), int(op.get("y", 20))), str(op.get("text", "")),
              fill=color, font=_font(int(op.get("size", 32))), anchor=op.get("anchor"))
    return img


_OPS = {"resize": _op_resize, "fit": _op_fit, "text": _op_text}


def apply_ops(data: bytes, ops: list[dict[str, Any]]) -> bytes:
    """Apply a sequence of edit ops to image bytes; return the edited image bytes."""
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    out_format = _PIL_FORMAT.get((img.format or "PNG").lower(), "PNG")
    quality = 90
    for op in ops or []:
        kind = op.get("op")
        if kind == "format":
            out_format = _PIL_FORMAT.get(str(op.get("format", "png")).lower(), out_format)
            quality = int(op.get("quality", quality))
            continue
        fn = _OPS.get(kind)
        if fn is None:
            raise ValueError(f"unknown image op {kind!r}; known: {sorted(_OPS) + ['format']}")
        img = fn(img, op)
    if out_format == "JPEG":
        img = img.convert("RGB")  # JPEG has no alpha
    buf = io.BytesIO()
    save_kwargs = {"quality": quality} if out_format in ("JPEG", "WEBP") else {}
    img.save(buf, format=out_format, **save_kwargs)
    return buf.getvalue()


def ext_for_format(out_format: str) -> str:
    return {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}.get(out_format.upper(), "png")
