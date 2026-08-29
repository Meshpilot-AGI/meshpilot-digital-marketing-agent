"""Facebook publisher — pure payload/endpoint selection + per-brand cred resolve.

No network: `build_post` and `resolve_facebook_creds` are pure/config-only.
"""
import json

import pytest

from glitch_signal import config as cfg
from glitch_signal.platforms import facebook as fb


def _setup_brand(monkeypatch, tmp_path, brand_id="glitch_executor", env_prefix="GE"):
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / f"{brand_id}.json").write_text(json.dumps({
        "brand_id": brand_id, "display_name": brand_id, "timezone": "UTC",
        "env_prefix": env_prefix,
    }))
    monkeypatch.setenv("BRAND_CONFIGS_DIR", str(configs))
    monkeypatch.setenv("DEFAULT_BRAND_ID", brand_id)
    cfg.settings.cache_clear()
    cfg._reset_brand_registry_for_tests()


def test_build_post_text_goes_to_feed():
    url, data = fb.build_post("PAGE", "TOK", message="hello world")
    assert url.endswith("/PAGE/feed")
    assert data == {"message": "hello world", "access_token": "TOK"}


def test_build_post_text_with_link():
    url, data = fb.build_post("PAGE", "TOK", message="hi", link="https://x.io")
    assert url.endswith("/PAGE/feed")
    assert data["link"] == "https://x.io"


def test_build_post_image_goes_to_photos():
    url, data = fb.build_post("PAGE", "TOK", message="cap", image_url="https://img/a.png")
    assert url.endswith("/PAGE/photos")
    assert data == {"url": "https://img/a.png", "access_token": "TOK", "caption": "cap"}


def test_build_post_video_goes_to_videos():
    url, data = fb.build_post("PAGE", "TOK", message="desc", video_url="https://v/a.mp4")
    assert url.endswith("/PAGE/videos")
    assert data == {"file_url": "https://v/a.mp4", "access_token": "TOK", "description": "desc"}


def test_build_post_requires_content():
    with pytest.raises(ValueError):
        fb.build_post("PAGE", "TOK")


def test_resolve_creds_from_brand_env(monkeypatch, tmp_path):
    _setup_brand(monkeypatch, tmp_path)
    monkeypatch.setenv("GE_META_PAGE_ID", "12345")
    monkeypatch.setenv("GE_SYSTEM_USER_TOKEN", "sys-tok")
    assert fb.resolve_facebook_creds() == ("12345", "sys-tok")


def test_resolve_creds_raises_when_page_missing(monkeypatch, tmp_path):
    _setup_brand(monkeypatch, tmp_path)
    monkeypatch.delenv("GE_META_PAGE_ID", raising=False)
    monkeypatch.delenv("META_PAGE_ID", raising=False)  # and no agent-wide default
    monkeypatch.setenv("GE_SYSTEM_USER_TOKEN", "sys-tok")
    with pytest.raises(RuntimeError):
        fb.resolve_facebook_creds()
