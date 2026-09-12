"""Two brands, one registry (2026-09-12). The multi-brand file path had never been exercised: GE ran
on the built-in default because `brand/configs/` did not exist."""
from __future__ import annotations

import json
import pathlib

import pytest

from glitch_signal import config

CONFIGS = pathlib.Path(__file__).resolve().parents[1] / "brand" / "configs"


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    """Point at the REAL configs dir, the way `test_brand_env.py` points at its tmp one: env var +
    `settings.cache_clear()`. `settings()` is lru_cached, so a previous test's tmp dir (acme_corp)
    leaks into this file otherwise — and this file is about the SHIPPED configs."""
    monkeypatch.setenv("BRAND_CONFIGS_DIR", str(CONFIGS))
    monkeypatch.setenv("DEFAULT_BRAND_ID", "glitch_executor")
    config.settings.cache_clear()
    config._reset_brand_registry_for_tests()
    yield
    config.settings.cache_clear()
    config._reset_brand_registry_for_tests()


def test_both_brands_are_registered_and_the_default_still_resolves():
    assert config.brand_ids() == ["ayurpet", "glitch_executor"]
    assert config.brand_config()["brand_id"] == "glitch_executor"


def test_the_ge_file_is_exactly_the_built_in_default():
    """Materialising GE's config as a file must change nothing for GE. If the built-in default ever
    moves, this catches the file drifting from it — or the reverse."""
    assert json.load(open(CONFIGS / "glitch_executor.json")) == config._default_brand_config()


def test_adding_a_brand_without_the_default_would_crash_startup(tmp_path, monkeypatch):
    """The trap: `brand/configs/` present but missing the default brand raises at load — the API
    would not start. That is why GE's file had to land in the same change as Ayurpet's."""
    (tmp_path / "ayurpet.json").write_text(json.dumps({"brand_id": "ayurpet", "env_prefix": "AP"}))
    monkeypatch.setenv("BRAND_CONFIGS_DIR", str(tmp_path))
    config.settings.cache_clear()
    with pytest.raises(RuntimeError, match="has no matching config"):
        config._load_brand_registry()


def test_ayurpet_is_isolated_and_inert():
    """Its own prefix, and no credentials — so nothing can post for it until the operator arms it."""
    assert config.brand_env_prefix("ayurpet") == "AP"
    assert config.brand_env("META_APP_ID", "ayurpet") == ""
    assert config.brand_env("BUFFER_API_KEY", "ayurpet") == ""


def test_every_config_validates_against_the_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.load(open(CONFIGS.parent / "schema" / "brand.config.schema.json"))
    for f in CONFIGS.glob("*.json"):
        jsonschema.validate(json.load(open(f)), schema)


def test_ayurpet_declares_it_cannot_use_the_git_publisher():
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
