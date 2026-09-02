"""A LAYOUT SYSTEM for post cards — several distinct formats, not one repeated template.

One card design, however clean, makes a monotonous feed: every post reads as the same asset with
different words. Real brand accounts run a small set of recurring formats that map to what the post
is doing — stating something, contrasting two things, defining a term, enumerating failure modes,
showing a mechanism. The shared palette, face and margins are what make them feel like one brand;
the differing structure is what makes the feed worth scrolling.

Every layout here is deterministic and honest by construction: no generated imagery, and nothing
that could imply performance. The diagram layout draws a SHAPE, never a measurement — no axis
labels, no figures — because the brand may not publish numbers it does not have.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from io import BytesIO

from PIL import Image, ImageDraw

from glitch_signal.media.render.card import (
    DEFAULT_FORMAT,
    SIZES,
    Palette,
    _clip_words,
    _fit_headline,
    _font,
    _draw_tracked,
    _wrap,
)


@dataclass
class Content:
    """Everything any layout might need. Layouts use the subset they care about."""

    headline: str = ""
    kicker: str = ""
    subhead: str = ""
    wordmark: str = ""
    # comparison
    left_label: str = ""
    left_body: str = ""
    right_label: str = ""
    right_body: str = ""
    # term / list
    term: str = ""
    items: list[str] = field(default_factory=list)


@dataclass
class Spec:
    content: Content
    fmt: str = DEFAULT_FORMAT
    palette: Palette = field(default_factory=Palette)
    # Optional generated backdrop (already scrimmed by `composite.prepare`) and real brand marks
    # keyed by the name the copy uses. Both are optional by design: a backdrop generation failure or
    # a missing logo must degrade to the flat card, never fail the post.
    backdrop: Any = None
    logos: dict[str, Any] = field(default_factory=dict)
    wordmark_logo: Any = None


# ── shared chrome ───────────────────────────────────────────────────────────────────────────────

def _canvas(spec: Spec) -> tuple[Image.Image, ImageDraw.ImageDraw, int, int, int]:
    """The frame every layout draws onto: the generated backdrop when there is one, else flat brand
    ground. Making this the shared entry point is what lets one change lift all five layouts."""
    w, h = SIZES.get(spec.fmt, SIZES[DEFAULT_FORMAT])
    if spec.backdrop is not None:
        img = spec.backdrop if spec.backdrop.size == (w, h) else spec.backdrop.resize((w, h))
        img = img.convert("RGB")
    else:
        img = Image.new("RGB", (w, h), spec.palette.bg)
    return img, ImageDraw.Draw(img), w, h, int(w * 0.09)


def _kicker(draw, spec: Spec, w: int, margin: int, y: int) -> int:
    """Kicker + accent rule. Shared across layouts so the family reads as one system."""
    p = spec.palette
    if spec.content.kicker:
        kf = _font(False, int(w * 0.021))
        _draw_tracked(draw, (margin, y), _clip_words(spec.content.kicker.upper(), 42), kf,
                      p.muted, tracking=w * 0.0032)
        y += int(w * 0.021 * 2.4)
    rule_h = max(3, int(w * 0.004))
    draw.rectangle([margin, y, margin + int(w * 0.10), y + rule_h], fill=p.accent)
    return y + rule_h


def _wordmark(draw, spec: Spec, w: int, h: int, margin: int, img: Image.Image | None = None) -> None:
    """Footer lockup: the real mark beside the name when we have the file, else the name alone.

    A generated approximation of our own logo would be worse than no logo, so this only ever places
    a stored file."""
    if not spec.content.wordmark and spec.wordmark_logo is None:
        return
    p = spec.palette
    if spec.wordmark_logo is not None and img is not None:
        size = int(w * 0.085)
        y = h - margin - size
        mark = spec.wordmark_logo.convert("RGBA").copy()
        mark.thumbnail((size, size), Image.LANCZOS)
        img.paste(mark, (margin, y + (size - mark.height) // 2), mark)
        wf = _font(True, int(w * 0.030))
        bbox = draw.textbbox((0, 0), spec.content.wordmark, font=wf)
        draw.text((margin + mark.width + int(w * 0.022),
                   y + (size - (bbox[3] - bbox[1])) // 2 - bbox[1]),
                  spec.content.wordmark, font=wf, fill=p.fg)
        return
    wf = _font(False, int(w * 0.019))
    draw.text((margin, h - margin - int(w * 0.019)), spec.content.wordmark, font=wf, fill=p.muted)


def _match_logo(logos: dict, label: str) -> Any:
    """Find the mark for a panel label. Matching is loose because the label is copy the LLM wrote
    ("Apex"), not a slug — and an unmatched label simply renders without a logo."""
    key = (label or "").strip().lower()
    if not key or not logos:
        return None
    for name, im in logos.items():
        n = (name or "").lower()
        if key == n or key in n or n in key:
            return im
    return None


def _logo_tile(logo: Any, size: int):
    from glitch_signal.media.render.composite import logo_tile
    return logo_tile(logo, size)


def _png(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


_SCRATCH = ImageDraw.Draw(Image.new("RGB", (8, 8)))


def _measure(text: str, font, max_w: int, leading: int) -> int:
    """Height this paragraph WILL occupy, without drawing it.

    Layouts have to know their total block height before placing anything, or the content anchors to
    the top margin and strands a third of the canvas empty below it. Measuring against the real font
    on a scratch surface is what makes a single centred pass possible.
    """
    if not text:
        return 0
    return len(_wrap(_SCRATCH, text, font, max_w)) * leading


def _panel_h(logos: dict, label: str, body: str, w: int, content_w: int, body_f, body_leading: int) -> int:
    """Height one `comparison` panel will actually render at — must mirror that render branch's
    text width and label height exactly.

    A logo-backed panel draws its body into a column narrower by the logo chip's width, so
    measuring it at the FULL content width (as the no-logo branch does) undercounts wrapped lines
    for long copy. The preflight and the render loop drifting apart is exactly how longer
    comparison copy ends up overlapping the fixed footer lockup.
    """
    if _match_logo(logos, label) is not None:
        chip = int(w * 0.095)
        text_w = content_w - chip - int(w * 0.035)
        label_h = int(chip * 0.06) + int(w * 0.026 * 1.9)
        return max(label_h + _measure(body, body_f, text_w, body_leading), chip)
    text_w = content_w - int(w * 0.035)
    return int(w * 0.026 * 2.0) + _measure(body, body_f, text_w, body_leading)


def _place(h: int, margin: int, footer: int, block_h: int) -> int:
    """Optically centre a measured block between the top margin and the footer band."""
    return margin + int(max(0, h - margin - footer - block_h) * 0.42)


def _para(draw, text: str, font, fill, x: int, y: int, max_w: int, leading: int) -> int:
    for ln in _wrap(draw, text, font, max_w):
        draw.text((x, y), ln, font=font, fill=fill)
        y += leading
    return y


# ── layouts ─────────────────────────────────────────────────────────────────────────────────────

def statement(spec: Spec) -> bytes:
    """The sharp one-liner, set large. The workhorse — but only one voice among several."""
    img, draw, w, h, margin = _canvas(spec)
    p, c = spec.palette, spec.content
    content_w = w - margin * 2
    footer = int(h * 0.17)

    kicker_h = (int(w * 0.021 * 2.4) if c.kicker else 0) + max(3, int(w * 0.004)) + int(h * 0.045)
    hl_font, lines, leading = _fit_headline(draw, c.headline, content_w,
                                            h - margin - footer - kicker_h,
                                            start=int(w * 0.082 * p.font_scale))
    sub_font = _font(False, int(w * 0.030))
    sub_lines = _wrap(draw, c.subhead, sub_font, content_w) if c.subhead else []
    sub_leading = int(w * 0.030 * 1.45)
    block = kicker_h + len(lines) * leading + (int(h * 0.028) + len(sub_lines) * sub_leading
                                               if sub_lines else 0)
    y = margin + int(max(0, h - margin - footer - block) * 0.44)

    y = _kicker(draw, spec, w, margin, y) + int(h * 0.045)
    for ln in lines:
        draw.text((margin, y), ln, font=hl_font, fill=p.fg)
        y += leading
    if sub_lines:
        y += int(h * 0.028)
        _para(draw, c.subhead, sub_font, p.muted, margin, y, content_w, sub_leading)
    _wordmark(draw, spec, w, h, margin, img)
    return _png(img)


def comparison(spec: Spec) -> bytes:
    """Two things set against each other — the strongest format for rule literacy.

    Split into stacked panels rather than columns: on a phone, side-by-side columns force the type
    down to a size that stops being readable in-feed.
    """
    img, draw, w, h, margin = _canvas(spec)
    p, c = spec.palette, spec.content
    content_w = w - margin * 2

    label_f = _font(True, int(w * 0.026))
    body_f = _font(False, int(w * 0.032))
    body_leading = int(w * 0.032 * 1.42)
    panel_gap = int(h * 0.035)
    footer = int(h * 0.15)

    chrome_h = (int(w * 0.021 * 2.4) if c.kicker else 0) + max(3, int(w * 0.004)) + int(h * 0.04)
    hf = lines = leading = None
    head_h = 0
    if c.headline:
        hf, lines, leading = _fit_headline(_SCRATCH, c.headline, content_w, int(h * 0.20),
                                           start=int(w * 0.055))
        head_h = len(lines) * leading + int(h * 0.045)
    panels_h = sum(
        _panel_h(spec.logos, label, body, w, content_w, body_f, body_leading) + panel_gap
        for label, body in ((c.left_label, c.left_body), (c.right_label, c.right_body))
        if (label or body))

    y = _place(h, margin, footer, chrome_h + head_h + panels_h)
    y = _kicker(draw, spec, w, margin, y) + int(h * 0.04)
    if lines:
        for ln in lines:
            draw.text((margin, y), ln, font=hf, fill=p.fg)
            y += leading
        y += int(h * 0.045)

    for i, (label, body) in enumerate(((c.left_label, c.left_body), (c.right_label, c.right_body))):
        if not (label or body):
            continue
        colour = p.accent if i else p.muted
        top = y
        # A real brand mark when the asset library has one. This is the case that forces the whole
        # composite architecture: a model cannot render a third-party logo, so a post contrasting
        # two firms is only possible by placing stored files.
        logo = _match_logo(spec.logos, label)
        if logo is not None:
            chip = int(w * 0.095)
            tile, mask = _logo_tile(logo, chip)
            img.paste(tile, (margin, y), mask)
            text_x = margin + chip + int(w * 0.035)
            _draw_tracked(draw, (text_x, y + int(chip * 0.06)), label.upper(), label_f, colour,
                          tracking=w * 0.0022)
            yy = y + int(chip * 0.06) + int(w * 0.026 * 1.9)
            yy = _para(draw, body, body_f, p.fg, text_x, yy, content_w - (text_x - margin),
                       body_leading)
            y = max(yy, top + chip) + panel_gap
            continue
        # No mark: fall back to the accent bar, which gives the eye the same asymmetry.
        _draw_tracked(draw, (margin + int(w * 0.035), y), label.upper(), label_f, colour,
                      tracking=w * 0.0022)
        y += int(w * 0.026 * 2.0)
        y = _para(draw, body, body_f, p.fg, margin + int(w * 0.035), y,
                  content_w - int(w * 0.035), body_leading)
        draw.rectangle([margin, top, margin + max(3, int(w * 0.005)),
                        y - int(body_leading * 0.25)], fill=colour)
        y += panel_gap

    _wordmark(draw, spec, w, h, margin, img)
    return _png(img)


def definition(spec: Spec) -> bytes:
    """Glossary card: the term, oversized, then plain-language meaning. Editorial, not promotional."""
    img, draw, w, h, margin = _canvas(spec)
    p, c = spec.palette, spec.content
    content_w = w - margin * 2

    body_f = _font(False, int(w * 0.034))
    body_leading = int(w * 0.034 * 1.45)
    footer = int(h * 0.15)
    tf, lines, leading = _fit_headline(_SCRATCH, c.term or c.headline, content_w, int(h * 0.30),
                                       start=int(w * 0.090))
    chrome_h = (int(w * 0.021 * 2.4) if c.kicker else 0) + max(3, int(w * 0.004)) + int(h * 0.06)
    block = (chrome_h + len(lines) * leading + int(h * 0.035)
             + _measure(c.subhead or c.headline, body_f, content_w, body_leading))
    y = _kicker(draw, spec, w, margin, _place(h, margin, footer, block)) + int(h * 0.06)
    for ln in lines:
        draw.text((margin, y), ln, font=tf, fill=p.accent)
        y += leading

    y += int(h * 0.035)
    y = _para(draw, c.subhead or c.headline, body_f, p.fg, margin, y, content_w, body_leading)
    _wordmark(draw, spec, w, h, margin, img)
    return _png(img)


def numbered(spec: Spec) -> bytes:
    """Enumerated failure modes. Carries more substance than a one-liner without becoming a wall."""
    img, draw, w, h, margin = _canvas(spec)
    p, c = spec.palette, spec.content
    content_w = w - margin * 2

    num_f = _font(True, int(w * 0.030))
    item_f = _font(False, int(w * 0.032))
    leading_i = int(w * 0.032 * 1.42)
    indent = int(w * 0.075)
    footer = int(h * 0.15)

    chrome_h = (int(w * 0.021 * 2.4) if c.kicker else 0) + max(3, int(w * 0.004)) + int(h * 0.04)
    hf = lines = leading = None
    head_h = 0
    if c.headline:
        hf, lines, leading = _fit_headline(_SCRATCH, c.headline, content_w, int(h * 0.22),
                                           start=int(w * 0.058))
        head_h = len(lines) * leading + int(h * 0.04)
    items_h = sum(_measure(it, item_f, content_w - indent, leading_i) + int(h * 0.026)
                  for it in c.items[:5])

    y = _place(h, margin, footer, chrome_h + head_h + items_h)
    y = _kicker(draw, spec, w, margin, y) + int(h * 0.04)
    if lines:
        for ln in lines:
            draw.text((margin, y), ln, font=hf, fill=p.fg)
            y += leading
        y += int(h * 0.04)
    for i, item in enumerate(c.items[:5], start=1):
        draw.text((margin, y), f"{i:02d}", font=num_f, fill=p.accent)
        end = _para(draw, item, item_f, p.fg, margin + indent, y, content_w - indent, leading_i)
        y = end + int(h * 0.026)

    _wordmark(draw, spec, w, h, margin, img)
    return _png(img)


def mechanism(spec: Spec) -> bytes:
    """A drawn diagram of the trailing-drawdown mechanic.

    Deliberately UNLABELLED and unitless: it shows that the floor ratchets up with the equity peak
    and never comes back down. That is a shape, not a measurement — so it stays inside the rule
    that we publish no figures we do not have. Any axis number here would be invented.
    """
    img, draw, w, h, margin = _canvas(spec)
    p, c = spec.palette, spec.content
    content_w = w - margin * 2

    plot_h = int(h * 0.30)
    sub_f = _font(False, int(w * 0.030))
    sub_leading = int(w * 0.030 * 1.45)
    footer = int(h * 0.15)
    chrome_h = (int(w * 0.021 * 2.4) if c.kicker else 0) + max(3, int(w * 0.004)) + int(h * 0.04)
    hf = lines = leading = None
    head_h = 0
    if c.headline:
        hf, lines, leading = _fit_headline(_SCRATCH, c.headline, content_w, int(h * 0.20),
                                           start=int(w * 0.058))
        head_h = len(lines) * leading
    block = (chrome_h + head_h + int(h * 0.05) + plot_h + int(h * 0.075)
             + _measure(c.subhead, sub_f, content_w, sub_leading))

    y = _kicker(draw, spec, w, margin, _place(h, margin, footer, block)) + int(h * 0.04)
    if lines:
        for ln in lines:
            draw.text((margin, y), ln, font=hf, fill=p.fg)
            y += leading
    y += int(h * 0.05)
    top, bottom = y, y + plot_h
    n = 220
    # A deterministic pseudo-equity curve: a rising trend with oscillation. Fixed coefficients, no
    # RNG — the same card must render identically every time.
    pts, floor_pts, peak = [], [], 0.0
    for i in range(n):
        t = i / (n - 1)
        v = (0.55 * t + 0.13 * math.sin(t * 8.5) + 0.05 * math.sin(t * 21.0) + 0.10)
        peak = max(peak, v)
        pts.append((margin + t * content_w, bottom - v * plot_h))
        # the floor trails the peak by a fixed distance and never retreats
        floor_pts.append((margin + t * content_w, bottom - max(0.0, peak - 0.22) * plot_h))

    draw.line(floor_pts, fill=p.accent, width=max(3, int(w * 0.004)), joint="curve")
    draw.line(pts, fill=p.fg, width=max(4, int(w * 0.005)), joint="curve")

    lab_f = _font(False, int(w * 0.023))
    draw.text((margin, bottom + int(h * 0.022)), "equity", font=lab_f, fill=p.fg)
    draw.text((margin + int(w * 0.22), bottom + int(h * 0.022)), "trailing floor",
              font=lab_f, fill=p.accent)

    if c.subhead:
        _para(draw, c.subhead, sub_f, p.muted, margin, bottom + int(h * 0.075), content_w,
              sub_leading)
    _wordmark(draw, spec, w, h, margin, img)
    return _png(img)


LAYOUTS = {
    "statement": statement,
    "comparison": comparison,
    "definition": definition,
    "numbered": numbered,
    "mechanism": mechanism,
}


def render(layout: str, spec: Spec) -> bytes:
    """Render by layout name, falling back to `statement` for an unknown one."""
    return LAYOUTS.get(layout, statement)(spec)
