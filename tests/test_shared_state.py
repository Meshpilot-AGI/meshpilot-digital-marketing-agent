"""Cross-worker shared state (#98): webhook dedup + shared rate limiter (fake engine, no DB)."""
from __future__ import annotations

from glitch_signal.middleware.shared_state import SharedWindowLimiter, cleanup, webhook_seen


class _Result:
    def __init__(self, first):
        self._first = first

    def first(self):
        return self._first


class _Conn:
    def __init__(self, sink, first):
        self._sink, self._first = sink, first

    async def execute(self, stmt, params=None):
        self._sink.append((str(stmt), params))
        return _Result(self._first)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Engine:
    def __init__(self, first=None):
        self.calls = []
        self._first = first

    def begin(self):
        return _Conn(self.calls, self._first)


# ── webhook dedup ──
async def test_webhook_first_time_is_not_seen():
    eng = _Engine(first=(1,))  # RETURNING 1 → row inserted → first time
    assert await webhook_seen("heygen", "evt-1", engine=eng) is False
    assert "on conflict" in eng.calls[0][0].lower() and "do nothing" in eng.calls[0][0].lower()


async def test_webhook_redelivery_is_seen():
    eng = _Engine(first=None)  # ON CONFLICT fired → no row → already seen
    assert await webhook_seen("heygen", "evt-1", engine=eng) is True


async def test_webhook_empty_event_id_is_not_seen():
    eng = _Engine()
    assert await webhook_seen("heygen", "", engine=eng) is False
    assert eng.calls == []  # no DB call for an empty id


async def test_webhook_fails_open_on_db_error():
    class _Boom:
        def begin(self):
            raise RuntimeError("db down")
    # fail-open: never drop a real event
    assert await webhook_seen("heygen", "evt-1", engine=_Boom()) is False


# ── shared rate limiter ──
async def test_shared_limiter_allows_under_limit():
    lim = SharedWindowLimiter(limit=5, window_seconds=60, engine=_Engine(first=(3,)))
    allowed, retry = await lim.check("ip:1.2.3.4")
    assert allowed is True and retry == 0


async def test_shared_limiter_blocks_over_limit():
    lim = SharedWindowLimiter(limit=5, window_seconds=60, engine=_Engine(first=(6,)))
    allowed, retry = await lim.check("ip:1.2.3.4")
    assert allowed is False and retry >= 1


async def test_shared_limiter_fails_open():
    class _Boom:
        def begin(self):
            raise RuntimeError("db down")
    lim = SharedWindowLimiter(limit=5, window_seconds=60, engine=_Boom())
    allowed, retry = await lim.check("ip:1.2.3.4")
    assert allowed is True and retry == 0  # fail-open: broken DB never becomes an outage


# ── #193: window-scale mismatch between the 60s rate limiter and e.g. the 86400s daily email cap ──
async def test_check_persists_its_own_window_scale():
    """Each row must record the window scale it belongs to, so cleanup can prune per-row instead of
    comparing raw bucket numbers across incompatible scales (60s vs 86400s)."""
    eng = _Engine(first=(1,))
    lim = SharedWindowLimiter(limit=50, window_seconds=86400.0, engine=eng)  # e.g. daily email cap
    await lim.check("email:brand-x")
    _, params = eng.calls[0]
    assert params["ws"] == 86400


async def test_cleanup_does_not_use_a_single_cross_scale_cutoff():
    """Regression for #193: the hourly cleanup used to delete `WHERE window_start < :cutoff` with a
    cutoff computed from the 60s rate-limit window, which wipes any row on a larger window scale
    (e.g. the 86400s daily email cap ends up bucketed ~20,693 vs a 60s cutoff of ~29.4M) on every
    sweep. The fixed query must prune by each row's own `window_seconds`, not a single global cutoff
    parameter that conflates scales.
    """
    eng = _Engine(first=(1,))
    await cleanup(window_s=60, engine=eng)
    rate_counters_sql = eng.calls[0][0].lower()
    assert "window_start < :cutoff" not in rate_counters_sql
    assert "window_seconds" in rate_counters_sql
    # No caller-supplied cutoff param should reach the query — the DB computes wall-clock expiry
    # per row from its own stored window_seconds instead.
    assert eng.calls[0][1] in (None, {})


# ── #196: the #193 backfill mislabeled every pre-existing row's scale as 60s (including 86400s
#    daily-cap buckets), which the scale-aware cleanup then read as ancient and deleted. Fix: an
#    unknown (NULL) window_seconds is never pruned, and the upsert repairs a row's scale on conflict.
async def test_cleanup_never_prunes_unknown_scale_rows():
    """The DELETE must exclude rows whose window_seconds is NULL (unknown scale) — pruning them by
    guessing a scale is exactly the #193 cross-scale wipe this migration exists to prevent."""
    eng = _Engine(first=(1,))
    await cleanup(window_s=60, engine=eng)
    rate_counters_sql = eng.calls[0][0].lower()
    assert "window_seconds is not null" in rate_counters_sql


async def test_check_upsert_repairs_window_seconds_on_conflict():
    """A conflicting write (existing key+bucket row) must SET window_seconds = the caller's value,
    not just bump count — otherwise a row stuck with a wrong/unknown stored scale (e.g. from the
    #193 backfill) can never self-heal."""
    eng = _Engine(first=(2,))
    lim = SharedWindowLimiter(limit=50, window_seconds=86400.0, engine=eng)
    await lim.check("email:brand-x")
    sql, params = eng.calls[0]
    sql_l = sql.lower()
    assert "do update set" in sql_l
    assert "window_seconds" in sql_l.split("do update set", 1)[1]  # the UPDATE branch sets it too
    assert params["ws"] == 86400
