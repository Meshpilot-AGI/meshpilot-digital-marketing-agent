from glitch_signal.agent.social import publish
from glitch_signal.agent.social.spec import PostDraft


class _FakeStore:
    def __init__(self, pending_inserted=True, mark_result_raises=False, mark_result_fails_times=0):
        self._inserted = pending_inserted
        self._mr_raises = mark_result_raises
        self._mr_fails_left = mark_result_fails_times
        self.pending: list[str] = []
        self.idem_keys: list[str | None] = []
        self.results: list[tuple[str, str]] = []
        self.mark_result_calls = 0
        self.recorded: list = []

    async def mark_pending(self, cid, platform, media_kind, caption, verdict, *,
                           idem_key=None, engine=None):
        self.pending.append(platform)
        self.idem_keys.append(idem_key)
        return self._inserted

    async def mark_result(self, cid, platform, status, *, platform_post_id, post_url, error, engine=None):
        self.mark_result_calls += 1
        if self._mr_raises:
            raise RuntimeError("db down")
        if self._mr_fails_left > 0:
            self._mr_fails_left -= 1
            raise RuntimeError("transient db blip")
        self.results.append((platform, status))

    async def record_post(self, cid, r, media_kind, caption, *, engine=None):
        self.recorded.append(r)


def _deps(calls):
    async def buffer_create(brand_id, service, *, text, media_url=None, idem_key=None):
        calls.append(("buffer", service, media_url))
        return ("bpost", "sending")
    async def fb(*, brand_id=None, message=None, image_url=None, video_url=None):
        calls.append(("fb", image_url, video_url))
        return ("fbid", "http://fb")
    async def ig(*, brand_id=None, caption=None, image_url=None, video_url=None):
        calls.append(("ig", image_url, video_url))
        return ("igid", "http://ig")
    return publish.Publishers(buffer_create=buffer_create, facebook=fb, instagram=ig)


async def test_fan_out_buffer_pending_meta_posted():
    calls = []
    drafts = [
        PostDraft("x", "image", "img.png", "c"),
        PostDraft("linkedin", "image", "img.png", "c"),
        PostDraft("facebook", "image", "img.png", "c"),
        PostDraft("tiktok", "video", "vid.mp4", "c"),
        PostDraft("instagram", "video", "vid.mp4", "c"),
    ]
    st = _FakeStore()
    res = await publish.fan_out("ge", "camp-1", drafts, {d.platform: "pass" for d in drafts},
                                deps=_deps(calls), store_mod=st)
    by = {r.platform: r.status for r in res}
    # Buffer 'sending' is NOT terminal → pending; Meta returns a real id synchronously → posted.
    assert by == {"x": "pending", "linkedin": "pending", "tiktok": "pending",
                  "facebook": "posted", "instagram": "posted"}
    assert ("buffer", "tiktok", "vid.mp4") in calls          # video via buffer
    assert ("fb", "img.png", None) in calls                  # image via meta
    assert ("ig", None, "vid.mp4") in calls                  # video via meta reels
    assert len(st.pending) == 5 and len(st.results) == 5     # outbox reserved then updated per platform


async def test_escalated_is_held_not_published():
    calls = []
    st = _FakeStore()
    res = await publish.fan_out("ge", "camp-1", [PostDraft("x", "image", "i.png", "c")],
                                {"x": "escalate"}, deps=_deps(calls), store_mod=st)
    assert res[0].status == "held" and calls == [] and st.pending == []   # never reserved/published
    assert len(st.recorded) == 1


async def test_already_attempted_skips_without_republish():
    calls = []
    st = _FakeStore(pending_inserted=False)   # mark_pending conflict → an attempt already exists
    res = await publish.fan_out("ge", "camp-1", [PostDraft("x", "image", "i.png", "c")],
                                {"x": "pass"}, deps=_deps(calls), store_mod=st)
    assert res[0].status == "skipped" and calls == []        # uncertain/duplicate not republished


async def test_persistence_failure_after_publish_is_isolated():
    calls = []
    st = _FakeStore(mark_result_raises=True)
    res = await publish.fan_out("ge", "camp-1", [PostDraft("facebook", "image", "i.png", "c")],
                                {"facebook": "pass"}, deps=_deps(calls), store_mod=st)
    # external publish happened; a mark_result DB error does not abort or lose the result
    assert res[0].status == "posted" and ("fb", "i.png", None) in calls


async def test_correlation_key_is_minted_before_publish_and_sent_to_provider():
    """REVIEW #1: the provider assigns its id only on success, so the ONLY identifier that exists on
    both sides before the call is one we mint ourselves. It must be persisted with the pending
    outbox row AND handed to the provider, so a lost response is still reconcilable."""
    seen: dict = {}

    async def buffer_create(brand_id, service, *, text, media_url=None, idem_key=None):
        seen["idem_key"] = idem_key
        return ("bpost", "sending")

    deps = publish.Publishers(buffer_create=buffer_create, facebook=None, instagram=None)
    st = _FakeStore()
    await publish.fan_out("ge", "camp-1", [PostDraft("x", "image", "i.png", "c")],
                          {"x": "pass"}, deps=deps, store_mod=st)
    assert st.idem_keys[0] is not None                       # persisted BEFORE the provider call
    assert seen["idem_key"] == st.idem_keys[0]               # same key reached the provider
    assert "camp-1" in st.idem_keys[0] and "x" in st.idem_keys[0]


async def test_mark_result_retries_a_transient_db_failure():
    """REVIEW #1: the result write carries the provider id — losing it strands a REAL published post
    as an un-pollable 'pending' row. A transient blip must be retried, not swallowed first try."""
    calls = []
    st = _FakeStore(mark_result_fails_times=2)
    res = await publish.fan_out("ge", "camp-1", [PostDraft("facebook", "image", "i.png", "c")],
                                {"facebook": "pass"}, deps=_deps(calls), store_mod=st)
    assert res[0].status == "posted"
    assert st.mark_result_calls == 3                         # two failures, then it landed
    assert st.results == [("facebook", "posted")]


async def test_mark_result_exhaustion_leaves_row_pending_and_never_republishes():
    """REVIEW #1: on exhaustion we do NOT republish — the row stays 'pending' for the reconciler,
    so the worst case is a delayed status, never a duplicate post."""
    calls = []
    st = _FakeStore(mark_result_raises=True)
    ok = await publish._mark_result_durably(st, "camp-1", "x", "pending", pid="bpost",
                                            url=None, error=None, idem_key="gsa-x")
    assert ok is False
    assert st.mark_result_calls == publish._MARK_RESULT_ATTEMPTS
    assert calls == []                                       # no re-publish attempt of any kind
