"""Internal control-surface — brand-scoped auth (#95 / BFLA).

`_require_jobs_auth` validates the x-jobs-token against the brand in the `?brand=` query param
(default brand when absent). These tests prove the body `brand` can NOT override that authorized
query brand on the remaining /internal|/jobs handlers that used to read `body.get("brand")`
(the PIPELINE endpoints were fixed earlier). A caller holding the default brand's token — or any
brand's token with no `?brand=` — must not be able to start actions for another brand by naming it
in the request body.

DB-touching calls (memory / run / cron stores) are monkeypatched, so these never hit a real
database. (This machine's local `.env` points at the real Supabase.)
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

TOKEN = "testtok"
H = {"x-jobs-token": TOKEN}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GE_JOBS_AUTH_TOKEN", TOKEN)   # jobs-auth for the default brand (glitch_executor)
    import glitch_signal.server as srv
    return TestClient(srv.app)


# ── /internal/agent/remember — a memory WRITE must land on the authorized brand only ──
class _FakeMem:
    id, kind, key = "m1", "fact", None


def _patch_remember(monkeypatch, captured):
    async def _fake_remember(brand, kind, content, **kw):
        captured["brand"] = brand
        return _FakeMem()

    monkeypatch.setattr("glitch_signal.agent.memory.remember", _fake_remember)


def test_remember_body_brand_cannot_override_default(client, monkeypatch):
    """No ?brand= (authorized = default) + a smuggled body brand → 400, nothing written."""
    captured: dict = {}
    _patch_remember(monkeypatch, captured)
    r = client.post("/internal/agent/remember", headers=H,
                    json={"brand": "someone_else", "kind": "fact", "content": "x"})
    assert r.status_code == 400, r.text
    assert "brand" not in captured                      # remember() never ran → no cross-brand write


def test_remember_body_brand_cannot_override_query(client, monkeypatch):
    """?brand=glitch_executor + a differing body brand → 400, nothing written."""
    captured: dict = {}
    _patch_remember(monkeypatch, captured)
    r = client.post("/internal/agent/remember?brand=glitch_executor", headers=H,
                    json={"brand": "someone_else", "kind": "fact", "content": "x"})
    assert r.status_code == 400, r.text
    assert "brand" not in captured


def test_remember_writes_authorized_brand(client, monkeypatch):
    """No brand in body → the authorized (default) brand is used — behavior unchanged."""
    captured: dict = {}
    _patch_remember(monkeypatch, captured)
    r = client.post("/internal/agent/remember", headers=H,
                    json={"kind": "fact", "content": "x"})
    assert r.status_code == 200, r.text
    assert captured["brand"] == "glitch_executor"


def test_remember_matching_body_brand_ok(client, monkeypatch):
    """A body brand equal to the authorized query brand is accepted (no false 400)."""
    captured: dict = {}
    _patch_remember(monkeypatch, captured)
    r = client.post("/internal/agent/remember?brand=glitch_executor", headers=H,
                    json={"brand": "glitch_executor", "kind": "fact", "content": "x"})
    assert r.status_code == 200, r.text
    assert captured["brand"] == "glitch_executor"


# ── /internal/agent/run — starting an agent loop must target the authorized brand only ──
def _patch_run(monkeypatch, captured):
    async def _fake_create_run(run_id, brand, goal):
        captured["brand"] = brand

    async def _fake_bg(*a, **k):
        return None

    monkeypatch.setattr("glitch_signal.agent.loop.runs.create_run", _fake_create_run)
    monkeypatch.setattr("glitch_signal.server._run_agent_bg", _fake_bg)


def test_run_body_brand_cannot_override(client, monkeypatch):
    captured: dict = {}
    _patch_run(monkeypatch, captured)
    r = client.post("/internal/agent/run", headers=H,
                    json={"brand": "someone_else", "goal": "do a thing"})
    assert r.status_code == 400, r.text
    assert "brand" not in captured                      # the background run never started


def test_run_uses_authorized_brand(client, monkeypatch):
    captured: dict = {}
    _patch_run(monkeypatch, captured)
    r = client.post("/internal/agent/run", headers=H, json={"goal": "do a thing"})
    assert r.status_code == 200, r.text
    assert captured["brand"] == "glitch_executor"


# ── /internal/cron/jobs — persistent state (a scheduled job) must be brand-scoped too ──
def test_cron_create_body_brand_cannot_override(client, monkeypatch):
    captured: dict = {}

    async def _fake_create_job(**kw):
        captured["brand"] = kw.get("brand_id")
        return "job1"

    monkeypatch.setattr("glitch_signal.agent.cron.store.create_job", _fake_create_job)
    r = client.post("/internal/cron/jobs", headers=H, json={
        "brand": "someone_else", "name": "j", "schedule_kind": "every",
        "schedule": {"every_ms": 1000}, "payload_kind": "agentTurn",
    })
    assert r.status_code == 400, r.text
    assert "brand" not in captured                      # no job created against another brand
