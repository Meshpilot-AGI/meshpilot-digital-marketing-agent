"""Composite rendering — a model paints the atmosphere, code sets the type.

Neither half can do the other's job. A model cannot be trusted to set a headline (kerning, wrap and
the exact brand face are never guaranteed) and cannot render a third-party mark at all; code cannot
invent a photograph.
"""
from io import BytesIO

from PIL import Image

from glitch_signal.media.render import composite
from glitch_signal.media.render.card import SIZES, Palette
from glitch_signal.media.render.layouts import Content, Spec, render


def _bytes(w, h, colour="#FFFFFF"):
    b = BytesIO()
    Image.new("RGB", (w, h), colour).save(b, "PNG")
    return b.getvalue()


def test_cover_fills_without_stretching():
    """A squashed photograph reads as broken in a way a crop does not — and the model returns
    whatever aspect it likes regardless of what was asked."""
    out = composite.cover(Image.new("RGB", (400, 200)), 1080, 1350)
    assert out.size == (1080, 1350)


def test_cover_handles_an_undersized_backdrop():
    assert composite.cover(Image.new("RGB", (50, 50)), 1080, 1350).size == (1080, 1350)


def test_scrim_guarantees_contrast_for_the_type_band():
    """THE reason the scrim exists. The backdrop is generated fresh per post, so a prompt asking for
    empty shadow sometimes returns a bright frame — and an unreadable headline ships silently,
    because nothing errors."""
    prepared = composite.prepare(_bytes(1080, 1350, "#FFFFFF"), 1080, 1350).convert("L")
    top_band = prepared.crop((0, 0, 1080, int(1350 * 0.25)))
    assert max(top_band.tobytes()) < 120        # a pure-white backdrop is still darkened for type


def test_scrim_also_protects_the_footer():
    prepared = composite.prepare(_bytes(1080, 1350, "#FFFFFF"), 1080, 1350).convert("L")
    foot = prepared.crop((0, int(1350 * 0.94), 1080, 1350))
    assert max(foot.tobytes()) < 160


def test_logo_tile_is_white_backed():
    """Third-party marks arrive as-is and many are dark; straight onto a near-black ground they
    vanish. The tile matches the treatment the product's own site uses."""
    tile, mask = composite.logo_tile(Image.new("RGBA", (100, 100), (0, 0, 0, 255)), 120)
    assert tile.size == (120, 120)
    assert tile.getpixel((2, 60)) == (255, 255, 255)     # white margin around the mark
    assert mask.getpixel((0, 0)) == 0                    # rounded corner is masked out


# ── layouts accept a backdrop, and degrade without one ──────────────────────────────────────────
def _spec(**kw):
    return Spec(content=Content(headline="A headline that wraps onto two lines", kicker="pillar",
                                wordmark="glitchexecutor.com"),
                palette=Palette(), **kw)


def test_every_layout_renders_with_a_backdrop():
    bd = composite.prepare(_bytes(800, 1000, "#404040"), *SIZES["4:5"])
    for layout in ("statement", "comparison", "definition", "numbered", "mechanism"):
        out = render(layout, _spec(backdrop=bd))
        assert Image.open(BytesIO(out)).size == SIZES["4:5"]


def test_every_layout_still_renders_without_one():
    """A backdrop generation failure must degrade to the flat card, never fail the post."""
    for layout in ("statement", "comparison", "definition", "numbered", "mechanism"):
        out = render(layout, _spec())
        assert Image.open(BytesIO(out)).size == SIZES["4:5"]


def test_backdrop_is_actually_used():
    """Guard against the backdrop being accepted and silently ignored."""
    bd = composite.prepare(_bytes(800, 1000, "#803030"), *SIZES["4:5"])
    with_bd = render("statement", _spec(backdrop=bd))
    without = render("statement", _spec())
    assert with_bd != without


def test_comparison_places_a_real_mark_when_one_matches():
    logos = {"FTMO": Image.new("RGBA", (128, 128), (10, 200, 10, 255))}
    c = Content(headline="h", kicker="k", left_label="FTMO", left_body="a",
                right_label="Apex", right_body="b", wordmark="x")
    with_logo = render("comparison", Spec(content=c, palette=Palette(), logos=logos))
    without = render("comparison", Spec(content=c, palette=Palette()))
    assert with_logo != without


def test_comparison_falls_back_when_no_mark_matches():
    """A label we hold no mark for still renders — with the accent bar instead."""
    c = Content(headline="h", kicker="k", left_label="Unknown Firm", left_body="a", wordmark="x")
    out = render("comparison", Spec(content=c, palette=Palette(),
                                    logos={"FTMO": Image.new("RGBA", (64, 64))}))
    assert Image.open(BytesIO(out)).size == SIZES["4:5"]


def test_wordmark_lockup_uses_the_real_mark_when_supplied():
    mark = Image.new("RGBA", (256, 256), (0, 255, 0, 255))
    with_mark = render("statement", _spec(wordmark_logo=mark))
    without = render("statement", _spec())
    assert with_mark != without


# ── backdrop direction ──────────────────────────────────────────────────────────────────────────
from glitch_signal.agent.social import technique  # noqa: E402


def test_backdrop_never_illustrates_the_headline():
    """The first version passed the HEADLINE in as the subject, so the model illustrated the words —
    'trailing and static drawdown' came back as a pulley on a plinth. Generic object photography,
    unrelated to trading. The subject must come from the fixed vocabulary, never from the copy."""
    p = technique.backdrop_prompt(0, style="s", palette="p")
    assert any(sub in p for sub in technique.BACKDROP_SUBJECTS)
    assert "drawdown" not in p.lower()          # copy cannot leak into the subject


def test_backdrop_subjects_are_all_trading_workspace():
    """The reader is a trader; the frame should look like the room they work in."""
    joined = " ".join(technique.BACKDROP_SUBJECTS).lower()
    assert all(w in joined for w in ("monitor", "keyboard", "desk"))


def test_backdrop_states_composition_as_a_proportion():
    """'sits low and small' was one soft clause and the model ignored it, putting the subject
    through the middle of the type. A stated proportion is obeyed."""
    p = technique.backdrop_prompt(0, style="s", palette="p")
    assert "70 percent" in p and "BOTTOM EDGE" in p
    assert "middle of the frame stays empty" in p


def test_backdrop_is_text_free_and_figure_free():
    """Type is composited afterwards — anything the model wrote would collide with it."""
    p = technique.backdrop_prompt(0, style="s", palette="p")
    assert "Render NO text" in p and "no numbers" not in p.lower() or "figure" in p.lower()


def test_backdrop_rotates_subjects_but_is_deterministic():
    a = technique.backdrop_prompt(0, style="s", palette="p")
    b = technique.backdrop_prompt(1, style="s", palette="p")
    assert a != b                                # consecutive posts do not share a frame
    assert a == technique.backdrop_prompt(0, style="s", palette="p")   # same seed, same frame


def test_backdrop_carries_the_brands_banned_imagery():
    p = technique.backdrop_prompt(0, style="s", palette="p", banned="stock traders, candlesticks")
    assert "stock traders" in p
