"""REVIEW #4: Buffer submissions were recorded 'pending' and nothing ever moved them on."""
from glitch_signal.agent.social import reconcile


class _FakeStore:
    def __init__(self, rows, poll_raises=False, statuses=None, stranded=None):
        self._rows = rows
        self.statuses = statuses if statuses is not None else ["posted"]
        self.stranded = stranded or []
        self.campaign_status = None
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

    async def campaign_post_statuses(self, cid, *, engine=None):
        return self.statuses

    async def set_campaign_status(self, cid, status, *, engine=None):
        self.campaign_status = status

    async def stranded_pending(self, *, older_than_s, limit=25, engine=None):
        return self.stranded


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
    assert counts["checked"] == 0 and counts["posted"] == 0 and counts["failed"] == 0


# ── PR #196 review findings ─────────────────────────────────────────────────────────────────────
async def test_terminal_buffer_failure_resolves_as_failed_not_retried():
    """FINDING 2: poll_status_for_post raises for Buffer's terminal `failed`/`error` states using the
    same RuntimeError as transport/rate-limit errors. Treating that as retryable burned the whole
    attempt budget and then left the row pending FOREVER, with the failure never recorded."""
    from glitch_signal.platforms.buffer import BufferPostFailed

    st = _FakeStore([_row()], statuses=["failed"])

    async def poll(pid, org, brand):
        raise BufferPostFailed("Buffer post reported status='failed'")

    counts = await reconcile.reconcile_pending(store_mod=st, poll=poll)
    assert counts["failed"] == 1 and st.bumped == []          # terminal, not retried
    assert st.resolved and st.resolved[0][1] == "failed"


async def test_transient_error_is_still_retried():
    """The distinction has to cut both ways — a rate limit must NOT be recorded as a failed post."""
    st = _FakeStore([_row()])

    async def poll(pid, org, brand):
        raise RuntimeError("Buffer post() query failed: RATE_LIMIT_EXCEEDED")

    counts = await reconcile.reconcile_pending(store_mod=st, poll=poll)
    assert counts["failed"] == 0 and st.bumped == ["p1"] and st.resolved == []


async def test_campaign_status_rolls_up_once_all_posts_are_terminal():
    """FINDING 3: run_campaign finalizes from the fan-out, when Buffer rows are deliberately pending.
    Without a roll-up the posts settle but the campaign reads `pending` forever."""
    st = _FakeStore([_row()], statuses=["posted", "posted"])

    async def poll(pid, org, brand):
        return (pid, "https://x.com/p/1")

    await reconcile.reconcile_pending(store_mod=st, poll=poll)
    assert st.campaign_status == "posted"


async def test_campaign_status_not_rolled_up_while_a_sibling_is_still_pending():
    """Rolling up early would mark a campaign terminal while a post is still in flight."""
    st = _FakeStore([_row()], statuses=["posted", "pending"])

    async def poll(pid, org, brand):
        return (pid, "https://x.com/p/1")

    await reconcile.reconcile_pending(store_mod=st, poll=poll)
    assert st.campaign_status is None


async def test_overlapping_sweeps_are_skipped():
    """FINDING 4: the cron tick is 20s but a batch can make 25 sequential polls of up to 15s each.
    `pending_for_reconcile` takes no lock, so overlapping sweeps select the SAME rows, duplicate
    vendor requests and burn the attempt budget far faster than intended."""
    import asyncio

    gate = asyncio.Event()
    st = _FakeStore([_row()])

    async def slow_poll(pid, org, brand):
        await gate.wait()
        return (pid, "u")

    first = asyncio.create_task(reconcile.reconcile_pending(store_mod=st, poll=slow_poll))
    await asyncio.sleep(0)                                    # let it take the lock
    second = await reconcile.reconcile_pending(store_mod=st, poll=slow_poll)
    assert second["checked"] == 0                             # skipped, not run concurrently
    gate.set()
    await first


async def test_stranded_rows_are_surfaced_with_their_correlation_key():
    """FINDING 5: a row whose provider id was never persisted has nothing to poll, so the reconciler
    can never settle it. The idem_key we sent Buffer in `source` is the operator's only handle."""
    st = _FakeStore([], stranded=[{"id": "p9", "campaign_id": "c1", "platform": "x",
                                   "idem_key": "gsa-c1-x-ab12", "brand_id": "ge"}])
    counts = await reconcile.reconcile_pending(store_mod=st, poll=None)
    assert counts["stranded"] == 1
    post_id, status, _url = st.resolved[0]
    assert post_id == "p9" and status == "unresolved"
