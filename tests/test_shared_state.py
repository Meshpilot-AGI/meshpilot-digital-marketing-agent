"""Cross-worker shared state (#98): webhook dedup + shared rate limiter (fake engine, no DB)."""
from __future__ import annotations

from glitch_signal.middleware.shared_state import SharedWindowLimiter, webhook_seen


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
