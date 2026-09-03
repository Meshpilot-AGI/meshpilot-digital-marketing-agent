"""SEO-9 — alerting on the silence between cycles.

The thing being watched is silence, not an error. A cycle that crashes leaves a row with `ok=False`;
a cycle that never runs leaves nothing, and nothing is exactly what a healthy quiet day looks like.
"""
from __future__ import annotations

import datetime as dt

from glitch_signal.agent.cron import capabilities as caps
from glitch_signal.agent.seo import heartbeat, track

NOW = dt.datetime(2026, 9, 3, 12, 0, tzinfo=dt.UTC)


class _Sent:
    def __init__(self, boom: bool = False):
        self.calls, self.boom = [], boom

    async def __call__(self, **kw):
        if self.boom:
            raise RuntimeError("resend down")
        self.calls.append(kw)
        return "msg_1"


def _rows(monkeypatch, rows):
    async def _recent(brand_id, *, limit=10, engine=None):
        return rows

    monkeypatch.setattr(track, "recent_cycles", _recent)


def _allow(monkeypatch, allowed=True):
    async def _may(brand_id):
        return allowed

    monkeypatch.setattr(heartbeat, "_may_alert", _may)
    monkeypatch.setattr(heartbeat, "_cfg", lambda b, n, d="": "ops@example.test" if n == "ALERT_EMAIL" else d)


# ── healthy ──
async def test_a_recent_cycle_is_quiet(monkeypatch):
    _rows(monkeypatch, [{"ran_at": NOW - dt.timedelta(hours=6), "outcome": "published"}])
    _allow(monkeypatch)
    sent = _Sent()
    res = await heartbeat.check("b", now=NOW, notify=sent)
    assert res["stale"] is False and res["alerted"] is False and sent.calls == []


async def test_a_refusal_is_still_a_heartbeat(monkeypatch):
    """A refusal means the cycle RAN and declined — the machine is alive, which is what is being
    watched. Treating it as failure would page on every quiet day."""
    _rows(monkeypatch, [{"ran_at": NOW - dt.timedelta(hours=2), "outcome": "refused"}])
    _allow(monkeypatch)
    res = await heartbeat.check("b", now=NOW, notify=_Sent())
    assert res["stale"] is False


# ── stale ──
async def test_a_missed_run_alerts(monkeypatch):
    _rows(monkeypatch, [{"ran_at": NOW - dt.timedelta(hours=31), "outcome": "published"}])
    _allow(monkeypatch)
    sent = _Sent()
    res = await heartbeat.check("b", now=NOW, notify=sent)
    assert res["stale"] and res["alerted"]
    assert "31.0h" in res["reason"]
    assert "launchctl list" in sent.calls[0]["text"]      # tells the reader what to actually do


async def test_no_rows_at_all_is_the_loudest_case(monkeypatch):
    """Not a missing datapoint. Either it has never run, or every row predates the table."""
    _rows(monkeypatch, [])
    _allow(monkeypatch)
    sent = _Sent()
    res = await heartbeat.check("b", now=NOW, notify=sent)
    assert res["stale"] and res["alerted"]
    assert "has ever been recorded" in res["reason"]


async def test_a_run_just_inside_the_threshold_is_not_stale(monkeypatch):
    _rows(monkeypatch, [{"ran_at": NOW - dt.timedelta(hours=29.9), "outcome": "published"}])
    _allow(monkeypatch)
    assert (await heartbeat.check("b", now=NOW, notify=_Sent()))["stale"] is False


# ── not shouting ──
async def test_it_alerts_once_per_window_not_every_run(monkeypatch):
    """The watcher runs on its own schedule, so without this a single stale cycle pages every time it
    fires — and an alert that repeats is an alert people filter."""
    _rows(monkeypatch, [{"ran_at": NOW - dt.timedelta(hours=40), "outcome": "published"}])
    _allow(monkeypatch, allowed=False)
    sent = _Sent()
    res = await heartbeat.check("b", now=NOW, notify=sent)
    assert res["stale"] and not res["alerted"] and sent.calls == []
    assert "already alerted" in res["detail"]


async def test_no_recipient_means_logged_only(monkeypatch):
    _rows(monkeypatch, [{"ran_at": NOW - dt.timedelta(hours=40), "outcome": "published"}])
    monkeypatch.setattr(heartbeat, "_cfg", lambda b, n, d="": d)
    res = await heartbeat.check("b", now=NOW, notify=_Sent())
    assert res["stale"] and not res["alerted"] and "no <PREFIX>_SEO_ALERT_EMAIL" in res["detail"]


async def test_a_failed_delivery_does_not_kill_the_monitor(monkeypatch):
    """A monitor that dies on its own delivery tells you nothing about the thing it monitors."""
    _rows(monkeypatch, [{"ran_at": NOW - dt.timedelta(hours=40), "outcome": "published"}])
    _allow(monkeypatch)
    res = await heartbeat.check("b", now=NOW, notify=_Sent(boom=True))
    assert res["ok"] and res["stale"] and not res["alerted"]
    assert "delivery failed" in res["detail"]


# ── the trap ──
async def test_the_watcher_never_writes_to_the_table_it_watches(monkeypatch):
    """Recording its own run in `seo_cycle` would refresh the newest-row timestamp and mask the very
    gap it exists to measure — the watcher would permanently reassure itself."""
    calls = []

    async def _record(*a, **kw):
        calls.append(kw)
        return True

    monkeypatch.setattr(track, "record_cycle", _record)
    _rows(monkeypatch, [{"ran_at": NOW - dt.timedelta(hours=40), "outcome": "published"}])
    _allow(monkeypatch)
    await heartbeat.check("b", now=NOW, notify=_Sent())
    assert calls == []


# ── wiring ──
def test_it_is_schedulable_from_the_cloud():
    assert "seo_heartbeat" in caps.names()


def test_sending_an_alert_demands_the_publish_capability():
    """`send_email` lives under `publish` in the capability vocabulary. Mapped honestly rather than
    arguing that an ops alert is a different kind of send."""
    assert caps.required_capabilities("seo_heartbeat") == frozenset({"publish"})
