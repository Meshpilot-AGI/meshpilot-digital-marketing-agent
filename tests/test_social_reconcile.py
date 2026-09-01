"""REVIEW #4: Buffer submissions were recorded 'pending' and nothing ever moved them on."""
from glitch_signal.agent.social import reconcile


class _FakeStore:
    def __init__(self, rows, poll_raises=False):
        self._rows = rows
        self.query_kwargs: dict = {}
        self.resolved: list[tuple[str, str, str | None]] = []
        self.bumped: list[str] = []

    async def pending_for_reconcile(self, *, older_than_s, limit, max_attempts, engine=None):
        self.query_kwargs = {"older_than_s": older_than_s, "limit": limit,
                             "max_attempts": max_attempts}
        return self._rows

    async def resolve_pending(self, post_id, status, *, post_url=None, error=None, engine=None):
        self.resolved.append((post_id, status, post_url))

    async def bump_reconcile_attempt(self, post_id, *, engine=None):
        self.bumped.append(post_id)


def _row(i="p1", pid="bpost-1"):
    return {"id": i, "campaign_id": "camp-1", "platform": "x", "platform_post_id": pid,
            "reconcile_attempts": 0, "brand_id": "ge"}


async def test_sent_post_is_resolved_to_posted():
    st = _FakeStore([_row()])

    async def poll(pid, org, brand):
        return (pid, "https://x.com/p/1")

    counts = await reconcile.reconcile_pending(store_mod=st, poll=poll)
    assert st.resolved == [("p1", "posted", "https://x.com/p/1")]
    assert counts["posted"] == 1 and st.bumped == []


async def test_still_sending_stays_pending_and_counts_an_attempt():
    """A None return means 'in flight' — it must NOT be marked failed, but the attempt is counted
    so an unresolvable row cannot spin the sweep forever."""
    st = _FakeStore([_row()])

    async def poll(pid, org, brand):
        return (None, None)

    counts = await reconcile.reconcile_pending(store_mod=st, poll=poll)
    assert st.resolved == [] and st.bumped == ["p1"]
    assert counts["in_flight"] == 1


async def test_vendor_error_does_not_abort_the_rest_of_the_sweep():
    st = _FakeStore([_row("p1", "b1"), _row("p2", "b2")])

    async def poll(pid, org, brand):
        if pid == "b1":
            raise RuntimeError("Buffer rate limited")
        return (pid, "https://x.com/p/2")

    counts = await reconcile.reconcile_pending(store_mod=st, poll=poll)
    assert st.bumped == ["p1"]                       # the failure was counted, not fatal
    assert st.resolved == [("p2", "posted", "https://x.com/p/2")]   # and the next row still ran
    assert counts["checked"] == 2 and counts["posted"] == 1


async def test_only_settled_rows_are_polled():
    st = _FakeStore([])
    await reconcile.reconcile_pending(store_mod=st, poll=None)
    # Buffer needs a moment to actually push; polling instantly just burns quota on "sending".
    assert st.query_kwargs["older_than_s"] == reconcile.SETTLE_WINDOW_S
    assert st.query_kwargs["max_attempts"] == reconcile.MAX_ATTEMPTS


async def test_query_failure_returns_empty_counts_without_raising():
    """Runs from the cron tick, where an exception would be invisible."""
    class _Boom:
        async def pending_for_reconcile(self, **k):
            raise RuntimeError("db down")

    counts = await reconcile.reconcile_pending(store_mod=_Boom(), poll=None)
    assert counts == {"checked": 0, "posted": 0, "failed": 0, "in_flight": 0}
