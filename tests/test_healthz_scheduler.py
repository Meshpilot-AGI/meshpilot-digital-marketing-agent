"""`/healthz` carries enough for an EXTERNAL watchdog, and no more (SEO-13).

The in-app heartbeat is scheduled on the very cron it watches, so when the scheduler stopped on
2026-09-02 it stayed silent for 21 hours. These fields are what lets something outside both the cloud
and the operator's Mac ask the question instead.
"""
from __future__ import annotations

from glitch_signal import server


async def test_healthz_reports_scheduler_lag(monkeypatch):
    async def _lag():
        return {"last_run_age_s": 42, "worst_overdue_s": 0}

    monkeypatch.setattr(server, "_scheduler_lag", _lag)
    out = await server.healthz()
    assert out["status"] == "ok"
    assert out["scheduler"]["last_run_age_s"] == 42
    assert out["scheduler"]["worst_overdue_s"] == 0
    assert "cron_enabled" in out["scheduler"]


async def test_a_database_blip_does_not_make_liveness_look_down(monkeypatch):
    """Liveness and scheduler lag are different questions. Conflating them would take the service
    'down' for a monitor because a bookkeeping query failed."""
    async def _boom():
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(server, "_scheduler_lag", _boom)
    out = await server.healthz()
    assert out["status"] == "ok"
    assert "error" in out["scheduler"]


async def test_healthz_leaks_no_job_or_brand_detail(monkeypatch):
    """Unauthenticated on purpose — so it must carry integers about lag, never what is scheduled,
    for whom, or with what credentials."""
    async def _lag():
        return {"last_run_age_s": 1, "worst_overdue_s": 0}

    monkeypatch.setattr(server, "_scheduler_lag", _lag)
    out = await server.healthz()
    assert set(out["scheduler"]) <= {"cron_enabled", "last_run_age_s", "worst_overdue_s", "error"}
    assert set(out) == {"status", "service", "version", "dispatch_mode", "scheduler"}
