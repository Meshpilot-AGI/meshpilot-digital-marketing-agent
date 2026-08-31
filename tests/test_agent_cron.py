"""AGENT-CRON — self-cron: schedule math, store claim/finish, self-scoped tool, capabilities."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from glitch_signal.agent.cron import capabilities, schedule as sched, service, store
from glitch_signal.agent.cron import runctx
from glitch_signal.agent.cron import tool as cron_tool

NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)


# ── schedule math (pure) ──
def test_compute_first_run_at_parses_iso():
    got = sched.compute_first_run({"at": "2026-09-01T16:00:00Z"}, "at", now=NOW)
    assert got == datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)


def test_compute_next_at_is_none():
    assert sched.compute_next({"at": "2026-09-01T16:00:00Z"}, "at", now=NOW) is None


def test_compute_next_every_advances_without_drift():
    # anchor 2 min before now, 5-min interval → next is anchor+5m (strictly after now), no drift
    anchor = NOW - timedelta(minutes=2)
    nxt = sched.compute_next({"every_ms": 300_000, "anchor_ms": int(anchor.timestamp() * 1000)}, "every", now=NOW)
    assert nxt == anchor + timedelta(minutes=5)


def test_compute_next_cron_in_tz():
    # 9am daily in New York → next occurrence is a real future instant
    nxt = sched.compute_next({"cron_expr": "0 9 * * *", "tz": "America/New_York"}, "cron", now=NOW)
    assert nxt > NOW and nxt.tzinfo is not None


def test_validate_rejects_bad_cron():
    with pytest.raises(ValueError):
        sched.validate({"cron_expr": "not a cron"}, "cron")


def test_validate_rejects_bad_tz():
    with pytest.raises(Exception):
        sched.validate({"cron_expr": "0 9 * * *", "tz": "Mars/Olympus"}, "cron")


# ── fake engine (no DB) ──
class _FakeResult:
    def __init__(self, rows, first):
        self._rows, self._first = rows, first

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._first


class _FakeConn:
    def __init__(self, sink, rows, first):
        self._sink, self._rows, self._first = sink, rows, first

    async def execute(self, stmt, params=None):
        self._sink.append((str(stmt), params))
        return _FakeResult(self._rows, self._first)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeEngine:
    def __init__(self, rows=None, first=None):
        self.calls = []
        self._rows, self._first = rows or [], first

    def begin(self):
        return _FakeConn(self.calls, self._rows, self._first)

    def connect(self):
        return _FakeConn(self.calls, self._rows, self._first)


# ── store ──
async def test_create_job_computes_next_run_and_inserts():
    eng = _FakeEngine(first={"id": "job-1"})
    jid = await store.create_job(
        brand_id="glitch_executor", name="nightly-curate", schedule_kind="every",
        schedule={"every_ms": 3_600_000}, payload_kind="capability",
        payload={"name": "curate"}, now=NOW, engine=eng)
    assert jid == "job-1"
    stmt, params = eng.calls[0]
    assert "insert into scheduled_jobs" in stmt.lower()
    assert params["brand_id"] == "glitch_executor" and params["payload_kind"] == "capability"
    assert params["next_run_at"] == NOW  # anchorless every fires now


async def test_claim_due_advances_and_opens_run():
    job = {"id": "job-1", "brand_id": "glitch_executor", "name": "n", "owner": "operator",
           "schedule_kind": "every", "schedule": {"every_ms": 120_000}, "payload_kind": "capability",
           "payload": {"name": "curate"}, "delete_after_run": False, "pacing": {}}
    eng = _FakeEngine(rows=[job])
    claimed = await store.claim_due(NOW, 10, engine=eng)
    assert len(claimed) == 1 and claimed[0]["run_id"]
    kinds = " ".join(s.lower() for s, _ in eng.calls)
    assert "for update skip locked" in kinds
    assert "update scheduled_jobs set next_run_at" in kinds   # advanced
    assert "insert into scheduled_runs" in kinds              # run opened


async def test_claim_due_spends_one_shot():
    job = {"id": "j2", "brand_id": "b", "name": "n", "owner": "operator", "schedule_kind": "at",
           "schedule": {"at": "2026-08-29T12:00:00Z"}, "payload_kind": "agentTurn",
           "payload": {"goal": "hi"}, "delete_after_run": True, "pacing": {}}
    eng = _FakeEngine(rows=[job])
    await store.claim_due(NOW, 10, engine=eng)
    joined = " ".join(s.lower() for s, _ in eng.calls)
    assert "next_run_at=null, enabled=false" in joined  # one-shot spent, not advanced


async def test_finish_run_success_resets_and_deletes_one_shot():
    eng = _FakeEngine()
    await store.finish_run("run-1", "job-1", status="done", result={"run_id": "x"},
                           delete_after_run=True, engine=eng)
    joined = " ".join(s.lower() for s, _ in eng.calls)
    assert "set fail_count=0" in joined            # success resets streak
    assert "delete from scheduled_jobs" in joined  # one-shot cleaned up


async def test_finish_run_error_increments_and_may_disable():
    eng = _FakeEngine()
    await store.finish_run("run-1", "job-1", status="error", error="boom", max_failures=3, engine=eng)
    joined = " ".join(s.lower() for s, _ in eng.calls)
    assert "fail_count=fail_count+1" in joined


async def test_delete_job_scoped_requires_owner_match():
    eng = _FakeEngine(first=None)  # scoped delete returns no row → not owned
    ok = await store.delete_job("job-1", owner="agent:glitch_executor", engine=eng)
    assert ok is False
    assert "and owner=:owner" in eng.calls[0][0].lower()


# ── capabilities ──
def test_capability_registry():
    assert set(capabilities.names()) == {"curate", "drive_scout", "reconcile", "routing_audit", "social_campaign"}
    assert capabilities.get("nope") is None


async def test_reconcile_capability_dispatches_to_reconcile(monkeypatch):
    # INC-2 filled the hook: reconcile now runs the balance-delta reconciliation.
    from glitch_signal.analytics.cost import reconcile

    async def _run(vendors=None):
        return {"vendors": [], "dispatched": True}
    monkeypatch.setattr(reconcile, "run", _run)
    out = await capabilities.get("reconcile")("glitch_executor", {})
    assert out["dispatched"] is True


# ── service ──
async def test_sweep_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(service, "_enabled", lambda: False)
    assert await service.sweep(now=NOW) == 0


async def test_run_capability_unknown_raises():
    with pytest.raises(ValueError):
        await service._run_capability("b", {"name": "does-not-exist"})


async def test_run_agent_turn_requires_goal():
    with pytest.raises(ValueError):
        await service._run_agent_turn("b", {"goal": "  "})


# ── self-scoped tool ──
async def test_tool_create_denied_when_kill_switch_off(monkeypatch):
    monkeypatch.setattr(cron_tool, "_cron_enabled", lambda: False)
    out = await cron_tool.schedule_tool({"action": "create", "name": "x"}, "glitch_executor")
    assert "disabled" in out


async def test_tool_create_enforces_creator_cap(monkeypatch):
    monkeypatch.setattr(cron_tool, "_cron_enabled", lambda: True)
    monkeypatch.setattr(cron_tool, "_max_jobs", lambda: 2)

    async def _count(brand, owner, **kw):
        return 2
    monkeypatch.setattr(store, "count_active_owned", _count)
    out = await cron_tool.schedule_tool({"action": "create", "name": "x"}, "glitch_executor")
    assert "creator-cap" in out


async def test_tool_create_stamps_agent_owner(monkeypatch):
    monkeypatch.setattr(cron_tool, "_cron_enabled", lambda: True)

    async def _count(brand, owner, **kw):
        return 0
    seen = {}

    async def _create(**kw):
        seen.update(kw)
        return "job-9"
    monkeypatch.setattr(store, "count_active_owned", _count)
    monkeypatch.setattr(store, "create_job", _create)
    out = await cron_tool.schedule_tool({
        "action": "create", "name": "watch", "schedule_kind": "every",
        "schedule": {"every_ms": 3_600_000}, "payload_kind": "capability",
        "payload": {"name": "curate"},
    }, "glitch_executor")
    assert "job-9" in out and seen["owner"] == "agent:glitch_executor"


async def test_tool_list_is_self_scoped(monkeypatch):
    captured = {}

    async def _list(brand, *, owner=None, **kw):
        captured["owner"] = owner
        return []
    monkeypatch.setattr(store, "list_jobs", _list)
    await cron_tool.schedule_tool({"action": "list"}, "glitch_executor")
    assert captured["owner"] == "agent:glitch_executor"


async def test_tool_next_check_requires_run_context():
    runctx.current_job_id.set(None)
    out = await cron_tool.schedule_tool({"action": "next_check", "in": "30m"}, "glitch_executor")
    assert "only valid inside" in out


async def test_tool_next_check_clamps_to_pacing(monkeypatch):
    runctx.current_job_id.set("job-1")
    runctx.current_job_pacing.set({"min_ms": 3_600_000})  # floor 1h
    seen = {}

    async def _set_next(job_id, next_at, **kw):
        seen["job_id"] = job_id
        seen["next_at"] = next_at
    monkeypatch.setattr(store, "set_next_run", _set_next)
    out = await cron_tool.schedule_tool({"action": "next_check", "in": "5m"}, "glitch_executor")
    assert "next check set" in out
    # requested 5m but floor is 1h → at least ~1h out
    assert seen["next_at"] >= datetime.now(timezone.utc) + timedelta(minutes=59)


def test_parse_duration():
    assert cron_tool.parse_duration_ms("30m") == 1_800_000
    assert cron_tool.parse_duration_ms("2h") == 7_200_000
    with pytest.raises(ValueError):
        cron_tool.parse_duration_ms("soon")
