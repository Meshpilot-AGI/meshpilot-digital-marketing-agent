"""Two brands, one registry (2026-09-12). The multi-brand file path had never been exercised: GE ran
on the built-in default because `brand/configs/` did not exist."""
from __future__ import annotations

import json
import pathlib

import pytest

from glitch_signal import config

CONFIGS = pathlib.Path(__file__).resolve().parents[1] / "brand" / "configs"


AYURPET = {
    "brand_id": "ayurpet", "display_name": "AyurPet", "env_prefix": "AP", "timezone": "America/New_York",
    "content_source": "ai_generated", "site_url": "https://theayurpet.com",
    "brand": {"name": "AyurPet", "accent_color": "#2e7d32", "base_color": "#fbf8f1",
              "watermark_path": None, "voice": "warm, plain-spoken"},
    "video_model_routing": {"phase": 1, "model_map": {"cinematic": "kling_2", "realistic": "kling_2",
                                                      "text_in_video": "kling_2", "fast": "kling_2"}},
    "orm_guardrails": {"hard_stop_phrases": ["cure", "FDA approved"], "competitor_names": [],
                       "auto_respond_tiers": ["positive", "neutral_faq"],
                       "review_window_seconds": {"negative_mild": 3600, "neutral_technical": 3600},
                       "escalate_tiers": ["negative_severe", "legal_flag"]},
    "platforms": {}, "default_hashtags": ["ayurpet"], "voice_prompt_path": None,
    "seo": {"publisher": "shopify", "blog_handle": "news"},
}


@pytest.fixture
def two_brands(tmp_path, monkeypatch):
    """Both brands as FILES in a tmp dir.

    ⚠️ Not the shipped `brand/configs/` — that directory is gitignored, so it exists on the
    operator's Mac and NOT on a CI runner. The first version of these tests read the shipped files,
    passed locally, and failed in the PR gate — the same fact this lane documents, biting its own
    tests. Everything here is built from `_default_brand_config()` and an inline AyurPet."""
    monkeypatch.setenv("BRAND_CONFIGS_DIR", str(tmp_path))
    monkeypatch.setenv("DEFAULT_BRAND_ID", "glitch_executor")
    monkeypatch.delenv("BRAND_CONFIGS_JSON", raising=False)
    config.settings.cache_clear()
    config._reset_brand_registry_for_tests()
    (tmp_path / "glitch_executor.json").write_text(json.dumps(config._default_brand_config()))
    (tmp_path / "ayurpet.json").write_text(json.dumps(AYURPET))
    config._reset_brand_registry_for_tests()
    yield tmp_path
    config.settings.cache_clear()
    config._reset_brand_registry_for_tests()


def test_both_brands_are_registered_and_the_default_still_resolves(two_brands):
    assert config.brand_ids() == ["ayurpet", "glitch_executor"]
    assert config.brand_config()["brand_id"] == "glitch_executor"


def test_adding_a_brand_without_the_default_would_crash_startup(tmp_path, monkeypatch):
    """The trap: `brand/configs/` present but missing the default brand raises at load — the API
    would not start. That is why GE's file had to land in the same change as Ayurpet's."""
    (tmp_path / "ayurpet.json").write_text(json.dumps({"brand_id": "ayurpet", "env_prefix": "AP"}))
    monkeypatch.setenv("BRAND_CONFIGS_DIR", str(tmp_path))
    monkeypatch.delenv("BRAND_CONFIGS_JSON", raising=False)
    config.settings.cache_clear()
    with pytest.raises(RuntimeError, match="has no matching config"):
        config._load_brand_registry()


def test_ayurpet_is_isolated_and_inert(two_brands):
    """Its own prefix, and no credentials — so nothing can post for it until the operator arms it."""
    assert config.brand_env_prefix("ayurpet") == "AP"
    assert config.brand_env("META_APP_ID", "ayurpet") == ""
    assert config.brand_env("BUFFER_API_KEY", "ayurpet") == ""


def test_the_ayurpet_config_validates_against_the_schema():
    """The schema was extended for `site_url` and `seo`; the config shape used in prod must pass it."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.load(open(CONFIGS.parent / "schema" / "brand.config.schema.json"))
    jsonschema.validate(AYURPET, schema)
    jsonschema.validate(config._default_brand_config(), schema)


def test_ayurpet_declares_it_cannot_use_the_git_publisher(two_brands):
    """Shopify store — the repo-based SEO publisher does not apply. Recorded in the config so the
    SEO lane refuses rather than tries."""
    ap = config.brand_config("ayurpet")
    assert ap["seo"]["publisher"] == "shopify"
    assert ap["site_url"].startswith("https://theayurpet.com")


# ── the path that reaches production ──
def test_configs_arrive_from_the_cloud_env(tmp_path, monkeypatch):
    """`brand/configs/*.json` is gitignored and the runtime is FastAPI Cloud, so files never reach
    prod — GE ran on the built-in default the whole time. BRAND_CONFIGS_JSON is the path that does."""
    monkeypatch.setenv("BRAND_CONFIGS_DIR", str(tmp_path))       # empty: no files, like prod
    monkeypatch.setenv("BRAND_CONFIGS_JSON", json.dumps({
        "glitch_executor": {"env_prefix": "GE", "display_name": "GE"},
        "ayurpet": {"env_prefix": "AP", "display_name": "AyurPet"},
    }))
    config.settings.cache_clear()
    config._reset_brand_registry_for_tests()
    assert config.brand_ids() == ["ayurpet", "glitch_executor"]
    assert config.brand_config("ayurpet")["brand_id"] == "ayurpet"   # stamped from the key
    assert config.brand_env_prefix("ayurpet") == "AP"


def test_env_wins_over_a_file_for_the_same_brand(tmp_path, monkeypatch):
    """Env is the source of truth for brand-scoped values — a stale local file must not shadow it."""
    (tmp_path / "glitch_executor.json").write_text(json.dumps({"env_prefix": "GE", "display_name": "from-file"}))
    monkeypatch.setenv("BRAND_CONFIGS_DIR", str(tmp_path))
    monkeypatch.setenv("BRAND_CONFIGS_JSON", json.dumps({"glitch_executor": {"env_prefix": "GE", "display_name": "from-env"}}))
    config.settings.cache_clear()
    config._reset_brand_registry_for_tests()
    assert config.brand_config("glitch_executor")["display_name"] == "from-env"


def test_malformed_env_configs_fail_loudly_at_boot(tmp_path, monkeypatch):
    """A typo in the cloud env must stop the app, not silently drop a brand."""
    monkeypatch.setenv("BRAND_CONFIGS_DIR", str(tmp_path))
    monkeypatch.setenv("BRAND_CONFIGS_JSON", "{not json")
    config.settings.cache_clear()
    with pytest.raises(RuntimeError, match="not valid JSON"):
        config._load_brand_registry()


def test_a_key_that_disagrees_with_its_brand_id_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAND_CONFIGS_DIR", str(tmp_path))
    monkeypatch.setenv("BRAND_CONFIGS_JSON", json.dumps({"ayurpet": {"brand_id": "other", "env_prefix": "AP"}}))
    config.settings.cache_clear()
    with pytest.raises(RuntimeError, match="disagrees"):
        config._load_brand_registry()
