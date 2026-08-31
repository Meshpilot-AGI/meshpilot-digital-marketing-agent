from glitch_signal.agent.social import publish
from glitch_signal.agent.social.spec import PostDraft


class _FakeStore:
    def __init__(self, posted=False):
        self._posted = posted
        self.recorded = []
    async def already_posted(self, cid, platform, *, engine=None):
        return self._posted
    async def record_post(self, cid, r, media_kind, caption, *, engine=None):
        self.recorded.append(r)


def _deps(calls):
    async def buffer_create(brand_id, service, *, text, media_url=None):
        calls.append(("buffer", service, media_url))
        return ("bpost", "sending")
    async def fb(*, brand_id=None, message=None, image_url=None, video_url=None):
        calls.append(("fb", image_url, video_url))
        return ("fbid", "http://fb")
    async def ig(*, brand_id=None, caption=None, image_url=None, video_url=None):
        calls.append(("ig", image_url, video_url))
        return ("igid", "http://ig")
    return publish.Publishers(buffer_create=buffer_create, facebook=fb, instagram=ig)


async def test_fan_out_routes_each_platform_once_correct_medium():
    calls = []
    drafts = [
        PostDraft("x", "image", "img.png", "c"),
        PostDraft("linkedin", "image", "img.png", "c"),
        PostDraft("facebook", "image", "img.png", "c"),
        PostDraft("tiktok", "video", "vid.mp4", "c"),
        PostDraft("instagram", "video", "vid.mp4", "c"),
    ]
    verdicts = {d.platform: "pass" for d in drafts}
    st = _FakeStore()
    res = await publish.fan_out("ge", "camp-1", drafts, verdicts, deps=_deps(calls), store_mod=st)
    assert {r.platform for r in res} == {"x", "linkedin", "facebook", "tiktok", "instagram"}
    assert all(r.status == "posted" for r in res)
    assert ("buffer", "tiktok", "vid.mp4") in calls          # video via buffer
    assert ("fb", "img.png", None) in calls                  # image via meta
    assert ("ig", None, "vid.mp4") in calls                  # video via meta reels
    assert len(st.recorded) == 5


async def test_escalated_verdict_is_held_not_published():
    calls = []
    drafts = [PostDraft("x", "image", "img.png", "c")]
    st = _FakeStore()
    res = await publish.fan_out("ge", "camp-1", drafts, {"x": "escalate"},
                                deps=_deps(calls), store_mod=st)
    assert res[0].status == "held" and calls == []           # never published


async def test_idempotent_skip_when_already_posted():
    calls = []
    st = _FakeStore(posted=True)
    res = await publish.fan_out("ge", "camp-1", [PostDraft("x", "image", "i.png", "c")],
                                {"x": "pass"}, deps=_deps(calls), store_mod=st)
    assert res[0].status == "skipped" and calls == []
