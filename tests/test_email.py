"""EMAIL-1 — Resend send path, the policy gate, and the /resend/webhook receiver. No network."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest


@pytest.fixture(autouse=True)
def _reset_caches():
    from glitch_signal import config as cfg
    cfg._reset_brand_registry_for_tests()
    cfg.settings.cache_clear()
    yield
    cfg.settings.cache_clear()


# ── policy gate ───────────────────────────────────────────────────────
def test_gate_denies_send_email_when_disabled():
    from glitch_signal.agent.loop.policy import Policy
    d = Policy(email_enabled=False).check("send_email", {}, "b")
    assert d.allow is False and "email" in d.reason.lower()


def test_gate_allows_send_email_when_enabled_within_cap():
    from glitch_signal.agent.loop.policy import Policy
    d = Policy(email_enabled=True, max_emails_per_run=3).check("send_email", {}, "b", counts={"send_email": 1})
    assert d.allow is True


def test_gate_enforces_per_run_email_cap():
    from glitch_signal.agent.loop.policy import Policy
    d = Policy(email_enabled=True, max_emails_per_run=2).check("send_email", {}, "b", counts={"send_email": 2})
    assert d.allow is False and "budget" in d.reason.lower()


def test_from_config_email_off_by_default():
    from glitch_signal.agent.loop.policy import from_config
    assert from_config().email_enabled is False


# ── send path ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_send_email_dry_run_returns_mock_id(monkeypatch):
    monkeypatch.setenv("DISPATCH_MODE", "dry_run")
    monkeypatch.setenv("RESEND_FROM", "agent@meshpilot.app")
    from glitch_signal import config as cfg
    cfg.settings.cache_clear()
    from glitch_signal.comms import email
    rid = await email.send_email(brand_id="glitch_executor", to="x@example.com", subject="hi", text="hello")
    assert rid.startswith("email-dry-")


@pytest.mark.asyncio
async def test_send_email_requires_recipient_and_body(monkeypatch):
    monkeypatch.setenv("DISPATCH_MODE", "dry_run")
    monkeypatch.setenv("RESEND_FROM", "agent@meshpilot.app")
    from glitch_signal import config as cfg
    cfg.settings.cache_clear()
    from glitch_signal.comms import email
    with pytest.raises(RuntimeError):
        await email.send_email(brand_id="glitch_executor", to="", subject="s", text="t")
    with pytest.raises(RuntimeError):
        await email.send_email(brand_id="glitch_executor", to="x@example.com", subject="s")  # no body


@pytest.mark.asyncio
async def test_send_email_requires_from(monkeypatch):
    monkeypatch.setenv("DISPATCH_MODE", "dry_run")
    monkeypatch.delenv("RESEND_FROM", raising=False)
    from glitch_signal import config as cfg
    cfg.settings.cache_clear()
    from glitch_signal.comms import email
    with pytest.raises(RuntimeError, match="From"):
        await email.send_email(brand_id="glitch_executor", to="x@example.com", subject="s", text="t")


@pytest.mark.asyncio
async def test_send_email_applies_content_policy_and_calls_resend(monkeypatch):
    # Live path (not dry-run): resend is monkeypatched to capture params.
    monkeypatch.setenv("DISPATCH_MODE", "live")
    monkeypatch.setenv("RESEND_FROM", "agent@meshpilot.app")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    from glitch_signal import config as cfg
    cfg.settings.cache_clear()

    import resend
    captured = {}
    monkeypatch.setattr(resend.Emails, "send", lambda params: captured.update(params) or {"id": "re_123"})

    from glitch_signal.comms import email
    # em-dash in subject must be stripped by the content policy before sending
    rid = await email.send_email(brand_id="glitch_executor", to="x@example.com",
                                 subject="Big news — today", html="<p>hi — there</p>")
    assert rid == "re_123"
    assert "—" not in captured["subject"] and "—" not in captured["html"]
    assert captured["from"] == "agent@meshpilot.app"
    assert captured["to"] == ["x@example.com"]


@pytest.mark.asyncio
async def test_send_email_daily_cap_denies(monkeypatch):
    monkeypatch.setenv("DISPATCH_MODE", "dry_run")
    monkeypatch.setenv("RESEND_FROM", "agent@meshpilot.app")
    from glitch_signal import config as cfg
    cfg.settings.cache_clear()
    # Force the shared limiter to report "over cap".
    import glitch_signal.middleware.shared_state as ss

    class _Full:
        def __init__(self, *a, **k): ...
        async def check(self, key): return (False, 60)
    monkeypatch.setattr(ss, "SharedWindowLimiter", _Full)

    from glitch_signal.comms import email
    with pytest.raises(RuntimeError, match="cap"):
        await email.send_email(brand_id="glitch_executor", to="x@example.com", subject="s", text="t")


# ── /resend/webhook (Svix signature) ──────────────────────────────────
_KEY = b"resend-test-signing-key-bytes-01"
_SECRET = "whsec_" + base64.b64encode(_KEY).decode()


def _client(monkeypatch, secret):
    from glitch_signal import config
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", secret)
    config.settings.cache_clear()
    from fastapi.testclient import TestClient

    from glitch_signal.server import app
    return TestClient(app)


def _sig(svix_id, ts, body):
    signed = f"{svix_id}.{ts}.".encode() + body
    return "v1," + base64.b64encode(hmac.new(_KEY, signed, hashlib.sha256).digest()).decode()


def _post(client, body, *, svix_id="msg_1", ts=None, sig=None):
    ts = str(ts if ts is not None else int(time.time()))
    sig = sig if sig is not None else _sig(svix_id, ts, body)
    return client.post("/resend/webhook", content=body,
                       headers={"svix-id": svix_id, "svix-timestamp": ts,
                                "svix-signature": sig, "content-type": "application/json"})


def test_resend_webhook_valid_signature_200(monkeypatch):
    c = _client(monkeypatch, _SECRET)
    body = json.dumps({"type": "email.delivered", "data": {"email_id": "e1", "to": ["x@y.com"]}}).encode()
    assert _post(c, body).status_code == 200


def test_resend_webhook_bad_signature_401(monkeypatch):
    c = _client(monkeypatch, _SECRET)
    assert _post(c, b'{"type":"email.bounced"}', sig="v1,not-the-right-signature").status_code == 401


def test_resend_webhook_missing_headers_400(monkeypatch):
    c = _client(monkeypatch, _SECRET)
    r = c.post("/resend/webhook", content=b'{}', headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_resend_webhook_stale_timestamp_400(monkeypatch):
    c = _client(monkeypatch, _SECRET)
    assert _post(c, b'{"type":"email.opened"}', ts=int(time.time()) - 10_000).status_code == 400


def test_resend_webhook_no_secret_fails_closed_503(monkeypatch):
    c = _client(monkeypatch, "")
    assert _post(c, b'{"type":"email.delivered"}').status_code == 503
