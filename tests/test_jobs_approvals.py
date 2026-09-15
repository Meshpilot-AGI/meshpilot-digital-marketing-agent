"""JOBS-5 acceptance — the approval gate.

Design § 10 requires: a card posted, all four reactions read back correctly, and expiry != approval.
Discord is faked here; the operator's real channel/user ids are not yet configured, so the network
half is unverified and says so in the lane's supervisor entry.
"""
from __future__ import annotations

import pytest

from glitch_signal.agent.jobs import approvals

BRAND = "tejas"
APPROVER = "111111111111111111"
STRANGER = "999999999999999999"

CFG = {"jobs": {"approvals_channel_id": "222", "approvers": [APPROVER], "offer_ttl_hours": 48}}

APP = {"company": "Acme", "title": "Performance Marketing Manager", "location": "Toronto, ON",
       "canonical_url": "https://job-boards.greenhouse.io/acme/jobs/1", "score": 4.3,
       "work_auth": "not_needed", "score_parts": {"requirements": 12, "critical": 4, "strong": 9, "none": 1},
       "answers": {"Are you legally authorized to work in Canada?": "Yes"},
       "tailored_cv": "# CV\n- Led a ~$30K/day account"}


@pytest.fixture(autouse=True)
def _brand_cfg(monkeypatch):
    import glitch_signal.config as cfgmod

    monkeypatch.setattr(cfgmod, "brand_config", lambda b=None: CFG)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")


def _fake_api(reactions, users_by_emoji):
    async def api(method, path, token, *, json_body=None):
        if method == "POST":
            return {"id": "msg-1"}
        if method == "PUT":
            return {}
        if "/reactions/" in path:
            for emoji, users in users_by_emoji.items():
                from urllib.parse import quote
                if quote(emoji) in path:
                    return [{"id": u} for u in users]
            return []
        return {"reactions": reactions}
    return api


# --- the card -------------------------------------------------------------------------

def test_card_shows_everything_that_would_be_submitted():
    """Nothing may be submitted that the operator has not seen in full."""
    c = approvals.card(BRAND, APP)
    assert "Acme" in c and "Performance Marketing Manager" in c
    assert "4.3" in c and "not_needed" in c
    assert "Are you legally authorized to work in Canada?" in c, "answers must be visible"
    assert "$30K/day" in c, "the tailored CV must be visible"
    assert approvals.LEGEND in c


def test_card_fits_discord_limit():
    big = dict(APP, tailored_cv="x" * 50_000, answers={f"q{i}": "y" * 200 for i in range(40)})
    assert len(approvals.card(BRAND, big)) <= 2000


# --- all four reactions ---------------------------------------------------------------

@pytest.mark.parametrize("emoji,expected", [
    ("✅", "approved"), ("✏️", "edited"), ("⏸️", "hold"), ("❌", "rejected"),
])
@pytest.mark.asyncio
async def test_each_reaction_reads_back(emoji, expected):
    api = _fake_api([{"emoji": {"name": emoji}, "count": 2}], {emoji: [APPROVER]})
    assert await approvals.read_decision(BRAND, "msg-1", api=api) == expected


@pytest.mark.asyncio
async def test_no_reaction_is_no_decision():
    api = _fake_api([], {})
    assert await approvals.read_decision(BRAND, "msg-1", api=api) is None


# --- precedence: a no beats a yes -----------------------------------------------------

@pytest.mark.asyncio
async def test_reject_beats_approve():
    api = _fake_api([{"emoji": {"name": "✅"}, "count": 2}, {"emoji": {"name": "❌"}, "count": 2}],
                    {"✅": [APPROVER], "❌": [APPROVER]})
    assert await approvals.read_decision(BRAND, "msg-1", api=api) == "rejected"


@pytest.mark.asyncio
async def test_hold_beats_approve():
    api = _fake_api([{"emoji": {"name": "✅"}, "count": 2}, {"emoji": {"name": "⏸️"}, "count": 2}],
                    {"✅": [APPROVER], "⏸️": [APPROVER]})
    assert await approvals.read_decision(BRAND, "msg-1", api=api) == "hold"


def test_precedence_order_is_pinned():
    """Dict order IS the precedence. A casual reorder would let a stray ✅ outrank a ❌."""
    assert list(approvals.REACTIONS) == ["❌", "⏸️", "✏️", "✅"]


# --- only the operator counts ---------------------------------------------------------

@pytest.mark.asyncio
async def test_a_stranger_cannot_approve():
    api = _fake_api([{"emoji": {"name": "✅"}, "count": 2}], {"✅": [STRANGER]})
    assert await approvals.read_decision(BRAND, "msg-1", api=api) is None


@pytest.mark.asyncio
async def test_bot_legend_reaction_alone_is_not_a_decision():
    """The bot pre-seeds all four emoji. A count of 1 is the bot itself, never the operator."""
    api = _fake_api([{"emoji": {"name": "✅"}, "count": 1}], {"✅": [APPROVER]})
    assert await approvals.read_decision(BRAND, "msg-1", api=api) is None


@pytest.mark.asyncio
async def test_empty_approver_list_means_nobody_can_approve(monkeypatch):
    """Fail safe: a misconfigured brand must not become 'anyone may approve'."""
    import glitch_signal.config as cfgmod

    monkeypatch.setattr(cfgmod, "brand_config",
                        lambda b=None: {"jobs": {"approvals_channel_id": "222", "approvers": []}})
    api = _fake_api([{"emoji": {"name": "✅"}, "count": 2}], {"✅": [APPROVER]})
    assert await approvals.read_decision(BRAND, "msg-1", api=api) is None


# --- expiry is NOT approval -----------------------------------------------------------

@pytest.mark.asyncio
async def test_expiry_runs_before_reading_so_a_late_yes_cannot_resurrect():
    """A card that timed out stays expired. A reaction arriving after the window is not consent —
    treating it as one means submitting long after the operator stopped watching that role."""
    from glitch_signal.agent.jobs import store as jobstore

    order = []

    def fake_expire(brand_id, *, engine=None):
        order.append("expire")
        return ["app-expired"]

    def fake_by_status(brand_id, statuses, *, engine=None):
        order.append("read")
        return []   # the expired row is no longer 'awaiting_approval'

    import glitch_signal.agent.jobs.approvals as appr
    orig_e, orig_b = jobstore.expire_stale, jobstore.applications_by_status
    jobstore.expire_stale, jobstore.applications_by_status = fake_expire, fake_by_status
    try:
        out = await appr.run(BRAND)
    finally:
        jobstore.expire_stale, jobstore.applications_by_status = orig_e, orig_b

    assert order == ["expire", "read"], "expiry must run FIRST"
    assert out["expired"] == ["app-expired"]
    assert out["decided"] == [], "an expired card must never be decided"


def test_expire_sql_only_touches_awaiting_approval():
    """Expiry must never reach an already-approved or already-submitted row."""
    from glitch_signal.agent.jobs.store import _EXPIRE

    sql = str(_EXPIRE)
    assert "status = 'awaiting_approval'" in sql
    assert "status = 'expired'" in sql


def test_submitted_today_counts_rows_not_runs():
    """The 3/day cap must survive a loop restart — it counts submitted ROWS in the brand's day."""
    from glitch_signal.agent.jobs.store import _SUBMITTED_TODAY

    sql = str(_SUBMITTED_TODAY)
    assert "submitted_at is not null" in sql.lower()
    assert "date_trunc" in sql.lower()


# --- one unreadable card must not stop the tick ---------------------------------------

@pytest.mark.asyncio
async def test_one_unreadable_card_does_not_stop_the_rest():
    import glitch_signal.agent.jobs.approvals as appr
    from glitch_signal.agent.jobs import store as jobstore

    rows = [{"id": "a", "discord_msg_id": "m1", "canonical_url": "u1"},
            {"id": "b", "discord_msg_id": "m2", "canonical_url": "u2"}]
    calls = []

    async def flaky(brand_id, msg_id, **kw):
        calls.append(msg_id)
        if msg_id == "m1":
            raise RuntimeError("discord 500")
        return "rejected"

    orig_e, orig_b, orig_s = (jobstore.expire_stale, jobstore.applications_by_status,
                              jobstore.set_application_status)
    jobstore.expire_stale = lambda b, **kw: []
    jobstore.applications_by_status = lambda b, s, **kw: rows
    jobstore.set_application_status = lambda *a, **kw: None
    try:
        out = await appr.run(BRAND, deps={"read_decision": flaky})
    finally:
        (jobstore.expire_stale, jobstore.applications_by_status,
         jobstore.set_application_status) = orig_e, orig_b, orig_s

    assert calls == ["m1", "m2"]
    assert len(out["errors"]) == 1 and out["decided"][0]["status"] == "rejected"
