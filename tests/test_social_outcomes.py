"""Outcome ingestion — the learning loop's sensor.

Before this, `curator.py` distilled lessons from `kind='episode'` memories: the agent's own record
of what it DID. Nothing read back what any post ACHIEVED, so a durable lesson could be learned from
a post that flopped.
"""
from datetime import UTC

from glitch_signal.agent.social import outcomes


class _FakeStore:
    def __init__(self, due_by_bucket=None):
        self.due = due_by_bucket or {}
        self.queries = []
        self.written = []

    async def posts_due_for_metrics(self, *, min_age_s, max_age_s, bucket, platforms,
                                    limit=25, engine=None):
        self.queries.append({"bucket": bucket, "min": min_age_s, "max": max_age_s,
                             "platforms": platforms})
        return self.due.get(bucket, [])

    async def record_metrics(self, post_id, platform, bucket, m, *, engine=None):
        self.written.append((post_id, platform, bucket, m))


def _post(i="p1", platform="facebook", measured_from=None):
    return {"id": i, "platform": platform, "platform_post_id": "fb1", "media_kind": "image",
            "brand_id": "ge", "idea": {}, "campaign_id": "c1", "measured_from": measured_from}


async def test_records_a_reading_per_bucket():
    st = _FakeStore({"24h": [_post()]})

    async def fetch(platform, pid, *, brand_id=None, client=None):
        return {"impressions": 100, "reach": 80, "likes": 5, "raw": {}}

    counts = await outcomes.collect(store_mod=st, fetch=fetch)
    assert counts["read"] == 1
    assert st.written[0][2] == "24h"


async def test_a_reading_that_arrives_after_the_window_is_not_recorded():
    """If the fetch is slow enough (backlog, rate limiting) that a post's real age drifts past the
    bucket's window before the write happens, the reading must not be locked in — the unique
    (post_id, age_bucket) constraint would otherwise permanently pair this bucket's label with a
    value read at the wrong age, making it incomparable to every other post's same-named bucket."""
    from datetime import datetime, timedelta

    stale = datetime.now(UTC) - timedelta(hours=10)   # "1h" bucket's window is 1-6h
    st = _FakeStore({"1h": [_post(measured_from=stale)]})

    async def fetch(*a, **k):
        return {"impressions": 1, "raw": {}}

    counts = await outcomes.collect(store_mod=st, fetch=fetch)
    assert st.written == []
    assert counts["read"] == 0


async def test_a_reading_taken_within_the_window_is_still_recorded():
    """The freshness re-check must not reject a normal, on-time reading."""
    from datetime import datetime, timedelta

    fresh = datetime.now(UTC) - timedelta(hours=2)    # inside the "1h" bucket's 1-6h window
    st = _FakeStore({"1h": [_post(measured_from=fresh)]})

    async def fetch(*a, **k):
        return {"impressions": 1, "raw": {}}

    counts = await outcomes.collect(store_mod=st, fetch=fetch)
    assert counts["read"] == 1
    assert st.written[0][2] == "1h"


async def test_unmeasurable_platform_is_never_recorded_as_zero():
    """THE critical invariant. A fabricated zero makes 'nobody engaged' indistinguishable from
    'we could not measure', and the loop would learn from that difference."""
    st = _FakeStore({"1h": [_post(platform="x")]})

    async def fetch(platform, pid, *, brand_id=None, client=None):
        return None                                     # Buffer-routed: no analytics available

    counts = await outcomes.collect(store_mod=st, fetch=fetch)
    assert counts["unmeasured"] == 1
    assert st.written == []                             # nothing written at all


async def test_only_measurable_platforms_are_queried():
    """Asking for X/LinkedIn/TikTok would just burn quota — Buffer returns delivery, not analytics."""
    st = _FakeStore()

    async def fetch(*a, **k):
        return None

    await outcomes.collect(store_mod=st, fetch=fetch)
    for q in st.queries:
        assert set(q["platforms"]) == {"facebook", "instagram"}


async def test_buckets_are_age_windowed_not_open_ended():
    """An upper bound stops an old backlog being read at the wrong age and stored as if it were a
    fresh 1h reading — which would silently corrupt every same-age comparison."""
    st = _FakeStore()

    async def fetch(*a, **k):
        return None

    await outcomes.collect(store_mod=st, fetch=fetch)
    by = {q["bucket"]: q for q in st.queries}
    assert set(by) == {"1h", "24h", "7d"}
    for q in st.queries:
        assert q["max"] > q["min"]                      # bounded window, not "everything older than"


async def test_a_write_failure_does_not_abort_the_sweep():
    st = _FakeStore({"1h": [_post("p1"), _post("p2")]})

    async def fetch(*a, **k):
        return {"impressions": 1, "raw": {}}

    async def boom(post_id, platform, bucket, m, *, engine=None):
        if post_id == "p1":
            raise RuntimeError("db blip")
        st.written.append((post_id, platform, bucket, m))
    st.record_metrics = boom

    counts = await outcomes.collect(store_mod=st, fetch=fetch)
    assert counts["read"] == 1 and st.written[0][0] == "p2"


async def test_a_query_failure_skips_that_bucket_only():
    class _Partial(_FakeStore):
        async def posts_due_for_metrics(self, *, bucket, **k):
            if bucket == "1h":
                raise RuntimeError("db down")
            return [_post()] if bucket == "24h" else []

    st = _Partial()

    async def fetch(*a, **k):
        return {"impressions": 1, "raw": {}}

    counts = await outcomes.collect(store_mod=st, fetch=fetch)
    assert counts["read"] == 1                          # 24h still collected


async def test_overlapping_collections_are_skipped():
    import asyncio

    gate = asyncio.Event()
    st = _FakeStore({"1h": [_post()]})

    async def slow(*a, **k):
        await gate.wait()
        return {"impressions": 1, "raw": {}}

    first = asyncio.create_task(outcomes.collect(store_mod=st, fetch=slow))
    await asyncio.sleep(0)
    second = await outcomes.collect(store_mod=st, fetch=slow)
    assert second == {"read": 0, "unmeasured": 0}
    gate.set()
    await first
