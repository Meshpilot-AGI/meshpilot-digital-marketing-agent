"""Deterministic post cards — the creative path that replaced text-to-image generation.

Origin: the pipeline sent `f"{idea.angle}: {idea.hook}"` to a photorealism model with no art
direction, producing generic stock imagery. Swapping models would not have fixed that brief; and
for a reader allergic to marketing, a glossy generated photo is the wrong creative at any quality.
"""
import io

import pytest
from PIL import Image

from glitch_signal.media.render import card as c


def _img(b: bytes) -> Image.Image:
    return Image.open(io.BytesIO(b))


def test_renders_png_at_the_requested_format():
    for fmt, size in c.SIZES.items():
        img = _img(c.render(c.Card(headline="hello", fmt=fmt)))
        assert img.size == size and img.format == "PNG"


def test_unknown_format_falls_back_to_the_default():
    assert _img(c.render(c.Card(headline="x", fmt="banana"))).size == c.SIZES[c.DEFAULT_FORMAT]


def test_render_is_deterministic():
    """Same input must give byte-identical output — the whole point of leaving the model behind is
    that a brand account looks like one brand every time."""
    card = c.Card(headline="Your daily loss resets on broker time", kicker="rule mechanics",
                  wordmark="glitchexecutor.com")
    assert c.render(card) == c.render(card)


def test_long_headline_shrinks_instead_of_overflowing():
    """Hook length varies every run, so the type has to adapt to the copy rather than clip."""
    short = c.Card(headline="Short hook", fmt="1:1")
    long = c.Card(headline=" ".join(["drawdown"] * 40), fmt="1:1")
    # Both render at the canvas size — the long one is fitted, not spilled onto a taller image.
    assert _img(c.render(short)).size == _img(c.render(long)).size == c.SIZES["1:1"]


def test_headline_never_intrudes_into_the_footer_band():
    """A long hook must keep clear air above the wordmark rather than colliding with it."""
    w, h = c.SIZES["1:1"]
    img = _img(c.render(c.Card(headline=" ".join(["drawdown"] * 40), fmt="1:1"))).convert("L")
    # The strip just above the wordmark baseline should be empty background.
    band = img.crop((0, int(h * 0.87), w, int(h * 0.90)))
    assert max(list(band.tobytes())) < 40  # noqa: PIL deprecation
              # near-black: nothing drawn there


def test_palette_from_dict_ignores_unknown_keys():
    """Tokens come from a JSONB column an operator edits — an extra key must not explode the render."""
    p = c.Palette.from_dict({"bg": "#123456", "wordmark": "x.com", "nonsense": 1})
    assert p.bg == "#123456" and p.fg == c.Palette().fg


def test_palette_none_is_the_default():
    assert c.Palette.from_dict(None) == c.Palette()


def test_accent_colour_actually_appears():
    """The accent rule is the only brand ornament — if the token is ignored the card is unbranded."""
    b = c.render(c.Card(headline="x", palette=c.Palette(accent="#FF0000")))
    colours = {c_ for _n, c_ in (_img(b).convert("RGB").getcolors(maxcolors=1 << 20) or [])}
    assert (255, 0, 0) in colours


def test_wrap_measures_the_real_font_not_an_estimate():
    from PIL import ImageDraw
    img = Image.new("RGB", (500, 100))
    draw = ImageDraw.Draw(img)
    font = c._font(True, 40)
    lines = c._wrap(draw, "aaa bbb ccc ddd eee fff ggg hhh", font, 200)
    assert len(lines) > 1
    assert all(draw.textlength(ln, font=font) <= 200 for ln in lines)


def test_single_unbreakable_word_does_not_loop_forever():
    """A word wider than the line must still emit, not spin the greedy wrapper."""
    from PIL import ImageDraw
    draw = ImageDraw.Draw(Image.new("RGB", (500, 100)))
    assert c._wrap(draw, "supercalifragilistic", c._font(True, 40), 10) == ["supercalifragilistic"]
