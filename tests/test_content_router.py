"""GROW-SOCIAL-RENDER-4 — brief→route→author (LLM injected; no network)."""
import json

import pytest

from glitch_signal.media import content_router as cr
from glitch_signal.media.html_render import CardSpec


def test_route_for():
    assert cr.route_for("screenshot") == "text_card"
    assert cr.route_for("table") == "text_card"
    assert cr.route_for("hero") == "illustrative_image"
    assert cr.route_for("video_script") == "video"
    assert cr.route_for("none") == "skip"


def _fake_llm(payload: dict):
    return lambda prompt, system: "```json\n" + json.dumps(payload) + "\n```"


def test_author_card_spec_parses_llm_json():
    spec = cr.author_card_spec(
        hook="The daily loss limit busts more accounts than max drawdown",
        notes="2-col table FTMO vs FundingPips",
        voice=cr.BrandVoice(disclaimer="Educational only. Trading involves risk.", footer="glitchexecutor.com"),
        complete_fn=_fake_llm({
            "eyebrow": "RULE TRAP",
            "headline": "The daily cap kills more accounts.",
            "subhead": "It resets every morning.",
            "rows": [{"label": "Resets", "a": "daily", "b": "once"}],
            "col_a": "Daily cap", "col_b": "Max DD",
        }),
    )
    assert isinstance(spec, CardSpec)
    assert spec.eyebrow == "RULE TRAP"
    assert spec.rows[0]["a"] == "daily"
    # disclaimer forced into footer, original footer kept
    assert "glitchexecutor.com" in spec.footer and "Educational only" in spec.footer


def test_author_card_spec_compliance_blocks_profit_claims():
    with pytest.raises(cr.ComplianceError):
        cr.author_card_spec(
            hook="x",
            complete_fn=_fake_llm({"headline": "Guaranteed risk-free returns"}),
        )


def test_author_card_spec_falls_back_on_bad_json():
    spec = cr.author_card_spec(
        hook="My headline", notes="some note",
        complete_fn=lambda p, s: "not json at all",
    )
    assert spec.headline == "My headline"     # deterministic fallback
    assert spec.subhead == "some note"


def test_plan_asset_text_card_routes_and_authors():
    plan = cr.plan_asset(
        hook="Same $100k account, different floor", notes="comparison", platform="x",
        asset_kind="screenshot",
        complete_fn=_fake_llm({"headline": "Same $100k account, different floor"}),
    )
    assert plan.route == "text_card" and plan.aspect == "16:9"
    assert plan.card_spec and "100k" in plan.card_spec.headline


def test_plan_asset_video_and_illustrative():
    v = cr.plan_asset(hook="prop firm hook", platform="tiktok", asset_kind="hook")
    assert v.route == "video" and v.aspect == "9:16" and v.video_prompt
    img = cr.plan_asset(hook="abstract chart", asset_kind="hero")
    assert img.route == "illustrative_image" and "no on-image text" in img.image_prompt.lower()
