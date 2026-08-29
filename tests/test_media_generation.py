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

# MEDIA-2 added these 7 (ai-clipping + youtube-shorts deferred — need video-edit ops).
MEDIA2 = {
    "muapi-ad-creative",
    "muapi-cinema-director",
    "muapi-logo-creator",
    "muapi-nano-banana",
    "muapi-seedance-2",
    "muapi-social-media-video",
    "muapi-ui-design",
}
ALL_RECIPES = STARTER | MEDIA2


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


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
def test_all_recipes_load():
    recipes = load_all()
    assert ALL_RECIPES <= set(recipes), f"missing: {ALL_RECIPES - set(recipes)}"
    assert {r.slug for r in list_recipes()} >= ALL_RECIPES


def test_manifest_model_family_traces_to_skill_md():
    """Every engine phase's model FAMILY must appear in the bundled SKILL.md —
    guards against drift (using a model from a family the recipe never names).
    Some skills name only the family in prose (e.g. 'Nano Banana Pro', 'Flux',
    'Seedance 2.0'), so we match the slug's leading brand token, not the whole
    slug. All slugs are also hand-verified against muapi's live model list."""
    for recipe in list_recipes():
        skill = _norm(recipe.skill_md)
        assert skill, f"{recipe.slug}: SKILL.md not bundled"
        skill_tokens = set(skill.split())
        for phase in recipe.phases:
            if phase.is_engine:
                brand = _norm(phase.model).split()[:2]  # leading brand/family tokens
                assert any(t in skill_tokens for t in brand), (
                    f"{recipe.slug}: model {phase.model!r} family {brand} not in SKILL.md"
                )


def test_returns_is_produced_and_kinds_are_right():
    assert get_recipe("muapi-product-video-ad-maker").kind == "video"
    assert get_recipe("muapi-ugc-video-factory").kind == "video"
    assert get_recipe("muapi-instagram-post").kind == "image"
    assert get_recipe("muapi-youtube-thumbnail").kind == "image"
    # MEDIA-2
    assert get_recipe("muapi-cinema-director").kind == "video"  # video.generate
    assert get_recipe("muapi-seedance-2").kind == "video"
    assert get_recipe("muapi-social-media-video").kind == "video"  # video.from_image
    assert get_recipe("muapi-ad-creative").kind == "image"
    assert get_recipe("muapi-logo-creator").kind == "image"
    assert get_recipe("muapi-nano-banana").kind == "image"
    assert get_recipe("muapi-ui-design").kind == "image"


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


async def test_social_media_video_four_phase_chain():
    """llm(ref prompt) -> image.generate -> llm(director) -> video.from_image."""
    eng = FakeEngine()

    async def compose(instruction, variables):
        return f"COMPOSED[{instruction[:12]}]"

    asset = await run_recipe(
        get_recipe("muapi-social-media-video"),
        {"brief": "launch our cold brew", "duration": "12"},
        engine=eng,
        compose=compose,
    )
    # two engine phases: reference image, then the video from that image
    assert len(eng.calls) == 2
    ref, vid = eng.calls
    assert ref["model"] == "google-imagen4-ultra" and ref["images"] == []
    assert ref["prompt"].startswith("COMPOSED[")  # ref_image_prompt authored by llm
    assert vid["model"] == "seedance-2-image-to-video"
    assert vid["images"] == ["https://fake.cdn/google-imagen4-ultra/1.jpg"]  # chained
    assert vid["params"]["duration"] == "12"  # {{duration}} rendered in params
    assert asset.kind == "video"


async def test_cinema_director_text_to_video_no_images():
    eng = FakeEngine()

    async def compose(instruction, variables):
        return "a low-angle crane shot, golden hour"

    asset = await run_recipe(
        get_recipe("muapi-cinema-director"),
        {"subject": "a lone samurai in a blizzard"},
        engine=eng,
        compose=compose,
    )
    assert len(eng.calls) == 1
    assert eng.calls[0]["model"] == "kling-v2.5-turbo-pro-t2v"
    assert eng.calls[0]["images"] == []  # video.generate takes no reference image
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


# ── LLM composer (MEDIA-2) — text via muapi, same key ────────────────
class FakeTextEngine:
    """Fake muapi engine for the composer: returns fixed text via generate()."""

    name = "muapi"

    def __init__(self, text="AUTHORED PROMPT"):
        self._text = text
        self.calls: list[dict] = []

    async def generate(self, model, prompt, *, images=None, params=None, timeout_s=360):
        self.calls.append({"model": model, "prompt": prompt, "params": dict(params or {})})
        return self._text


async def test_llm_compose_returns_text_via_muapi():
    from glitch_signal.media.generation.compose import llm_compose

    eng = FakeTextEngine("  a punchy hero image, golden hour  ")
    out = await llm_compose("Write an Instagram image prompt for summer launch", {}, engine=eng)
    assert out == "a punchy hero image, golden hour"  # stripped
    # composer used a text model + passed a system prompt
    assert eng.calls[0]["model"]  # a text model slug
    assert "system_prompt" in eng.calls[0]["params"]


async def test_llm_compose_empty_raises():
    from glitch_signal.media.generation.compose import llm_compose

    with pytest.raises(EngineError, match="returned empty text"):
        await llm_compose("anything", {}, engine=FakeTextEngine(""))


async def test_instagram_end_to_end_with_muapi_composer():
    """Runner + composer integration: an LLM-authored recipe, all fake engines."""
    from glitch_signal.media.generation.compose import llm_compose

    text_eng = FakeTextEngine("AUTHORED IG PROMPT")
    img_eng = FakeEngine()

    async def compose(instruction, variables):
        return await llm_compose(instruction, variables, engine=text_eng)

    asset = await run_recipe(
        get_recipe("muapi-instagram-post"),
        {"brief": "summer coffee launch"},
        engine=img_eng,
        compose=compose,
    )
    assert img_eng.calls[0]["prompt"] == "AUTHORED IG PROMPT"
    assert img_eng.calls[0]["params"] == {"aspect_ratio": "1:1"}  # default format rendered
    assert asset.kind == "image"


# ── Supabase storage (STORAGE-1) ─────────────────────────────────────
class _FakeResp:
    def __init__(self, status=200, text="", headers=None, content=b""):
        self.status_code = status
        self.text = text
        self.headers = headers or {}
        self.content = content


class FakeStorageClient:
    """Fake httpx client: create-bucket + fetch-source + upload-object."""

    def __init__(self, bucket_status=200):
        self.calls: list[tuple[str, str]] = []
        self._bucket_status = bucket_status

    async def post(self, url, headers=None, json=None, content=None):
        self.calls.append(("POST", url))
        if "/storage/v1/bucket" in url:
            return _FakeResp(self._bucket_status, text="created" if self._bucket_status < 300 else "exists")
        if "/storage/v1/object/" in url:
            return _FakeResp(200, text="ok")
        return _FakeResp(404, text="?")

    async def get(self, url, headers=None):
        self.calls.append(("GET", url))
        return _FakeResp(200, headers={"content-type": "image/png"}, content=b"PNGDATA")

    async def aclose(self):
        pass


def _sb_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_x")


def test_bucket_for_derives_from_env_prefix():
    from glitch_signal.media.generation.storage import bucket_for

    assert bucket_for("glitch_executor") == "ge-media"  # env_prefix GE -> ge-media


def test_ext_for():
    from glitch_signal.media.generation.storage import _ext_for

    assert _ext_for("https://cdn/x/abc.mp4", "", "video") == "mp4"
    assert _ext_for("https://cdn/x/abc", "image/png", "image") == "png"  # from content-type
    assert _ext_for("https://cdn/x/noext", "", "video") == "mp4"  # kind fallback


async def test_persist_uploads_and_rewrites_url(monkeypatch):
    _sb_env(monkeypatch)
    from glitch_signal.media.generation.spec import Asset
    from glitch_signal.media.generation.storage import persist

    src = Asset(url="https://cdn.muapi.ai/outputs/x.png", kind="image",
                engine="muapi:nano-banana-pro", recipe="muapi-nano-banana")
    fake = FakeStorageClient()
    out = await persist(src, "glitch_executor", client=fake)

    assert out.url.startswith("https://proj.supabase.co/storage/v1/object/public/ge-media/muapi-nano-banana/")
    assert out.url.endswith(".png")
    assert out.metadata["source_url"] == "https://cdn.muapi.ai/outputs/x.png"
    assert out.metadata["bucket"] == "ge-media"
    # ensured bucket, fetched source, uploaded object
    kinds = [c[0] for c in fake.calls]
    assert kinds == ["POST", "GET", "POST"]
    assert "/storage/v1/bucket" in fake.calls[0][1]
    assert "/storage/v1/object/ge-media/" in fake.calls[2][1]


async def test_ensure_bucket_tolerates_existing(monkeypatch):
    _sb_env(monkeypatch)
    from glitch_signal.media.generation.storage import ensure_bucket

    await ensure_bucket("ge-media", client=FakeStorageClient(bucket_status=409))  # no raise


async def test_persist_requires_supabase_env(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    from glitch_signal.media.generation.spec import Asset
    from glitch_signal.media.generation.storage import persist

    with pytest.raises(EngineError, match="SUPABASE_URL / SUPABASE_SECRET_KEY not set"):
        await persist(Asset(url="x", kind="image", engine="e"), "glitch_executor",
                      client=FakeStorageClient())


def test_no_placeholders_leak_in_templates():
    """Non-llm template prompts should only reference known inputs/outputs."""
    for recipe in list_recipes():
        known = {i.name for i in recipe.inputs} | {p.output for p in recipe.phases}
        for phase in recipe.phases:
            if phase.prompt_mode == "template" and phase.op != "llm":
                for ref in re.findall(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", phase.prompt):
                    assert ref in known, f"{recipe.slug}/{phase.id}: unknown placeholder {ref!r}"
                for pval in phase.params.values():
                    if isinstance(pval, str):
                        for ref in re.findall(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", pval):
                            assert ref in known, f"{recipe.slug}/{phase.id}: unknown param placeholder {ref!r}"
