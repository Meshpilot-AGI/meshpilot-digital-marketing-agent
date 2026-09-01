"""Typographic post cards, rendered deterministically with Pillow.

Why this exists instead of a text-to-image model:

A generative model renders a *different-looking brand every time*, which is the opposite of what a
brand account needs, and its text is only approximately right — kerning, wrap and the exact brand
face are never guaranteed. For a reader who is allergic to marketing, a glossy AI photograph also
reads as stock and undermines the trust the copy is trying to build. The strongest creative for this
brand is the sentence itself, set well.

So the headline IS the image: real typography, exact brand colour, perfect wrap, every time, for
essentially zero marginal cost. Pillow was already a dependency for deterministic image work; the
Inter face is vendored under `fonts/` (SIL OFL 1.1, see fonts/OFL.txt).
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

_FONTS = pathlib.Path(__file__).resolve().parent / "fonts"
_REGULAR = _FONTS / "Inter-400.ttf"
_BOLD = _FONTS / "Inter-700.ttf"

# Canvas sizes per social format. 4:5 is the default: it occupies the most feed height on
# Instagram/Facebook without being cropped, and reads fine when scaled down elsewhere.
SIZES: dict[str, tuple[int, int]] = {
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}
DEFAULT_FORMAT = "4:5"


@dataclass
class Palette:
    """Design tokens. Deliberately small — a card that needs more than this is a different design."""

    bg: str = "#0B0E14"          # near-black, not pure black: pure black crushes on OLED feeds
    fg: str = "#F2F4F8"          # off-white body/headline
    muted: str = "#7C8797"       # kicker + wordmark
    accent: str = "#4ADE80"      # single accent, used sparingly (rule + kicker)
    font_scale: float = 1.0

    @classmethod
    def from_dict(cls, d: dict | None) -> "Palette":
        d = d or {}
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Card:
    headline: str
    kicker: str = ""
    subhead: str = ""
    wordmark: str = ""
    fmt: str = DEFAULT_FORMAT
    palette: Palette = field(default_factory=Palette)


def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_BOLD if bold else _REGULAR), size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
          max_w: int) -> list[str]:
    """Greedy word wrap measured against the ACTUAL font, not an estimated character width."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _fit_headline(draw: ImageDraw.ImageDraw, text: str, max_w: int, max_h: int,
                  start: int, min_size: int = 34) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """Shrink until the wrapped headline fits the box.

    Auto-fitting rather than truncating matters: a hook is written by an LLM and its length varies
    run to run, so a fixed size would either clip a long line or leave a short one looking lost.
    """
    size = start
    while size > min_size:
        font = _font(True, size)
        lines = _wrap(draw, text, font, max_w)
        leading = int(size * 1.18)
        if len(lines) * leading <= max_h:
            return font, lines, leading
        size -= 4
    font = _font(True, min_size)
    return font, _wrap(draw, text, font, max_w), int(min_size * 1.18)


def _draw_tracked(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
                  font: ImageFont.FreeTypeFont, fill: str, tracking: float) -> None:
    """Letter-spaced text. Pillow has no tracking, so step per glyph.

    Worth the loop: an uppercase kicker without added tracking reads cramped and cheap, and this
    label is the one place the design signals editorial rather than promotional.
    """
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking


def _clip_words(text: str, limit: int) -> str:
    """Trim to a WORD boundary. A hard slice leaves the kicker ending mid-word, which reads as a
    rendering bug rather than a label."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut or text[:limit]


def render(card: Card) -> bytes:
    """Render the card to PNG bytes."""
    w, h = SIZES.get(card.fmt, SIZES[DEFAULT_FORMAT])
    p = card.palette
    img = Image.new("RGB", (w, h), p.bg)
    draw = ImageDraw.Draw(img)

    margin = int(w * 0.09)
    content_w = w - margin * 2
    # Reserve enough that even a headline shrunk to its floor keeps clear air above the wordmark —
    # a long hook must never crowd the footer.
    footer_band = int(h * 0.17)
    top_band = margin

    # Measure the whole block BEFORE drawing, then centre it optically. Anchoring to the top left a
    # short headline stranded above half a canvas of dead space — and hook length varies every run,
    # so the composition has to adapt to the copy rather than the copy fitting a fixed slot.
    kicker_h = int(w * 0.021 * 2.4) if card.kicker else 0
    rule_h = max(3, int(h * 0.004))
    rule_block = rule_h + int(h * 0.045)

    avail_h = h - top_band - footer_band - kicker_h - rule_block
    hl_font, lines, leading = _fit_headline(
        draw, card.headline, content_w, avail_h, start=int(w * 0.082 * p.font_scale))
    headline_h = len(lines) * leading

    sub_font = _font(False, int(w * 0.030))
    sub_lines = _wrap(draw, card.subhead, sub_font, content_w) if card.subhead else []
    sub_leading = int(w * 0.030 * 1.45)
    sub_h = (int(h * 0.028) + len(sub_lines) * sub_leading) if sub_lines else 0

    block_h = kicker_h + rule_block + headline_h + sub_h
    # Optical centre sits slightly ABOVE true centre — a block centred by pure arithmetic reads as
    # sagging, and the wordmark already weights the bottom.
    slack = max(0, h - top_band - footer_band - block_h)
    y = top_band + int(slack * 0.44)

    if card.kicker:
        kf = _font(False, int(w * 0.021))
        _draw_tracked(draw, (margin, y), _clip_words(card.kicker.upper(), 42), kf, p.muted,
                      tracking=w * 0.0032)
        y += kicker_h

    # Accent rule — the only ornament. One short line, brand colour, doing the work a logo lockup
    # would otherwise do.
    draw.rectangle([margin, y, margin + int(w * 0.10), y + rule_h], fill=p.accent)
    y += rule_block

    for ln in lines:
        draw.text((margin, y), ln, font=hl_font, fill=p.fg)
        y += leading

    if sub_lines:
        y += int(h * 0.028)
        for ln in sub_lines:
            draw.text((margin, y), ln, font=sub_font, fill=p.muted)
            y += sub_leading

    if card.wordmark:
        wf = _font(False, int(w * 0.019))
        draw.text((margin, h - margin - int(w * 0.019)), card.wordmark, font=wf, fill=p.muted)

    from io import BytesIO
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
