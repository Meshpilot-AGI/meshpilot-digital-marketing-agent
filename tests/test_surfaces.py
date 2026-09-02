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


def test_module_names_no_industry_or_platform():
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
    for term in ("reddit", "propfirm", "prop firm", "trading", "glitchexecutor"):
        assert term not in code, f"surface scoring hardcodes {term!r}"
