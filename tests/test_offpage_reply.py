"""OFFPAGE-2 — listen, score, draft, offer, decide, stand. Nothing here touches a network or a DB."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from glitch_signal.agent.offpage import approvals, listen, reply, standing

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
CFG = {"daily_candidates": 3, "min_gap_hours": 72, "max_age_hours": 48, "offer_ttl_hours": 36,
       "brand_terms": ["Glitch Executor"], "forbidden": list(reply.DEFAULT_FORBIDDEN),
       "product_line": "Glitch Executor — tracks your account against the firm's rules."}


def _item(url, room="propfirm", age_h=3.0, title="Which prop firm has the loosest daily loss rule?",
          excerpt="Looking for a firm with a 5% daily limit.", ext=None):
    return {"external_id": ext or url.rsplit("/", 1)[-1], "surface": room, "title": title,
            "excerpt": excerpt, "url": url, "upvotes": 4, "comment_count": 2,
            "observed_at": NOW, "raw": {"created_utc": (NOW - timedelta(hours=age_h)).timestamp()}}


@pytest.fixture(autouse=True)
def _brand(monkeypatch):
    monkeypatch.setattr("glitch_signal.config.brand_config", lambda b: {
        "offpage": {"audience_queries": ["prop firm drawdown"], "brand_terms": ["Glitch Executor"],
                    "product_line": CFG["product_line"], "reply": {"reddit_username": "glitchExecutor"},
                    "approvals_channel_id": "chan", "approvers": ["owner"]}})


# ----------------------------------------------------------------------------- scoring

def test_score_is_the_product_of_the_four_factors():
    s, parts = reply.score(_item("https://r/1"), now=NOW, surface_fit=0.8, brand_terms=["Glitch Executor"])
    assert parts == {"surface_fit": 0.8, "recency": 1.0, "question": 1.0, "novelty": 1.0} and s == 0.8


@pytest.mark.parametrize("age_h,expect", [(1, 1.0), (12, 0.7), (30, 0.3), (60, 0.0)])
def test_recency_is_a_gate_disguised_as_a_factor(age_h, expect):
    _, parts = reply.score(_item("https://r/1", age_h=age_h), now=NOW, surface_fit=1.0, brand_terms=[])
    assert parts["recency"] == expect


def test_a_thread_that_names_the_brand_or_where_we_commented_scores_zero():
    named = _item("https://r/1", excerpt="I use Glitch Executor for this")
    assert reply.score(named, now=NOW, surface_fit=1.0, brand_terms=["Glitch Executor"])[0] == 0.0
    assert reply.score(_item("https://r/2"), now=NOW, surface_fit=1.0, brand_terms=[],
                       already_commented=True)[0] == 0.0


def test_competitor_already_recommended_halves_novelty_and_statements_score_less_than_questions():
    comp = _item("https://r/1", excerpt="I'd recommend TraderSync for this, works fine")
    assert reply.score(comp, now=NOW, surface_fit=1.0, brand_terms=[])[1]["novelty"] == 0.5
    stmt = _item("https://r/2", title="Passed my challenge today", excerpt="Feels good.")
    assert reply.score(stmt, now=NOW, surface_fit=1.0, brand_terms=[])[1]["question"] == 0.4


def test_unknown_surface_gets_the_provisional_prior():
    assert reply.score(_item("https://r/1"), now=NOW, surface_fit=None, brand_terms=[])[1]["surface_fit"] == 0.5


# ----------------------------------------------------------------------------- picking

def test_pick_honours_budget_room_gap_taken_urls_and_blocked_rooms():
    items = [_item("https://r/a", room="propfirm", age_h=1), _item("https://r/b", room="propfirm", age_h=2),
             _item("https://r/c", room="algotrading", age_h=1), _item("https://r/d", room="daytrading", age_h=1),
             _item("https://r/e", room="blockedroom", age_h=1), _item("https://r/f", room="forex", age_h=1)]
    surfaces = {"blockedroom": {"status": "blocked"}, "propfirm": {"fit_score": 0.9}}
    existing = [{"target_url": "https://r/f", "surface": "forex", "status": "offered",
                 "created_at": NOW - timedelta(hours=100)},
                {"target_url": "https://r/old", "surface": "daytrading", "status": "posted_by_operator",
                 "created_at": NOW - timedelta(hours=10)}]
    picked = reply.pick(items, surfaces=surfaces, existing=existing, cfg=CFG, now=NOW)
    urls = [p[0]["url"] for p in picked]
    assert urls == ["https://r/a", "https://r/c"]        # one per room; f taken; e blocked; daytrading in gap
    assert picked[0][1] == 0.9


def test_daily_budget_counts_todays_candidates():
    existing = [{"target_url": f"https://r/x{i}", "surface": f"room{i}", "status": "offered",
                 "created_at": NOW - timedelta(hours=1)} for i in range(3)]
    assert reply.pick([_item("https://r/new", room="fresh")], surfaces={}, existing=existing, cfg=CFG, now=NOW) == []


# ----------------------------------------------------------------------------- checks

FACTS = "daily_loss_pct: 2 of 6 firms have one.\n- FTMO: 5% (as of 2026-09-01)\n- Apex: none"


@pytest.mark.parametrize("draft,mention_ok,expect", [
    ("FTMO's daily loss limit is 5% of starting balance; check the firm's rules page.", False, []),
    ("FTMO caps it at 4%.", False, ["unsupported_figures:4%"]),
    ("See https://ftmo.com for details.", False, ["contains_url"]),
    ("It's a guaranteed pass if you size down.", False, ["forbidden:guaranteed,guarantee"]),
    ("Glitch Executor tracks this.", False, ["brand_mention_not_allowed"]),
    ("Glitch Executor tracks this. Glitch Executor also alerts.", True, ["brand_mentioned_more_than_once"]),
    ("As an AI, I'd say check the rules.", False, ["breaks_character"]),
])
def test_check(draft, mention_ok, expect):
    assert reply.check(draft, facts=FACTS, thread_text="5% daily limit?", cfg=CFG,
                       mention_allowed=mention_ok) == expect


def test_mention_policy_only_opens_when_allowed_and_asked_and_configured():
    assert "Do NOT mention" in reply.mention_policy(allowed=False, tool_asked=True, product_line="x")
    assert "Do NOT mention" in reply.mention_policy(allowed=True, tool_asked=False, product_line="x")
    assert "ONCE" in reply.mention_policy(allowed=True, tool_asked=True, product_line="x")


def test_rules_excerpt_handles_zernio_shape_and_nothing():
    assert "no rules captured" in reply.rules_excerpt(None)
    txt = reply.rules_excerpt({"rules": [{"shortName": "No self-promotion", "violationReason": "spam"}]})
    assert txt.startswith("- No self-promotion: spam")


# ----------------------------------------------------------------------------- reply.run

def _run_deps(monkeypatch, *, draft_text, items=None, promo=False):
    calls = {"rows": [], "offers": [], "offered": []}

    async def signals(b, engine=None):
        return items if items is not None else [_item("https://r/1", excerpt="Looking for a tracker app with a 5% daily limit.")]

    async def surfaces(b, engine=None):
        return {"propfirm": {"fit_score": 0.9, "self_promo_allowed": promo, "status": "active"}}

    async def recent(b, lever, hours, engine=None):
        return []

    async def facts(title, excerpt, engine=None):
        return FACTS

    async def rules(b, room, engine=None):
        return {"rules": [{"shortName": "Be civil"}]}

    async def complete(prompt):
        assert "SUBREDDIT RULES" in prompt and "Be civil" in prompt
        return draft_text

    async def offer(b, cand):
        calls["offers"].append(cand)
        return "msg-1"

    async def add_candidate(b, **kw):
        calls["rows"].append(kw)
        return "cid-1"

    async def mark_offered(cid, mid, ttl_hours, engine=None):
        calls["offered"].append((cid, mid, ttl_hours))

    monkeypatch.setattr(reply.store, "add_candidate", add_candidate)
    monkeypatch.setattr(reply.store, "mark_offered", mark_offered)
    return calls, {"signals": signals, "surfaces": surfaces, "recent": recent, "facts": facts,
                   "rules": rules, "complete": complete, "offer": offer, "now": NOW}


async def test_run_drafts_records_and_offers(monkeypatch):
    calls, deps = _run_deps(monkeypatch, draft_text="FTMO's limit is 5%; check the rules page before sizing.")
    out = await reply.run("ge", {}, deps=deps)
    assert out["offered"] == 1 and out["refused"] == []
    row = calls["rows"][0]
    assert row["status"] == "drafted" and row["target_url"] == "https://r/1" and row["surface"] == "propfirm"
    assert row["meta"]["mention_allowed"] is False and row["meta"]["rules_hash"]
    assert calls["offered"] == [("cid-1", "msg-1", 36)]


async def test_run_refuses_a_brand_mention_when_the_room_forbids_promo(monkeypatch):
    calls, deps = _run_deps(monkeypatch, draft_text="Glitch Executor does exactly this, 5% tracked live.", promo=False)
    out = await reply.run("ge", {}, deps=deps)
    assert out["offered"] == 0 and out["refused"][0]["refused"] == ["brand_mention_not_allowed"]
    assert calls["rows"] == []


async def test_run_allows_one_mention_when_promo_ok_and_tool_asked(monkeypatch):
    calls, deps = _run_deps(monkeypatch, draft_text="Glitch Executor does this — I'm on the team. FTMO is 5%.", promo=True)
    out = await reply.run("ge", {}, deps=deps)
    assert out["offered"] == 1 and calls["rows"][0]["meta"]["mention_allowed"] is True


async def test_run_dry_run_writes_nothing(monkeypatch):
    calls, deps = _run_deps(monkeypatch, draft_text="FTMO's limit is 5%.")
    out = await reply.run("ge", {"dry_run": True}, deps=deps)
    assert out["drafts"] and calls["rows"] == [] and calls["offers"] == []


async def test_run_without_signals_names_the_reason(monkeypatch):
    calls, deps = _run_deps(monkeypatch, draft_text="x", items=[])
    assert (await reply.run("ge", {}, deps=deps))["skipped"] == "no_signals"


# ----------------------------------------------------------------------------- approvals

def test_card_is_under_discords_limit_and_carries_the_legend():
    c = approvals.card("ge", {"surface": "propfirm", "target_url": "https://r/1", "draft": "x" * 3000,
                              "score": 0.81, "draft_meta": {"title": "T", "score_parts": {"recency": 1.0},
                                                             "mention_allowed": False}})
    assert len(c) <= 2000 and "r/propfirm" in c and "score 0.81" in c and "❌ no" in c


async def test_read_decision_honours_precedence_and_only_approvers():
    seen = {"📤": [{"id": "bot"}], "✏️": [{"id": "stranger"}], "❌": [{"id": "owner"}], "✅": [{"id": "owner"}]}

    async def api(method, path, token, json_body=None):
        for emoji, users in seen.items():
            if path.endswith(approvals.quote(emoji)):
                return users
        return []

    assert await approvals.read_decision("ge", "m1", api=api) == "rejected"
    seen["❌"] = []
    assert await approvals.read_decision("ge", "m1", api=api) == "approved"
    seen["✅"] = []
    assert await approvals.read_decision("ge", "m1", api=api) is None


async def test_offer_posts_the_card_and_seeds_the_legend(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "t")
    calls = []

    async def api(method, path, token, json_body=None):
        calls.append((method, path))
        return {"id": "m9"} if method == "POST" else {}

    mid = await approvals.offer("ge", {"surface": "propfirm", "target_url": "u", "draft": "d", "score": 0.5,
                                       "draft_meta": {}}, api=api)
    assert mid == "m9" and calls[0] == ("POST", "/channels/chan/messages")
    assert sum(1 for m, p in calls if m == "PUT" and p.endswith("/@me")) == 4


async def test_decide_tick_expires_reads_and_reoffers(monkeypatch):
    state = {"statuses": []}

    async def expire_stale(b, lever, engine=None):
        return ["old"]

    async def by_status(b, lever, statuses, engine=None):
        if statuses == ["offered"]:
            return [{"id": "c1", "discord_msg_id": "m1", "target_url": "u1"}]
        return [{"id": "c2", "created_at": NOW}, {"id": "c3", "created_at": NOW - timedelta(hours=40)}]

    async def set_status(cid, status, decided=False, engine=None):
        state["statuses"].append((cid, status))

    async def mark_offered(cid, mid, ttl_hours, engine=None):
        state["statuses"].append((cid, f"offered:{mid}"))

    async def read(b, mid):
        return "posted_by_operator"

    async def offer(b, c):
        return "m2"

    monkeypatch.setattr(approvals.store, "expire_stale", expire_stale)
    monkeypatch.setattr(approvals.store, "by_status", by_status)
    monkeypatch.setattr(approvals.store, "set_status", set_status)
    monkeypatch.setattr(approvals.store, "mark_offered", mark_offered)
    monkeypatch.setattr(approvals, "datetime", _FrozenDT)
    out = await approvals.run("ge", {}, deps={"read_decision": read, "offer": offer})
    assert out["decided"] == [{"id": "c1", "status": "posted_by_operator", "url": "u1"}]
    assert ("c1", "posted_by_operator") in state["statuses"] and ("c2", "offered:m2") in state["statuses"]
    assert ("c3", "expired") in state["statuses"] and out["expired"] == ["old", "c3"]


class _FrozenDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


# ----------------------------------------------------------------------------- standing

def test_stage_is_derived_from_evidence():
    assert standing.stage_for(None, [])[0] == "R0"
    weak = {"comment_karma": 41, "account_age_days": 133, "approvals_30d": 25, "rejections_30d": 0}
    st, ev = standing.stage_for(weak, [])
    assert st == "R0" and ev["karma"] == "41/100" and ev["age_days"] == "133/180"
    strong = {"comment_karma": 150, "account_age_days": 200, "approvals_30d": 25, "rejections_30d": 1}
    assert standing.stage_for(strong, [])[0] == "R1"
    assert standing.stage_for(strong, [{"status": "posted_by_agent"}] * 30)[0] == "R2"
    # a removal at the head of the history breaks the run — back to R1 even with 30 clean behind it
    assert standing.stage_for(strong, [{"status": "removed"}] + [{"status": "posted_by_agent"}] * 30)[0] == "R1"
    assert standing.stage_for({**strong, "rejections_30d": 3}, [])[0] == "R0"


async def test_standing_run_measures_and_counts(monkeypatch):
    rows = []

    async def user(name):
        assert name == "glitchExecutor"
        return {"created_utc": (NOW - timedelta(days=133)).timestamp(), "comment_karma": 41, "link_karma": 1}

    async def recent(b, lever, hours, engine=None):
        return [{"status": "approved"}, {"status": "posted_by_operator"}, {"status": "rejected"}, {"status": "expired"}]

    async def record_standing(b, kind, engine=None, **row):
        rows.append(row)

    async def history(b, lever, engine=None):
        return []

    monkeypatch.setattr(standing.store, "record_standing", record_standing)
    out = await standing.run("ge", {}, deps={"user": user, "recent": recent, "history": history, "now": NOW})
    assert out["stage"] == "R0" and rows[0]["approvals_30d"] == 2 and rows[0]["rejections_30d"] == 1
    assert rows[0]["account_age_days"] == 133 and out["evidence"]["approvals_30d"] == "2/20"


# ----------------------------------------------------------------------------- listen

async def test_listen_records_posts_and_communities_per_query_and_survives_a_failure():
    calls = {"posts": [], "comms": [], "synced": False}

    async def search_posts(q, **kw):
        if q == "bad":
            raise RuntimeError("429")
        return {"posts": [{"id": "p1", "subreddit": "propfirm", "title": "t"}]}

    async def search_communities(q, **kw):
        return {"communities": [{"name": "propfirm", "subscribers": 39000}]}

    async def record(b, source, kind, items, query="", engine=None):
        calls["posts"].append((source, kind, query, len(items)))
        return len(items)

    async def upsert(b, kind, rooms, engine=None):
        calls["comms"].append((kind, len(rooms)))
        return len(rooms)

    async def rescore(b, engine=None):
        return []

    async def sync_rules(b, limit=10, engine=None):
        calls["synced"] = True
        return {"fetched": 1}

    import glitch_signal.config as config
    orig = config.brand_config
    config.brand_config = lambda b: {"offpage": {"audience_queries": ["prop firm drawdown", "bad"]}}
    try:
        out = await listen.run("ge", {}, deps={"search_posts": search_posts, "search_communities": search_communities,
                                                "record": record, "upsert": upsert, "rescore": rescore,
                                                "sync_rules": sync_rules})
    finally:
        config.brand_config = orig
    assert out["posts"] == 1 and out["communities"] == 1 and calls["synced"]
    assert out["errors"] == ["bad: 429"] and calls["posts"][0] == ("reddit", "post", "prop firm drawdown", 1)


def test_list_markers_are_not_figures():
    assert reply.check("Two things:\n1. FTMO is 5%.\n2. Check the rules page.", facts=FACTS,
                       thread_text="", cfg=CFG, mention_allowed=False) == []


async def test_an_over_long_reply_gets_one_shorten_pass(monkeypatch):
    prompts = []

    async def complete(prompt):
        prompts.append(prompt)
        return ("FTMO is 5%. " * 120) if len(prompts) == 1 else "FTMO is 5%. Check the rules page."

    calls, deps = _run_deps(monkeypatch, draft_text="unused")
    deps["complete"] = complete
    out = await reply.run("ge", {"dry_run": True}, deps=deps)
    assert out["drafts"][0]["draft"] == "FTMO is 5%. Check the rules page." and "at most 1200" in prompts[1]


def test_units_are_not_facts_and_trim_ends_on_a_sentence():
    assert reply.check("That 47.7% number needs a bigger sample.", facts="", thread_text="hit 47.7 percent",
                       cfg=CFG, mention_allowed=False) == []
    body = "First point here. Second point there. Third point everywhere."
    assert reply.trim_to(body, 40) == "First point here. Second point there."
    assert reply.trim_to(body, 200) == body
