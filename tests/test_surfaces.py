"""TARGET-2 — surface scoring: the opinion, the honesty about it, and the posting gate."""
from __future__ import annotations

import json

from glitch_signal.agent.social import surfaces
from glitch_signal.agent.social.matrix import MIN_SAMPLES_TO_RANK


# ── the scoring opinion ──
def test_a_small_dense_room_beats_a_big_sparse_one():
    """The whole opinion of this module, and the reason it exists.

    r/Forex (547,438) is ~19x r/PropFirmTester (28,258). If the brand's queries keep surfacing
    threads in the smaller room, it must win — reach you cannot address is not reach. A
    reach-ranked list would send every brand to the biggest generic room, which is the broadcast
    behaviour surfaces replace.
    """
    big, _ = surfaces.fit(signal_count=2, total_signals=100, reach=547_438)
    small, _ = surfaces.fit(signal_count=40, total_signals=100, reach=28_258)
    assert small > big
    assert small > big * 10          # decisively, not marginally


def test_reach_only_modulates_it_never_dominates():
    """Same relevance, 100x the reach: better, but not overwhelmingly — participation is bounded by
    attention in a thread, not by the room's size."""
    small, _ = surfaces.fit(10, 100, 5_000)
    huge, _ = surfaces.fit(10, 100, 500_000)
    assert huge > small
    assert huge < small * 2


def test_reach_norm_is_logarithmic():
    """1k→10k should matter far more than 500k→5M."""
    lo = surfaces.reach_norm(10_000) - surfaces.reach_norm(1_000)
    hi = surfaces.reach_norm(5_000_000) - surfaces.reach_norm(500_000)
    assert lo > hi


def test_unknown_reach_earns_nothing():
    """Absent size is not assumed to be large — or small-but-fine. It simply earns no modifier."""
    assert surfaces.reach_norm(None) == 0.0
    assert surfaces.reach_norm(0) == 0.0


def test_no_signals_scores_zero_not_an_error():
    score, comp = surfaces.fit(0, 0, 50_000)
    assert score == 0.0 and comp["relevance_density"] == 0.0


def test_components_explain_the_ranking():
    """A ranking must be explainable without re-deriving the number."""
    _, comp = surfaces.fit(7, 20, 1000)
    for k in ("relevance_density", "reach_norm", "signal_count", "total_signals", "reach", "formula"):
        assert k in comp


# ── honesty about what the score is ──
class _Conn:
    def __init__(self, sink, rows):
        self._sink, self._rows = sink, rows

    async def execute(self, stmt, params=None):
        self._sink.append((str(stmt), params))
        return _Res(self._rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Res:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _Engine:
    def __init__(self, rows=None):
        self.calls = []
        self._rows = rows or []

    def begin(self):
        return _Conn(self.calls, self._rows)

    def connect(self):
        return _Conn(self.calls, self._rows)


_ROWS = [
    {"id": "1", "handle": "roomA", "reach": 500_000, "signal_count": 2,
     "self_promo_allowed": None, "status": "candidate"},
    {"id": "2", "handle": "roomB", "reach": 20_000, "signal_count": 30,
     "self_promo_allowed": True, "status": "active"},
]


async def test_scores_are_provisional_until_measured():
    """Mirrors the curator: below MIN_SAMPLES_TO_RANK we have a prior, not a finding. Nothing has
    been posted to these rooms, so today everything is provisional and callers must say so."""
    eng = _Engine(_ROWS)
    out = await surfaces.rescore("b", engine=eng)
    assert out and all(r["provisional"] for r in out)


async def test_enough_measured_outcomes_clears_provisional():
    eng = _Engine(_ROWS)
    out = await surfaces.rescore("b", measured={"roomB": MIN_SAMPLES_TO_RANK}, engine=eng)
    by = {r["handle"]: r for r in out}
    assert by["roomB"]["provisional"] is False
    assert by["roomA"]["provisional"] is True


async def test_rescore_uses_observed_signals_not_assertions():
    eng = _Engine(_ROWS)
    await surfaces.rescore("b", engine=eng)
    joined = " ".join(s.lower() for s, _ in eng.calls)
    assert "from signal_item" in joined     # density comes from what sensing actually saw


async def test_rescore_ranks_the_denser_room_first():
    eng = _Engine(_ROWS)
    out = await surfaces.rescore("b", engine=eng)
    assert out[0]["handle"] == "roomB"      # 30/32 signals, despite 25x less reach


# ── the posting gate ──
async def test_postable_only_excludes_unknown_permission():
    """NULL self_promo_allowed is UNKNOWN, and unknown is not permission."""
    eng = _Engine([])
    await surfaces.top("b", postable_only=True, engine=eng)
    sql, params = eng.calls[0]
    assert "self_promo_allowed is true" in sql.lower()
    assert params["postable_only"] is True


async def test_rules_forbidding_self_promo_make_a_room_read_only():
    """Still worth listening to — never posted into. Decided from the room's stated rules, not our
    appetite for it."""
    eng = _Engine()
    await surfaces.record_rules("b", "subreddit", "x", {"rules": []},
                                self_promo_allowed=False, engine=eng)
    _, params = eng.calls[0]
    assert params["status"] == "read_only"
    json.loads(params["rules"])            # must be valid json for the jsonb cast


async def test_unknown_rules_do_not_mark_a_room_postable():
    eng = _Engine()
    await surfaces.record_rules("b", "subreddit", "x", {}, self_promo_allowed=None, engine=eng)
    _, params = eng.calls[0]
    assert params["status"] == "candidate" and params["allowed"] is None


# ── resilience + neutrality ──
async def test_upsert_is_idempotent_on_rediscovery():
    eng = _Engine()
    await surfaces.upsert_discovered("b", "subreddit",
                                     [{"name": "roomA", "subscribers": 10}], engine=eng)
    sql, _ = eng.calls[0]
    assert "on conflict (brand_id, kind, handle) do update" in sql.lower()


async def test_bookkeeping_failures_never_break_discovery():
    class _Boom:
        def begin(self):
            raise RuntimeError("db down")

    assert await surfaces.upsert_discovered("b", "subreddit", [{"name": "a"}], engine=_Boom()) == 0
    assert await surfaces.rescore("b", engine=_Boom()) == []


def test_module_names_no_industry_or_brand():
    """Multi-BRAND, not platform-agnostic — a deliberate distinction.

    Being platform-aware is fine and unavoidable: rules capture is a Reddit call, and the codebase is
    already platform-shaped (`platforms/buffer.py`, per-platform profiles). What must never appear is
    an INDUSTRY or a BRAND — those are what stop a second tenant reusing this. A subreddit NAME would
    also fail this, since rooms are discovered, never listed in code.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(surfaces))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:]
    code = ast.unparse(tree).lower().replace("glitch_signal", "")
    for term in ("propfirm", "prop firm", "trading", "trader", "glitchexecutor", "r/"):
        assert term not in code, f"surfaces hardcodes an industry/brand/room: {term!r}"


# ── rules capture: the permission gate (TARGET-3) ──
# Real rule text, quoted from what the live API returned 2026-09-02.
_FOREX = {"rules": [{"shortName": "No Promotional Activity or Advertisements",
                     "description": "Do not self promote here. Doing so risks your brand being "
                                    "blacklisted by our spam filters."}],
          "siteRules": ["Spam"]}
_DAYTRADING = {"rules": [
    {"shortName": "No spamming, selling or promoting your product, service or community",
     "description": "No spamming, selling products/services, or sharing affiliate/referral links."},
    {"shortName": "No ChatGPT or AI-Generated Content",
     "description": "Posts or comments created using AI tools like ChatGPT, Claude, or similar "
                    "language models"}]}
_PROPFIRM = {"rules": [], "siteRules": ["Spam"]}


def test_explicit_self_promo_ban_is_detected():
    promo, _ = surfaces.classify_rules(_FOREX)
    assert promo is False


def test_ai_content_ban_is_a_separate_dimension():
    """r/Daytrading bans AI-generated posts outright — a prohibition on what this agent PRODUCES,
    independent of self-promotion. A room can welcome brands and still ban AI text."""
    promo, ai = surfaces.classify_rules(_DAYTRADING)
    assert promo is False and ai is False


def test_a_room_with_no_rules_is_unknown_not_permitted():
    """Silence is not consent. r/propfirm publishes no rules of its own; that grants nothing."""
    assert surfaces.classify_rules(_PROPFIRM) == (None, None)
    assert surfaces.classify_rules({}) == (None, None)


def test_classifier_can_never_grant_permission():
    """The asymmetry that protects the account: a false NO costs one room, a false YES costs the
    account. A keyword scan is nowhere near good enough to let a machine grant itself permission to
    post publicly under the brand's name — `True` stays a deliberate human act."""
    for payload in (_FOREX, _DAYTRADING, _PROPFIRM, {}, {"rules": [
            {"shortName": "Self promotion welcome", "description": "Feel free to share your product"}]}):
        promo, ai = surfaces.classify_rules(payload)
        assert promo is not True and ai is not True


async def test_either_ban_makes_the_room_read_only():
    for promo, ai in ((False, None), (None, False), (False, False)):
        eng = _Engine()
        await surfaces.record_rules("b", "subreddit", "x", {}, self_promo_allowed=promo,
                                    ai_content_allowed=ai, engine=eng)
        assert eng.calls[0][1]["status"] == "read_only"


async def test_postable_only_requires_both_permissions():
    eng = _Engine([])
    await surfaces.top("b", postable_only=True, engine=eng)
    sql = eng.calls[0][0].lower()
    assert "self_promo_allowed is true" in sql and "ai_content_allowed is true" in sql


async def test_sync_rules_survives_one_unreachable_room():
    """One room failing must not abort the sweep — the rest still get their gate set."""
    eng = _Engine([("roomA",), ("roomB",)])

    async def _fetch(brand_id, handle):
        if handle == "roomA":
            raise RuntimeError("vendor 500")
        return _DAYTRADING

    out = await surfaces.sync_rules("b", fetch=_fetch, engine=eng)
    assert out["checked"] == 2 and out["failed"] == 1 and out["read_only"] == 1


async def test_sync_rules_only_fetches_rooms_without_rules():
    eng = _Engine([])
    await surfaces.sync_rules("b", fetch=None, engine=eng)
    assert "rules_fetched_at is null" in eng.calls[0][0].lower()
