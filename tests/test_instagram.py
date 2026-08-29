"""Meta Instagram publisher (VENDOR-1) — pure/unit tests, no network."""
from __future__ import annotations

import pytest

from glitch_signal.platforms.instagram import build_container, resolve_instagram_creds


def test_build_container_image():
    url, data = build_container("ig123", "TOK", caption="hi", image_url="https://cdn/x.png")
    assert url.endswith("/ig123/media")
    assert data["image_url"] == "https://cdn/x.png"
    assert data["access_token"] == "TOK"
    assert data["caption"] == "hi"
    assert "media_type" not in data  # image containers are not REELS


def test_build_container_video_is_reel():
    _url, data = build_container("ig123", "TOK", caption="c", video_url="https://cdn/x.mp4")
    assert data["media_type"] == "REELS"
    assert data["video_url"] == "https://cdn/x.mp4"


def test_build_container_needs_media():
    with pytest.raises(ValueError, match="need image_url or video_url"):
        build_container("ig123", "TOK", caption="c")


async def test_publish_dry_run(monkeypatch):
    from glitch_signal.config import settings
    from glitch_signal.platforms.instagram import publish_instagram

    monkeypatch.setenv("DISPATCH_MODE", "dry_run")
    settings.cache_clear()
    try:
        media_id, permalink = await publish_instagram(
            brand_id="glitch_executor", caption="c", image_url="https://cdn/x.png"
        )
        assert media_id == "ig-dry-run"
    finally:
        settings.cache_clear()


def test_resolve_creds_requires_env(monkeypatch):
    for k in ("GE_META_IG_USER_ID", "GE_META_PAGE_ID", "GE_SYSTEM_USER_TOKEN",
              "META_IG_USER_ID", "META_PAGE_ID", "SYSTEM_USER_TOKEN"):  # incl. agent-wide defaults
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError, match="META_IG_USER_ID"):
        resolve_instagram_creds("glitch_executor")
