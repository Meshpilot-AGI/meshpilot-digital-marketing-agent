"""Issue #195: the self-scheduling scope clamp only covered `agentTurn`.

A `chat`-scoped run could self-schedule a `capability` or `pipelineTurn` job that fires later with
powers the creating run never held — widening the agent's own powers across time, which is exactly
what the clamp exists to prevent.
"""
import pytest

from glitch_signal.agent.cron import store
from glitch_signal.agent.cron import tool as cron_tool
from glitch_signal.agent.loop import scopes


@pytest.fixture
def _creatable(monkeypatch):
    """Let `create` reach the scope check: kill-switch on, cap clear, store stubbed."""
    created: dict = {}

    async def _count(brand, owner, **kw):
        return 0

    async def _create(**kw):
        created.update(kw)
        return "job-1"

    monkeypatch.setattr(cron_tool, "_cron_enabled", lambda: True)
    monkeypatch.setattr(store, "count_active_owned", _count)
    monkeypatch.setattr(store, "create_job", _create)
    return created


async def _create(payload_kind, payload):
    return await cron_tool.schedule_tool({
        "action": "create", "name": "j", "schedule_kind": "every",
        "schedule": {"every_ms": 3_600_000},
        "payload_kind": payload_kind, "payload": payload,
    }, "glitch_executor")


async def test_chat_run_cannot_schedule_a_paid_publishing_capability(_creatable):
    """`social_campaign` needs media + publish; `chat` (the default) grants neither."""
    scopes.set_current("chat")
    out = await _create("capability", {"name": "social_campaign"})
    assert "ERROR" in out and "scope escalation" in out
    assert not _creatable                       # the job was never created


async def test_full_run_can_schedule_a_paid_publishing_capability(_creatable):
    scopes.set_current("full")
    out = await _create("capability", {"name": "social_campaign"})
    assert "job-1" in out and _creatable["payload_kind"] == "capability"


async def test_read_only_capability_is_allowed_from_chat(_creatable):
    """Containment must not become a blanket ban — bookkeeping grants no new powers."""
    scopes.set_current("chat")
    out = await _create("capability", {"name": "routing_audit"})
    assert "job-1" in out


async def test_unknown_capability_is_refused_not_waved_through(_creatable):
    scopes.set_current("full")
    out = await _create("capability", {"name": "definitely_not_real"})
    assert "ERROR" in out and "unknown capability" in out
    assert not _creatable


async def test_chat_run_cannot_prearm_a_web_scoped_pipeline(_creatable):
    """The concrete escalation from the issue: pre-arm `discovery` (web) from a chat run so it
    starts running web tools the moment the operator flips the switch."""
    scopes.set_current("chat")
    out = await _create("pipelineTurn", {"pipeline": "discovery"})
    assert "ERROR" in out and "scope escalation" in out
    assert not _creatable


async def test_pipeline_within_scope_is_allowed(_creatable):
    scopes.set_current("full")
    out = await _create("pipelineTurn", {"pipeline": "discovery"})
    assert "job-1" in out


async def test_unknown_pipeline_is_refused(_creatable):
    scopes.set_current("full")
    out = await _create("pipelineTurn", {"pipeline": "nope"})
    assert "ERROR" in out and "unknown pipeline" in out


async def test_agent_turn_is_still_clamped_down_rather_than_refused(_creatable):
    """An agentTurn carries a scope name, so it can be narrowed in place — the job still runs."""
    scopes.set_current("chat")
    out = await _create("agentTurn", {"goal": "g", "scope": "full"})
    assert "job-1" in out
    assert _creatable["payload"]["scope"] == "chat"


async def test_unknown_payload_kind_is_refused(_creatable):
    scopes.set_current("full")
    out = await _create("nonsense", {})
    assert "ERROR" in out and "unknown payload_kind" in out


def test_unknown_capability_requires_everything():
    """Fail closed: a name we don't recognise must not pass containment by default."""
    assert cron_tool.capabilities.required_capabilities("nope") == frozenset(scopes.CAPABILITIES)
