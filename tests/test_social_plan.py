"""Brief -> route -> author. Adapted from the monorepo's content_router.

The previous pipeline had none of this: it sent `f"{angle}: {hook}"` straight to a photorealism
model, so the model had no art direction and the renderer was hardcoded to one treatment.
"""
import pytest

from glitch_signal.agent.social import plan, technique
from glitch_signal.agent.social.spec import Idea

VOICE = plan.BrandVoice(style="editorial", palette="near-black + green",
                        banned_imagery="stock traders, candlestick charts",
                        prohibited=("guaranteed", "get funded", "payout"), wordmark="ge.com")


def _idea(kind="statement"):
    return Idea(angle="rule mechanics: drawdown", hook="The floor moves up with you",
                key_points=["one", "two"], dedup_key="k1", asset_kind=kind)


# ── routing: the CONTENT picks the renderer ─────────────────────────────────────────────────────
def test_structured_kinds_route_to_deterministic_cards():
    for kind in ("comparison", "definition", "numbered", "mechanism", "statement"):
        assert plan.route_for(kind) == "card"


def test_conceptual_kinds_route_to_the_image_model():
    assert plan.route_for("concept") == "image"
    assert plan.route_for("poster") == "poster"
    assert plan.route_for("video") == "video"


def test_unknown_kind_is_skipped_not_defaulted():
    """A kind we do not understand must not silently render as the default treatment."""
    assert plan.route_for("interpretive dance") == "skip"


def test_asset_kind_maps_to_its_card_layout():
    assert plan.layout_for("comparison") == "comparison"
    assert plan.layout_for("glossary") == "definition"
    assert plan.layout_for("checklist") == "numbered"
    assert plan.layout_for("whatever") == "statement"


# ── authoring: a LOOSE idea becomes a refined, art-directed brief ───────────────────────────────
async def test_image_route_refines_the_brief_with_brand_art_direction():
    async def complete(prompt, **k):
        assert "BRAND POSITIONING" in prompt          # the doc is what refines it
        return '{"subject": "A steel ratchet whose pawl only ever climbs."}'

    p = await plan.plan_asset(_idea("concept"), asset_kind="concept", platform="instagram",
                              voice=VOICE, positioning="never show traders", complete=complete)
    assert p.route == "image"
    assert "steel ratchet" in p.prompt
    assert "editorial" in p.prompt and "near-black + green" in p.prompt
    assert "stock traders" in p.prompt                # banned imagery reaches the model
    assert p.aspect == "4:5"


async def test_illustrative_route_forbids_model_rendered_text():
    """Copy on the illustrative route lives in the caption, so the model must not invent any."""
    async def complete(prompt, **k):
        return '{"subject": "a ratchet"}'
    p = await plan.plan_asset(_idea("concept"), asset_kind="concept", platform="x",
                              voice=VOICE, complete=complete)
    assert "Render NO text" in p.prompt


async def test_poster_route_passes_the_headline_verbatim():
    """The model may SET type but must never invent the words — the headline is supplied quoted."""
    async def complete(prompt, **k):
        return '{"subject": "a ratchet", "headline": "The floor moves up with you"}'
    p = await plan.plan_asset(_idea("poster"), asset_kind="poster", platform="instagram",
                              voice=VOICE, complete=complete)
    assert '"The floor moves up with you"' in p.prompt
    assert "Render NO text" not in p.prompt


async def test_card_route_authors_structured_fields():
    async def complete(prompt, **k):
        return ('{"kicker":"RULE MECHANICS","headline":"Two drawdowns","subhead":"s",'
                '"left_label":"Static","left_body":"a","right_label":"Trailing","right_body":"b"}')
    p = await plan.plan_asset(_idea("comparison"), asset_kind="comparison", platform="instagram",
                              voice=VOICE, complete=complete)
    assert p.route == "card" and p.layout == "comparison"
    assert p.fields["left_label"] == "Static" and p.fields["wordmark"] == "ge.com"


# ── guardrails: fail BEFORE spending ────────────────────────────────────────────────────────────
def test_find_prohibited_is_case_insensitive():
    assert plan.find_prohibited("You are GUARANTEED a Payout", VOICE.prohibited) == ["guaranteed", "payout"]


async def test_prohibited_phrase_fails_the_draft_before_generation():
    """A compliance failure must raise rather than reach a paid image call — the critic is the last
    line of defence, not the first."""
    async def complete(prompt, **k):
        return '{"subject": "a trophy for traders who get funded"}'
    with pytest.raises(plan.ComplianceError):
        await plan.plan_asset(_idea("concept"), asset_kind="concept", platform="x",
                              voice=VOICE, complete=complete)


# ── degradation: an authoring blip must not kill a campaign ─────────────────────────────────────
async def test_author_failure_falls_back_to_a_deterministic_brief():
    async def complete(prompt, **k):
        raise RuntimeError("LLM down")
    p = await plan.plan_asset(_idea("concept"), asset_kind="concept", platform="x",
                              voice=VOICE, complete=complete)
    assert p.route == "image" and "The floor moves up with you" in p.prompt


async def test_unparseable_author_output_falls_back():
    async def complete(prompt, **k):
        return "sorry, I can't do that"
    p = await plan.plan_asset(_idea("comparison"), asset_kind="comparison", platform="x",
                              voice=VOICE, complete=complete)
    assert p.fields["headline"] == "The floor moves up with you"


async def test_skip_route_does_no_authoring():
    calls = {"n": 0}
    async def complete(prompt, **k):
        calls["n"] += 1
        return "{}"
    p = await plan.plan_asset(_idea("x"), asset_kind="interpretive dance", platform="x",
                              voice=VOICE, complete=complete)
    assert p.route == "skip" and calls["n"] == 0


# ── brand voice comes from the brand, never hardcoded ───────────────────────────────────────────
def test_voice_loads_from_the_brands_own_row():
    v = plan.BrandVoice.from_brand(
        {"style": "brutalist", "palette": "red", "wordmark": "x.com"},
        {"prohibited": ["Guaranteed"], "banned_imagery": "clowns"})
    assert v.style == "brutalist" and v.wordmark == "x.com"
    assert v.prohibited == ("guaranteed",)            # normalised for case-insensitive matching
    assert v.banned_imagery == "clowns"


def test_voice_defaults_when_the_brand_has_nothing_set():
    v = plan.BrandVoice.from_brand(None, None)
    assert v.prohibited == () and v.style and v.palette


def test_platform_aspect_defaults():
    assert technique.aspect_for("tiktok") == "9:16"
    assert technique.aspect_for("linkedin") == "1:1"
    assert technique.aspect_for("unknown-platform") == technique.DEFAULT_ASPECT
