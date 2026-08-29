"""MEDIA-1 — deterministic media-generation runner + recipe library.

Pure unit tests: a fake engine records calls and returns canned URLs, so the
whole recipe pipeline is exercised with no network.
"""
from __future__ import annotations

import re

import pytest

from glitch_signal.media.generation import (
    generate,
    get_recipe,
    list_recipes,
    recipe_for_trigger,
    run_recipe,
)
from glitch_signal.media.generation.engines.base import EngineError
from glitch_signal.media.generation.engines.muapi import MuapiEngine
from glitch_signal.media.generation.loader import RECIPE_DIR, load_all
from glitch_signal.media.generation.spec import Brief

STARTER = {
    "muapi-product-video-ad-maker",
    "muapi-ugc-video-factory",
    "muapi-instagram-post",
    "muapi-youtube-thumbnail",
}


class FakeEngine:
    """Records every generate() call; returns a deterministic fake URL."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate(self, model, prompt, *, images=None, params=None, timeout_s=360):
        self.calls.append(
            {"model": model, "prompt": prompt, "images": list(images or []), "params": dict(params or {})}
        )
        kind = "video" if "video" in model or "i2v" in model else "image"
        return f"https://fake.cdn/{model}/{len(self.calls)}.{'mp4' if kind == 'video' else 'jpg'}"


async def _echo_compose(instruction, variables):
    return f"AUTHORED::{instruction[:40]}"


# ── library integrity ────────────────────────────────────────────────
def test_all_starter_recipes_load():
    recipes = load_all()
    assert STARTER <= set(recipes), f"missing: {STARTER - set(recipes)}"
    assert {r.slug for r in list_recipes()} >= STARTER


def test_manifest_traces_to_skill_md():
    """Every engine phase's model must appear in the bundled SKILL.md — guards
    the manifest from drifting away from its source skill."""
    for recipe in list_recipes():
        if recipe.slug not in STARTER:
            continue
        skill = recipe.skill_md
        assert skill, f"{recipe.slug}: SKILL.md not bundled"
        for phase in recipe.phases:
            if phase.is_engine:
                assert phase.model in skill, f"{recipe.slug}: model {phase.model!r} not in SKILL.md"


def test_returns_is_produced_and_kinds_are_right():
    assert get_recipe("muapi-product-video-ad-maker").kind == "video"
    assert get_recipe("muapi-ugc-video-factory").kind == "video"
    assert get_recipe("muapi-instagram-post").kind == "image"
    assert get_recipe("muapi-youtube-thumbnail").kind == "image"


def test_recipe_for_trigger():
    assert recipe_for_trigger("please make me a product video ad for X").slug == "muapi-product-video-ad-maker"
    assert recipe_for_trigger("need a youtube thumbnail").slug == "muapi-youtube-thumbnail"
    assert recipe_for_trigger("nothing relevant here") is None


# ── deterministic (template-only) path — no LLM ──────────────────────
async def test_product_video_chains_two_phases_no_llm():
    eng = FakeEngine()
    recipe = get_recipe("muapi-product-video-ad-maker")
    asset = await run_recipe(
        recipe, {"product_image": "https://img/p.jpg"}, engine=eng, compose=None
    )
    assert len(eng.calls) == 2
    a, b = eng.calls
    # Phase A: image edit on the product image, default scene filled in
    assert a["model"] == "flux-2-pro-edit"
    assert a["images"] == ["https://img/p.jpg"]
    assert "fresh flowers and soft morning sunlight" in a["prompt"]  # default applied
    assert a["params"] == {"aspect_ratio": "1:1"}
    # Phase B: animate the premium image from phase A (chaining)
    assert b["model"] == "wan2.5-image-to-video-fast"
    assert b["images"] == ["https://fake.cdn/flux-2-pro-edit/1.jpg"]  # phase A output chained in
    # Asset reflects the final phase
    assert asset.kind == "video"
    assert asset.engine == "fake:wan2.5-image-to-video-fast"
    assert asset.recipe == "muapi-product-video-ad-maker"
    assert asset.url.endswith(".mp4")


async def test_scene_description_override():
    eng = FakeEngine()
    recipe = get_recipe("muapi-product-video-ad-maker")
    await run_recipe(
        recipe,
        {"product_image": "https://img/p.jpg", "scene_description": "on a marble slab"},
        engine=eng,
    )
    assert "on a marble slab" in eng.calls[0]["prompt"]
    assert "fresh flowers" not in eng.calls[0]["prompt"]


async def test_missing_required_input_raises_before_network():
    eng = FakeEngine()
    recipe = get_recipe("muapi-product-video-ad-maker")
    with pytest.raises(EngineError, match="missing required input"):
        await run_recipe(recipe, {}, engine=eng)
    assert eng.calls == []  # nothing was submitted


# ── LLM-authored prompt path ─────────────────────────────────────────
async def test_llm_phase_requires_composer():
    eng = FakeEngine()
    recipe = get_recipe("muapi-instagram-post")
    with pytest.raises(EngineError, match="LLM composer is required"):
        await run_recipe(recipe, {"brief": "summer launch"}, engine=eng, compose=None)


async def test_instagram_uses_composer_and_renders_format_param():
    eng = FakeEngine()
    recipe = get_recipe("muapi-instagram-post")
    asset = await run_recipe(
        recipe,
        {"brief": "summer coffee launch", "format": "4:5"},
        engine=eng,
        compose=_echo_compose,
    )
    assert len(eng.calls) == 1
    call = eng.calls[0]
    assert call["model"] == "nano-banana-2"
    assert call["prompt"].startswith("AUTHORED::")  # composer authored it
    assert call["params"] == {"aspect_ratio": "4:5"}  # {{format}} rendered
    assert asset.kind == "image"


async def test_ugc_full_pipeline_llm_then_two_engine_calls():
    eng = FakeEngine()
    recipe = get_recipe("muapi-ugc-video-factory")
    asset = await run_recipe(
        recipe,
        {"person": "https://img/person.jpg", "product": "https://img/prod.jpg"},
        engine=eng,
        compose=_echo_compose,
    )
    # Step 1 is llm (no engine); steps 2+3 are engine calls
    assert len(eng.calls) == 2
    hero, video = eng.calls
    assert hero["model"] == "nano-banana-pro-edit"
    assert hero["images"] == ["https://img/person.jpg", "https://img/prod.jpg"]
    assert hero["prompt"].startswith("AUTHORED::")  # step1_prompt from the llm phase
    assert video["model"] == "seedance-2-vip-image-to-video"
    assert video["images"] == ["https://fake.cdn/nano-banana-pro-edit/1.jpg"]  # hero chained in
    assert video["params"]["generate_audio"] is True
    assert asset.kind == "video"


async def test_generate_convenience_resolves_slug():
    eng = FakeEngine()
    asset = await generate(
        Brief(brand_id="glitch_executor", recipe="muapi-product-video-ad-maker",
              inputs={"product_image": "https://img/p.jpg"}),
        engine=eng,
    )
    assert asset.url.endswith(".mp4")


# ── MUapi engine wiring ──────────────────────────────────────────────
async def test_muapi_engine_requires_key(monkeypatch):
    monkeypatch.delenv("MUAPI_API_KEY", raising=False)
    eng = MuapiEngine(api_key=None)
    with pytest.raises(EngineError, match="MUAPI_API_KEY not set"):
        await eng.generate("flux-2-pro-edit", "hi")


def test_muapi_endpoint_passthrough():
    eng = MuapiEngine(api_key="x")
    assert eng._endpoint("wan2.5-image-to-video-fast") == "wan2.5-image-to-video-fast"
    assert eng._endpoint("gpt-image-2") == "gpt-image-2-text-to-image"  # alias


def test_no_placeholders_leak_in_templates():
    """Non-llm template prompts should only reference known inputs/outputs."""
    for recipe in list_recipes():
        if recipe.slug not in STARTER:
            continue
        known = {i.name for i in recipe.inputs} | {p.output for p in recipe.phases}
        for phase in recipe.phases:
            if phase.prompt_mode == "template" and phase.op != "llm":
                for ref in re.findall(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", phase.prompt):
                    assert ref in known, f"{recipe.slug}/{phase.id}: unknown placeholder {ref!r}"
