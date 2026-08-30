"""DISCOVERY (CaptAPI) — policy gate, client, discover_trending tool."""
from __future__ import annotations

import json

import pytest

from glitch_signal.agent.discovery import captapi
from glitch_signal.agent.loop import tools
from glitch_signal.agent.loop.policy import Policy


# ── policy gate (off by default; per-run cap) ─────────────────────────
def test_discovery_denied_when_disabled():
    d = Policy(discovery_enabled=False).check("discover_trending", {}, "b")
    assert d.allow is False and "disabled" in d.reason


def test_discovery_allowed_when_enabled():
    assert Policy(discovery_enabled=True).check("discover_trending", {}, "b").allow is True


def test_discovery_per_run_cap():
    d = Policy(discovery_enabled=True, max_discovery_per_run=2).check(
        "discover_trending", {}, "b", counts={"discover_trending": 2})
    assert d.allow is False and "budget" in d.reason


# ── CaptAPI client ────────────────────────────────────────────────────
class _Resp:
    def __init__(self, code, payload):
        self.status_code = code
        self._p = payload
        self.text = str(payload)

    def json(self):
        return self._p


class _Client:
    def __init__(self, resp):
        self._resp = resp
        self.got = None

    async def get(self, url, *, params=None, headers=None):
        self.got = {"url": url, "params": params, "headers": headers}
        return self._resp


def test_endpoint_for():
    assert captapi.endpoint_for("Instagram", "reels") == "/v1/instagram/trending-reels"
    assert captapi.endpoint_for("tiktok", "feed") == "/v1/tiktok/trending-feed"
    assert captapi.endpoint_for("instagram", "bogus") is None


async def test_trending_builds_request(monkeypatch):
    monkeypatch.setenv("CAPTAPI_KEY", "capt_live_x")
    c = _Client(_Resp(200, {"success": True, "data": {"reels": [{"id": "1"}]}}))
    data = await captapi.trending("instagram", "reels", country="US", client=c)
    assert data == {"reels": [{"id": "1"}]}                       # unwraps `data`
    assert c.got["url"].endswith("/v1/instagram/trending-reels")
    assert c.got["headers"]["Authorization"] == "Bearer capt_live_x"
    assert c.got["params"] == {"cache": "true", "country": "US"}  # cache on by default


async def test_trending_unsupported_target(monkeypatch):
    monkeypatch.setenv("CAPTAPI_KEY", "capt_live_x")
    with pytest.raises(ValueError):
        await captapi.trending("instagram", "songs")             # songs is tiktok-only


# ── discover_trending tool ────────────────────────────────────────────
async def test_discover_trending_tool_compacts(monkeypatch):
    async def _fake(platform, kind, **k):
        return {"platform": "instagram", "country": "United States", "reels": [
            {"id": "1", "caption": "hi", "engagement": {"likes": 5, "comments": 1},
             "hashtags": ["a"], "videoUrl": "x", "thumbnailUrlExpiresAt": "y"}]}
    monkeypatch.setattr("glitch_signal.agent.discovery.captapi.trending", _fake)
    out = await tools._t_discover_trending({"platform": "instagram", "kind": "reels"}, "b")
    d = json.loads(out)
    assert d["platform"] == "instagram" and d["count"] == 1
    item = d["trending"][0]
    assert item["caption"] == "hi"
    assert "videoUrl" not in item and "thumbnailUrlExpiresAt" not in item   # noisy fields dropped


async def test_discover_trending_tool_error(monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr("glitch_signal.agent.discovery.captapi.trending", _boom)
    out = await tools._t_discover_trending({"platform": "instagram"}, "b")
    assert out.startswith("ERROR: discovery failed")
