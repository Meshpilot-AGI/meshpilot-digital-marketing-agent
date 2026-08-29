"""HeyGen media engine (submit→poll) + webhook receiver (HMAC verify). No network."""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from glitch_signal.media.generation.engines.heygen import HeyGenEngine


class _Resp:
    def __init__(self, code, payload):
        self.status_code = code
        self._p = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._p


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def post(self, url, *, headers=None, json=None):
        self.calls.append(("POST", url, json))
        return self._responses.pop(0)

    async def get(self, url, *, headers=None):
        self.calls.append(("GET", url))
        return self._responses.pop(0)


# ── body mapping ──────────────────────────────────────────────────────
def test_build_body_maps_model_and_voice():
    body = HeyGenEngine._build_body("avatar_42", "hello world",
                                    {"voice_id": "vx", "aspect_ratio": "9:16"})
    assert body["avatar_id"] == "avatar_42"
    assert body["input_text"] == "hello world"
    assert body["voice"] == {"voice_id": "vx"}      # voice_id → nested voice
    assert body["aspect_ratio"] == "9:16"
    assert "voice_id" not in body


# ── submit / poll ─────────────────────────────────────────────────────
async def test_submit_returns_video_id(monkeypatch):
    monkeypatch.setenv("HEYGEN_API_KEY", "hg-test")
    eng = HeyGenEngine(poll_interval_s=0)
    c = _FakeClient([_Resp(200, {"data": {"video_id": "vid1"}})])
    assert await eng._submit(c, {"input_text": "hi"}) == "vid1"
    assert c.calls[0][1].endswith("/v3/videos")


async def test_wait_polls_until_completed(monkeypatch):
    monkeypatch.setenv("HEYGEN_API_KEY", "hg-test")
    eng = HeyGenEngine(poll_interval_s=0)
    c = _FakeClient([
        _Resp(200, {"data": {"status": "processing"}}),
        _Resp(200, {"data": {"status": "completed", "video_url": "https://cdn/v.mp4"}}),
    ])
    assert await eng._wait(c, "vid1", timeout_s=30) == "https://cdn/v.mp4"


async def test_wait_raises_on_failed(monkeypatch):
    from glitch_signal.media.generation.engines.base import EngineError
    monkeypatch.setenv("HEYGEN_API_KEY", "hg-test")
    eng = HeyGenEngine(poll_interval_s=0)
    c = _FakeClient([_Resp(200, {"data": {"status": "failed", "error": "bad avatar"}})])
    with pytest.raises(EngineError, match="failed"):
        await eng._wait(c, "vid1", timeout_s=30)


def test_missing_key_raises():
    from glitch_signal.media.generation.engines.base import EngineError
    import os
    os.environ.pop("HEYGEN_API_KEY", None)
    with pytest.raises(EngineError, match="HEYGEN_API_KEY"):
        HeyGenEngine(api_key=None)._key()


def test_engine_registry_resolves_heygen():
    from glitch_signal.media.generation.engines import get_engine
    assert get_engine("heygen").name == "heygen"
    assert get_engine("muapi").name == "muapi"


def test_build_body_prefers_params_avatar_id():
    body = HeyGenEngine._build_body("static-tag", "hi", {"avatar_id": "av_real", "voice_id": "v1"})
    assert body["avatar_id"] == "av_real"                 # params override the static model tag
    assert body["voice"] == {"voice_id": "v1"}


# A recipe may declare its engine; runner.generate resolves it (default "muapi").
def test_recipe_engine_field_defaults_to_muapi():
    from glitch_signal.media.generation import get_recipe
    assert get_recipe("muapi-cinema-director").engine == "muapi"


# ── webhook receiver ──────────────────────────────────────────────────
def _client_with_secret(monkeypatch, secret):
    from glitch_signal import config
    monkeypatch.setenv("HEYGEN_WEBHOOK_SECRET", secret)
    config.settings.cache_clear()
    from fastapi.testclient import TestClient
    from glitch_signal.server import app
    return TestClient(app)


def _post(client, body: bytes, secret: str, *, ts=None, eid="evt1", sign=True):
    ts = str(int(time.time())) if ts is None else str(ts)
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest() if sign else "deadbeef"
    return client.post("/webhooks/heygen", content=body,
                       headers={"Heygen-Signature": sig, "Heygen-Timestamp": ts,
                                "Heygen-Event-Id": eid, "content-type": "application/json"})


def test_webhook_valid_signature_200(monkeypatch):
    c = _client_with_secret(monkeypatch, "whsec_test")
    body = json.dumps({"event_type": "avatar_video.success",
                       "event_data": {"video_id": "v9"}}).encode()
    assert _post(c, body, "whsec_test").status_code == 200


def test_webhook_bad_signature_401(monkeypatch):
    c = _client_with_secret(monkeypatch, "whsec_test")
    assert _post(c, b'{"x":1}', "whsec_test", sign=False).status_code == 401


def test_webhook_stale_timestamp_400(monkeypatch):
    c = _client_with_secret(monkeypatch, "whsec_test")
    assert _post(c, b'{"x":1}', "whsec_test", ts=int(time.time()) - 10_000).status_code == 400


def test_webhook_no_secret_fails_closed_503(monkeypatch):
    c = _client_with_secret(monkeypatch, "")   # secret unset → reject
    assert _post(c, b'{"x":1}', "whatever").status_code == 503


def test_webhook_dedup_replays_ack_200(monkeypatch):
    c = _client_with_secret(monkeypatch, "whsec_test")
    body = json.dumps({"event_type": "avatar_video.success"}).encode()
    assert _post(c, body, "whsec_test", eid="dup1").status_code == 200
    assert _post(c, body, "whsec_test", eid="dup1").status_code == 200   # redelivery still 200
