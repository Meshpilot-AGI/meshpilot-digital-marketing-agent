"""Backdrop preparation — the generated half of a composite card.

The split that makes this work: a model paints the ATMOSPHERE, code sets the TYPE. Neither half can
do the other's job well. A model cannot be trusted to set a headline (kerning, wrap and the exact
brand face are never guaranteed) and it cannot render a third-party mark at all. Code cannot invent
a photograph. Composited, you get depth AND exact typography — which is what a flat card lacks and
what a raw generation cannot promise.

The scrim is not decoration. The backdrop is generated fresh per post, so its brightness varies run
to run: a prompt asking for empty shadow sometimes returns a bright frame. Without a guaranteed
contrast floor the headline would be legible in most posts and invisible in some, which is the worst
possible failure mode because nothing errors — it just ships unreadable.
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter

# How far down the frame the top scrim reaches, and how hard. The type band lives in the upper
# portion of every layout, so the gradient protects it and releases toward the subject below.
_TOP_BAND = 0.72
_TOP_STRENGTH = 225
_TOP_FALLOFF = 2.2
# A shorter, softer scrim at the bottom so the wordmark lockup separates from a busy subject.
_FOOT_BAND = 0.17
_FOOT_STRENGTH = 200
_FOOT_FALLOFF = 1.5


def cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Scale-and-crop to fill the frame, preserving aspect.

    Never stretch: a squashed photograph reads as broken in a way a crop does not, and the model
    returns whatever aspect it feels like regardless of what was asked.
    """
    scale = max(w / img.width, h / img.height)
    img = img.resize((max(w, int(img.width * scale + 1)), max(h, int(img.height * scale + 1))),
                     Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def prepare(data: bytes, w: int, h: int, *, ground: str = "#05070B") -> Image.Image:
    """Backdrop bytes -> a frame that is guaranteed to carry type at `w`x`h`."""
    img = cover(Image.open(BytesIO(data)).convert("RGB"), w, h)

    scrim = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(scrim)
    band = int(h * _TOP_BAND)
    for y in range(band):
        d.line([(0, y), (w, y)], fill=int(_TOP_STRENGTH * (1 - (y / band) ** _TOP_FALLOFF)))
    foot = int(h * _FOOT_BAND)
    for i in range(foot):
        y = h - 1 - i
        val = int(_FOOT_STRENGTH * (1 - (i / foot) ** _FOOT_FALLOFF))
        if val > scrim.getpixel((0, y)):
            d.line([(0, y), (w, y)], fill=val)

    return Image.composite(Image.new("RGB", (w, h), ground), img,
                           scrim.filter(ImageFilter.GaussianBlur(3)))


def logo_tile(logo: Image.Image, size: int, *, radius_ratio: float = 0.24) -> tuple[Image.Image, Image.Image]:
    """A rounded white tile carrying a brand mark, plus its mask.

    White-backed on purpose: third-party marks are supplied as-is and many are dark, so placing one
    straight onto a near-black ground would make it disappear. The tile is the same treatment the
    product's own marquee uses, so the posts match the site.
    """
    tile = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    mark = logo.convert("RGBA").copy()
    mark.thumbnail((size - int(size * 0.16), size - int(size * 0.16)), Image.LANCZOS)
    tile.alpha_composite(mark, ((size - mark.width) // 2, (size - mark.height) // 2))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1],
                                           radius=int(size * radius_ratio), fill=255)
    return tile.convert("RGB"), mask
