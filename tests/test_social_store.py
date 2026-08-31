from glitch_signal.agent.social import store
from glitch_signal.agent.social.spec import Idea, PlatformResult
from tests.test_agent_memory import FakeEngine, _Result, _Row


async def test_reserve_campaign_returns_id():
    eng = FakeEngine()
    eng.queue(_Result(rows=[("camp-1",)]))
    cid = await store.reserve_campaign("ge", Idea("a", "h", ["p"], "k1"), engine=eng)
    assert cid == "camp-1"
    sql, params = eng.calls[0]
    assert "insert into social_campaign" in sql.lower() and "on conflict" in sql.lower()
    assert params["brand"] == "ge" and params["dedup_key"] == "k1"


async def test_reserve_campaign_conflict_returns_none():
    eng = FakeEngine()
    eng.queue(_Result(rows=[]))                      # ON CONFLICT (brand,dedup) DO NOTHING → no row
    cid = await store.reserve_campaign("ge", Idea("a", "h", ["p"], "k1"), engine=eng)
    assert cid is None


async def test_recent_dedup_keys_returns_set():
    eng = FakeEngine()
    eng.queue(_Result(rows=[_Row({"dedup_key": "k1"}), _Row({"dedup_key": "k2"})]))
    assert await store.recent_dedup_keys("ge", limit=10, engine=eng) == {"k1", "k2"}


async def test_mark_pending_inserts_and_reports_true():
    eng = FakeEngine()
    eng.queue(_Result(rows=[("row-1",)]))
    ok = await store.mark_pending("camp-1", "x", "image", "c", "pass", engine=eng)
    assert ok is True
    sql, params = eng.calls[0]
    assert "insert into social_post" in sql.lower() and "on conflict" in sql.lower()
    assert "'pending'" in sql.lower()                 # status is a SQL literal, not a bind
    assert params["platform"] == "x" and params["verdict"] == "pass"


async def test_mark_pending_conflict_reports_false():
    eng = FakeEngine()
    eng.queue(_Result(rows=[]))                      # row already exists → no insert → don't republish
    assert await store.mark_pending("camp-1", "x", "image", "c", "pass", engine=eng) is False


async def test_mark_result_updates_row():
    eng = FakeEngine()
    eng.queue(_Result(rowcount=1))
    await store.mark_result("camp-1", "facebook", "posted", platform_post_id="p1",
                            post_url="http://fb", error=None, engine=eng)
    sql, params = eng.calls[0]
    assert "update social_post set status" in sql.lower()
    assert params["s"] == "posted" and params["p"] == "facebook" and params["ppid"] == "p1"


async def test_record_post_writes_terminal_row():
    eng = FakeEngine()
    eng.queue(_Result(rowcount=1))
    r = PlatformResult(platform="x", status="held", verdict="escalate")
    await store.record_post("camp-1", r, media_kind="image", caption="c", engine=eng)
    sql, params = eng.calls[0]
    assert "insert into social_post" in sql.lower() and params["status"] == "held"


async def test_finalize_sets_status_cost_reason():
    eng = FakeEngine()
    eng.queue(_Result(rowcount=1))
    await store.finalize_campaign("camp-1", "failed", 1.25, failure_reason="boom", engine=eng)
    sql, params = eng.calls[0]
    assert "update social_campaign set status" in sql.lower()
    assert params["s"] == "failed" and params["c"] == 1.25 and params["reason"] == "boom"
