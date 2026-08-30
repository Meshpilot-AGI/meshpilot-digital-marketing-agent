"""ROUTER audit — primary-not-serving (fallback firing) + cost/call drift from usage_events."""
from __future__ import annotations

from glitch_signal.agent.loop import audit


class _Conn:
    def __init__(self, rows, boom=False):
        self._rows, self._boom = rows, boom

    async def execute(self, stmt, params=None):
        if self._boom:
            raise RuntimeError("db down")
        rows = self._rows

        class _R:
            def mappings(self_):
                class _M:
                    def all(self__):
                        return rows
                return _M()
        return _R()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Engine:
    def __init__(self, rows, boom=False):
        self._rows, self._boom = rows, boom

    def connect(self):
        return _Conn(self._rows, self._boom)


async def test_flags_primary_not_serving_and_drift():
    rows = [
        # complex primary (anthropic/claude-sonnet-5) absent → 0 recent; fallback glm-5.3 served
        {"model": "z-ai/glm-5.3", "recent_calls": 10, "recent_cost": 0.5, "base_calls": 5, "base_cost": 0.2},
        # haiku recent cost/call 0.10 vs baseline 0.05 → 2x drift
        {"model": "anthropic/claude-haiku-4.5", "recent_calls": 10, "recent_cost": 1.0,
         "base_calls": 10, "base_cost": 0.5},
    ]
    res = await audit.routing_audit(engine=_Engine(rows))
    types = {(f["type"], f.get("tier") or f.get("model")) for f in res["findings"]}
    assert ("primary_not_serving", "complex") in types
    assert ("cost_per_call_drift", "anthropic/claude-haiku-4.5") in types


async def test_clean_when_primary_serves_and_no_drift():
    rows = [
        {"model": "anthropic/claude-sonnet-5", "recent_calls": 20, "recent_cost": 2.0,
         "base_calls": 20, "base_cost": 2.0},
        {"model": "anthropic/claude-haiku-4.5", "recent_calls": 20, "recent_cost": 1.0,
         "base_calls": 20, "base_cost": 1.0},
    ]
    res = await audit.routing_audit(engine=_Engine(rows))
    assert res["findings"] == [] and res["summary"]["models_seen"] == 2


async def test_audit_failsoft_on_db_error():
    res = await audit.routing_audit(engine=_Engine([], boom=True))
    assert res["findings"] == [] and "error" in res["summary"]


def test_routing_audit_capability_registered():
    from glitch_signal.agent.cron import capabilities
    assert "routing_audit" in capabilities.names() and capabilities.get("routing_audit") is not None
