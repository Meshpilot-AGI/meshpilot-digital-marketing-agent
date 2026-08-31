from glitch_signal.agent.social import store
from glitch_signal.agent.social.spec import Idea, PlatformResult
from tests.test_agent_memory import FakeEngine, _Result, _Row


async def test_create_campaign_inserts_and_returns_id():
    eng = FakeEngine()
    eng.queue(_Result(rows=[("camp-1",)]))
    idea = Idea(angle="a", hook="h", key_points=["p"], dedup_key="k1")
    cid = await store.create_campaign("ge", idea, image_url="u.png", video_url="v.mp4", engine=eng)
    assert cid == "camp-1"
    sql, params = eng.calls[0]
    assert "insert into social_campaign" in sql.lower()
    assert params["brand"] == "ge" and params["dedup_key"] == "k1"


async def test_recent_dedup_keys_returns_set():
    eng = FakeEngine()
    eng.queue(_Result(rows=[_Row({"dedup_key": "k1"}), _Row({"dedup_key": "k2"})]))
    keys = await store.recent_dedup_keys("ge", limit=10, engine=eng)
    assert keys == {"k1", "k2"}


async def test_already_posted_true_when_row_exists():
    eng = FakeEngine()
    eng.queue(_Result(rows=[("x",)]))
    assert await store.already_posted("camp-1", "x", engine=eng) is True


async def test_record_post_writes_row():
    eng = FakeEngine()
    eng.queue(_Result(rowcount=1))
    r = PlatformResult(platform="x", status="posted", verdict="pass",
                       platform_post_id="p1", post_url="http://x")
    await store.record_post("camp-1", r, media_kind="image", caption="c", engine=eng)
    sql, params = eng.calls[0]
    assert "insert into social_post" in sql.lower()
    assert params["platform"] == "x" and params["status"] == "posted"
