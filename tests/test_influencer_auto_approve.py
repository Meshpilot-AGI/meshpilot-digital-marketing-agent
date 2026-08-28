"""Influencer auto-approve (hands-off approval gate) — no DB / no network.

Covers the env-config helpers, connected-persona scoping (only personas with
a Meta account get auto-approved), and that the format allow-list is forwarded
to the DB layer. The DB SQL itself is exercised live against core.influencer_
post_plan; here we stub content_plan.auto_approve to assert orchestration.
"""
import asyncio

import pytest

from glitch_signal.influencer import pipeline


def test_env_helpers(monkeypatch):
    monkeypatch.setenv("INFLUENCER_AUTO_APPROVE", "on")
    monkeypatch.setenv("INFLUENCER_AUTO_APPROVE_KEEP", "3")
    monkeypatch.setenv("INFLUENCER_AUTO_APPROVE_MAX_AGE_DAYS", "7")
    monkeypatch.setenv("INFLUENCER_AUTO_APPROVE_FORMATS", "carousel, still ,")
    assert pipeline._auto_approve_enabled() is True
    assert pipeline._auto_approve_keep() == 3
    assert pipeline._auto_approve_max_age() == 7
    assert pipeline._auto_approve_formats() == ["carousel", "still"]


def test_env_helpers_defaults(monkeypatch):
    for k in ("INFLUENCER_AUTO_APPROVE", "INFLUENCER_AUTO_APPROVE_KEEP",
              "INFLUENCER_AUTO_APPROVE_MAX_AGE_DAYS", "INFLUENCER_AUTO_APPROVE_FORMATS"):
        monkeypatch.delenv(k, raising=False)
    assert pipeline._auto_approve_enabled() is False
    assert pipeline._auto_approve_keep() == 2
    assert pipeline._auto_approve_max_age() == 5
    assert pipeline._auto_approve_formats() == []


def test_env_keep_bad_value_falls_back(monkeypatch):
    monkeypatch.setenv("INFLUENCER_AUTO_APPROVE_KEEP", "not-an-int")
    assert pipeline._auto_approve_keep() == 2


def test_tick_scopes_to_connected_personas_and_forwards_formats(monkeypatch):
    # Two brand personas; only 'connected' has a Meta account.
    monkeypatch.setattr(pipeline, "_brand_personas", lambda b: ["connected", "offline"])

    class _P:
        def __init__(self, ig):
            self.raw = {"accounts": {"meta": {"ig_user_id": ig} if ig else {}}}

    monkeypatch.setattr(
        pipeline, "load_persona",
        lambda pid, validate=True: _P("ig123" if pid == "connected" else None),
    )

    calls = []

    async def _fake_auto_approve(brand_id, persona_ids, *, keep, max_age_days, formats=None):
        calls.append((brand_id, tuple(persona_ids), keep, max_age_days, tuple(formats or [])))
        return [101] if persona_ids == ["connected"] else []

    monkeypatch.setattr(pipeline.content_plan, "auto_approve", _fake_auto_approve)

    r = asyncio.run(pipeline.auto_approve_tick(
        "ayurpet", keep=2, max_age_days=5, formats=["carousel", "still"]))

    # offline persona was filtered out → only 'connected' is asked to promote.
    assert calls == [("ayurpet", ("connected",), 2, 5, ("carousel", "still"))]
    assert r.status == "ok"
    assert "101" in r.detail


def test_tick_idle_when_no_connected_persona(monkeypatch):
    monkeypatch.setattr(pipeline, "_brand_personas", lambda b: ["offline"])

    class _P:
        raw = {"accounts": {"meta": {}}}

    monkeypatch.setattr(pipeline, "load_persona", lambda pid, validate=True: _P())
    r = asyncio.run(pipeline.auto_approve_tick("ayurpet"))
    assert r.status == "idle"
    assert "no connected personas" in r.detail
