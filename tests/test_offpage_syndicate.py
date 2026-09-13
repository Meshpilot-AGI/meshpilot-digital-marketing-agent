"""OFFPAGE-1 — every merged post earns X on day 0 and LinkedIn on day 1, once, from the page's own facts."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from glitch_signal.agent.offpage import syndicate as syn

NOW = datetime(2026, 9, 13, 14, 0, tzinfo=UTC)
POSTS = [{"slug": "a", "title": "A: the 5% rule", "merged_at": NOW - timedelta(days=3)},
         {"slug": "b", "title": "B", "merged_at": NOW - timedelta(days=2)},
         {"slug": "c", "title": "C", "merged_at": NOW - timedelta(days=1)}]


def _c(slug, kind, status="posted_by_agent", age_h=30):
    return {"source_ref": slug, "surface_kind": kind, "status": status,
            "created_at": NOW - timedelta(hours=age_h)}


# ----------------------------------------------------------------------------- planning

def test_first_run_takes_the_oldest_post_to_x_only():
    assert syn.plan(POSTS, [], NOW) == [("x", POSTS[0])]


def test_linkedin_follows_x_the_next_day_while_x_moves_on():
    cands = [_c("a", "x", age_h=30)]
    assert syn.plan(POSTS, cands, NOW) == [("x", POSTS[1]), ("linkedin", POSTS[0])]


def test_linkedin_waits_until_x_is_old_enough():
    cands = [_c("a", "x", age_h=2)]
    assert syn.plan(POSTS, cands, NOW) == [("x", POSTS[1])]


def test_a_skipped_x_row_blocks_that_post_on_both_platforms_until_a_human_looks():
    cands = [_c("a", "x", status="skipped", age_h=48)]
    # X for post "a" is not retried (the row exists), and LinkedIn never follows a failed X.
    assert syn.plan(POSTS, cands, NOW) == [("x", POSTS[1])]


def test_nothing_left_means_no_actions():
    cands = [_c(s, k) for s in "abc" for k in ("x", "linkedin")]
    assert syn.plan(POSTS, cands, NOW) == []


def test_naive_timestamps_from_the_driver_are_treated_as_utc():
    cands = [{"source_ref": "a", "surface_kind": "x", "status": "posted_by_agent",
              "created_at": (NOW - timedelta(hours=30)).replace(tzinfo=None)}]
    assert ("linkedin", POSTS[0]) in syn.plan(POSTS, cands, NOW)


# ----------------------------------------------------------------------------- checks

PAGE = "FTMO allows a 5% daily loss and a 10% max drawdown on a $100,000 account, since 2015."


@pytest.mark.parametrize("body,expect", [
    ("FTMO's daily loss limit is 5% — here's how it interacts with overnight holds.", []),
    ("A $100,000 account has a 10% max drawdown.", []),
    ("The daily limit is 6%.", ["unsupported_figures:6%"]),
    ("Read it here https://x.y/z", ["contains_url"]),
    ("Great post #propfirm", ["hashtag"]),
    ("", ["empty"]),
])
def test_check_catches_what_the_page_cannot_back(body, expect):
    assert syn.check(body, platform="x", page_text=PAGE, hard_stops=[]) == expect


def test_check_refuses_hard_stops_and_length():
    long = "x" * 241
    assert syn.check(long, platform="x", page_text=PAGE, hard_stops=[]) == ["too_long:241>240"]
    assert syn.check("guaranteed pass with this", platform="linkedin", page_text=PAGE,
                     hard_stops=["guaranteed pass"]) == ["hard_stop:guaranteed pass"]


def test_figures_compare_as_written():
    assert syn.figures("5% of $100,000 since 2015, 0.5 lots") == {"5%", "100,000", "2015", "0.5"}


# ----------------------------------------------------------------------------- run

class _Eng:  # never touched: every DB access is injected below
    pass


@pytest.fixture(autouse=True)
def _brand(monkeypatch):
    monkeypatch.setattr(syn, "_on", lambda: True)
    monkeypatch.setattr(syn, "_hard_stops", lambda b: ["guaranteed pass"])
    monkeypatch.setattr("glitch_signal.config.brand_config",
                        lambda b: {"site_url": "https://example.com", "seo": {"blog_path": "/blog/"}})


def _deps(monkeypatch, *, cands=None, draft_text="FTMO's daily loss limit is 5%.", fail_publish=False):
    calls = {"posts": [], "rows": [], "outcomes": [], "fetched": []}

    async def merged_posts(b, engine=None):
        return POSTS

    async def candidates(b, lever, engine=None):
        return cands or []

    async def fetch(url, b):
        calls["fetched"].append(url)
        return PAGE

    async def complete(prompt):
        assert "the only facts you may use" in prompt
        return draft_text

    async def create_post(b, platform, *, text, idem_key):
        if fail_publish:
            raise RuntimeError("buffer 500")
        calls["posts"].append((platform, text, idem_key))
        return f"bf-{platform}", "sending"

    async def add_candidate(b, **kw):
        calls["rows"].append(kw)
        return f"cid-{len(calls['rows'])}"

    async def record_outcome(cid, b, lever, **kw):
        calls["outcomes"].append((cid, kw))

    monkeypatch.setattr(syn.store, "add_candidate", add_candidate)
    monkeypatch.setattr(syn.store, "record_outcome", record_outcome)
    return calls, {"merged_posts": merged_posts, "candidates": candidates, "fetch": fetch,
                   "complete": complete, "create_post": create_post, "now": NOW}


async def test_a_run_posts_x_for_the_oldest_post_with_the_link_appended(monkeypatch):
    calls, deps = _deps(monkeypatch)
    out = await syn.run("ge", {}, engine=_Eng(), deps=deps)
    assert out["actions"][0]["posted"] == "bf-x (sending)"
    platform, text, idem = calls["posts"][0]
    assert platform == "x" and text.endswith("\n\nhttps://example.com/blog/a/")
    assert idem == "offpage:syndicate:ge:a:x"
    assert calls["rows"][0]["status"] == "posted_by_agent" and calls["rows"][0]["source_ref"] == "a"
    assert calls["fetched"] == ["https://example.com/blog/a/"]


async def test_a_refused_draft_leaves_no_row_so_tomorrow_retries(monkeypatch):
    calls, deps = _deps(monkeypatch, draft_text="The daily limit is 6%, guaranteed pass.")
    out = await syn.run("ge", {}, engine=_Eng(), deps=deps)
    assert out["actions"][0]["refused"] == ["unsupported_figures:6%", "hard_stop:guaranteed pass"]
    assert calls["posts"] == [] and calls["rows"] == []


async def test_a_failed_publish_leaves_a_skipped_row_for_a_human(monkeypatch):
    calls, deps = _deps(monkeypatch, fail_publish=True)
    out = await syn.run("ge", {}, engine=_Eng(), deps=deps)
    assert out["actions"][0]["error"].startswith("publish_failed: buffer 500")
    assert calls["rows"][0]["status"] == "skipped" and calls["outcomes"][0][1]["error"] == "buffer 500"


async def test_dry_run_drafts_and_checks_but_posts_nothing(monkeypatch):
    calls, deps = _deps(monkeypatch)
    out = await syn.run("ge", {"dry_run": True}, engine=_Eng(), deps=deps)
    assert out["dry_run"] and out["actions"][0]["draft"] and calls["posts"] == [] and calls["rows"] == []


async def test_kill_switch_and_missing_site_url_refuse(monkeypatch):
    monkeypatch.setattr(syn, "_on", lambda: False)
    assert (await syn.run("ge", {}, engine=_Eng()))["skipped"] == "social_or_publish_disabled"
    monkeypatch.setattr(syn, "_on", lambda: True)
    monkeypatch.setattr("glitch_signal.config.brand_config", lambda b: {})
    assert (await syn.run("ge", {}, engine=_Eng()))["skipped"] == "no_site_url"


async def test_all_syndicated_is_a_named_refusal(monkeypatch):
    cands = [_c(s, k) for s in "abc" for k in ("x", "linkedin")]
    _, deps = _deps(monkeypatch, cands=cands)
    assert (await syn.run("ge", {}, engine=_Eng(), deps=deps))["skipped"] == "all_syndicated"


def test_small_counts_the_page_spells_out_are_supported():
    page = "FundingPips Zero requires seven qualifying days and The5ers High Stakes three."
    assert syn.check("FundingPips Zero: 7 days. The5ers: 3.", platform="x", page_text=page, hard_stops=[]) == []
    assert syn.check("FundingPips Zero: 8 days.", platform="x", page_text=page, hard_stops=[]) == ["unsupported_figures:8"]


async def test_drafter_falls_through_tiers_and_fails_loudly(monkeypatch):
    seen = []

    async def complete_messages(msgs, *, tier, **kw):
        seen.append(tier)
        if tier == "simple":
            raise RuntimeError("empty completion from a reasoning model")
        return "A grounded line."

    monkeypatch.setattr("glitch_signal.agent.loop.llm.complete_messages", complete_messages)
    assert await syn._default_complete("p") == "A grounded line." and seen == ["simple", "complex"]

    async def always_empty(msgs, *, tier, **kw):
        return ""

    monkeypatch.setattr("glitch_signal.agent.loop.llm.complete_messages", always_empty)
    with pytest.raises(RuntimeError):
        await syn._default_complete("p")


async def test_an_over_long_draft_gets_one_shorten_pass():
    prompts = []

    async def complete(prompt):
        prompts.append(prompt)
        return ("x" * 300) if len(prompts) == 1 else "short and grounded"

    out = await syn.draft("x", title="T", page_text=PAGE, complete=complete)
    assert out == "short and grounded" and "at most 240 characters" in prompts[1]
