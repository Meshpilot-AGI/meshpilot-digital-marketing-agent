"""PIPELINE endpoints — brand-scoped auth (#95) + idempotent live-resolving schedule.

DB-touching calls (run/cron stores) are monkeypatched, so these never hit a real database.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

TOKEN = "testtok"
H = {"x-jobs-token": TOKEN}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GE_JOBS_AUTH_TOKEN", TOKEN)   # jobs-auth for the default brand
    import glitch_signal.server as srv
    return TestClient(srv.app)


# ── #1: the run targets the AUTHORIZED (query) brand, never the body brand ──
def test_manual_pipeline_uses_query_brand_not_body(client, monkeypatch):
    captured: dict = {}

    async def _fake_create_run(run_id, brand, goal):
        captured["brand"] = brand

    async def _fake_bg(*a, **k):
        return None

    monkeypatch.setattr("glitch_signal.agent.loop.runs.create_run", _fake_create_run)
    monkeypatch.setattr("glitch_signal.server._run_agent_bg", _fake_bg)

    # authorized as glitch_executor via ?brand=; body tries to smuggle another brand
    r = client.post("/internal/agent/pipeline/content?brand=glitch_executor", headers=H,
                    json={"brand": "someone_else"})
    assert r.status_code == 200, r.text
    assert captured["brand"] == "glitch_executor"      # body brand ignored → no cross-brand


def test_manual_pipeline_unknown_is_404(client):
    r = client.post("/internal/agent/pipeline/nope?brand=glitch_executor", headers=H, json={})
    assert r.status_code == 404


# ── #4: re-seeding the same pipeline updates in place (no unique-index 500) ──
def _set_cron(monkeypatch, enabled: bool):
    """Override only agent_cron_enabled — proxy every other attr to the real settings so the
    rate-limit middleware et al. still work."""
    from glitch_signal.config import settings as _settings_fn
    real = _settings_fn()

    class _Over:
        def __getattr__(self, k):
            return enabled if k == "agent_cron_enabled" else getattr(real, k)

    monkeypatch.setattr("glitch_signal.config.settings", lambda: _Over())


def _enable_cron(monkeypatch):
    _set_cron(monkeypatch, True)


def test_schedule_seeds_pipelineTurn_with_name_only(client, monkeypatch):
    _enable_cron(monkeypatch)
    calls: dict = {}

    async def _list_jobs(brand, *, owner=None, engine=None):
        return []                                       # nothing seeded yet

    async def _create_job(**kw):
        calls["create"] = kw
        return "job-1"

    monkeypatch.setattr("glitch_signal.agent.cron.store.list_jobs", _list_jobs)
    monkeypatch.setattr("glitch_signal.agent.cron.store.create_job", _create_job)

    r = client.post("/internal/agent/pipeline/content/schedule?brand=glitch_executor", headers=H, json={})
    assert r.status_code == 200, r.text
    assert r.json()["created"] is True
    assert calls["create"]["payload_kind"] == "pipelineTurn"
    assert calls["create"]["payload"] == {"pipeline": "content"}   # NAME only, no frozen goal/scope


def test_schedule_reseed_updates_in_place(client, monkeypatch):
    _enable_cron(monkeypatch)
    calls: dict = {}

    async def _list_jobs(brand, *, owner=None, engine=None):
        return [{"id": "job-1", "name": "pipeline:content"}]        # already seeded

    async def _update_job(job_id, patch, *, now, brand_id=None, engine=None):
        calls["update"] = (job_id, patch)
        return {"id": job_id}

    async def _create_job(**kw):
        calls["create"] = kw                            # must NOT be called on re-seed
        return "job-2"

    monkeypatch.setattr("glitch_signal.agent.cron.store.list_jobs", _list_jobs)
    monkeypatch.setattr("glitch_signal.agent.cron.store.update_job", _update_job)
    monkeypatch.setattr("glitch_signal.agent.cron.store.create_job", _create_job)

    r = client.post("/internal/agent/pipeline/content/schedule?brand=glitch_executor", headers=H, json={})
    assert r.status_code == 200, r.text
    assert r.json()["created"] is False
    assert calls["update"][0] == "job-1" and calls["update"][1]["enabled"] is True
    assert "create" not in calls                        # idempotent — no duplicate insert


def test_schedule_gated_off_is_409(client, monkeypatch):
    _set_cron(monkeypatch, False)
    r = client.post("/internal/agent/pipeline/content/schedule?brand=glitch_executor", headers=H, json={})
    assert r.status_code == 409
