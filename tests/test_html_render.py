"""GROW-SOCIAL-RENDER-2 — deterministic HTML card renderer.

Pure helpers need no env/DB; the render tests shell out to headless Chrome
(skipped if no Chrome on the box).
"""
import pathlib

import pytest

from glitch_signal.media import html_render as hr


def test_theme_is_brand_scoped_no_cross_tenant_bleed():
    ge = hr.theme_for("glitch_executor")
    assert ge.accent == "#2dd4bf"                       # GE teal
    other = hr.theme_for("some-other-client")
    assert other.accent != ge.accent                    # never GE's look
    assert "indigo" or other.accent == "#6366f1"


def test_build_card_html_includes_real_text_and_escapes():
    spec = hr.CardSpec(
        eyebrow="Rule Trap Autopsy",
        headline='Same $100k account. Different floor.',
        subhead="Static vs trailing drawdown",
        rows=[
            {"label": "Floor basis", "a": "static $90,000", "b": "trailing $95,000"},
        ],
        col_a="FTMO", col_b="FundingPips",
        footer="glitchexecutor.com",
    )
    out = hr.build_card_html(spec, hr.theme_for("glitch_executor"), 1600, 900)
    # exact strings present verbatim (the whole point — no garbling)
    assert "Same $100k account. Different floor." in out
    assert "static $90,000" in out and "trailing $95,000" in out
    assert "FundingPips" in out
    assert "#2dd4bf" in out                              # brand accent applied
    # html-escaping active
    spec2 = hr.CardSpec(headline="A & B <script>x</script>")
    out2 = hr.build_card_html(spec2, hr.theme_for("x"), 1080, 1080)
    assert "<script>" not in out2 and "&amp;" in out2


def test_bullets_branch_renders_list():
    spec = hr.CardSpec(headline="Three traps", bullets=["daily cap", "trailing DD", "consistency"])
    out = hr.build_card_html(spec, hr.theme_for("x"), 1080, 1080)
    assert out.count("<li>") == 3


def _chrome_available() -> bool:
    try:
        hr._chrome_bin()
        return True
    except hr.HtmlRenderError:
        return False


@pytest.mark.skipif(not _chrome_available(), reason="no Chrome on this box")
def test_render_card_live_produces_png(tmp_path):
    spec = hr.CardSpec(
        eyebrow="True Cost Math",
        headline="The $497 fee is the smallest line item.",
        rows=[
            {"label": "Entry fee", "a": "$497", "b": ""},
            {"label": "Expected resets", "a": "6–9", "b": ""},
            {"label": "Total to funded", "a": "$2,982–$4,473", "b": ""},
        ],
        col_a="Apex $50k", col_b="",
        footer="glitchexecutor.com",
    )
    out = hr.render_card(spec, "glitch_executor", aspect="16:9", out_dir=tmp_path)
    assert out.exists() and out.stat().st_size > 0
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"   # PNG magic
