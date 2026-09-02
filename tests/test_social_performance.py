"""`by_cell`'s query shape — platform stays a comparison dimension, null pillars and unmeasured
metric rows never become rankable cells, and a real query failure never looks like "no evidence".
"""
from __future__ import annotations

import pytest

from glitch_signal.agent.social import performance


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeConn:
    def __init__(self, sink, rows, exc=None):
        self._sink, self._rows, self._exc = sink, rows, exc

    async def execute(self, stmt, params=None):
        self._sink.append((str(stmt), params))
        if self._exc:
            raise self._exc
        return _FakeResult(self._rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeEngine:
    def __init__(self, rows=None, exc=None):
        self.calls = []
        self._rows, self._exc = rows or [], exc

    def connect(self):
        return _FakeConn(self.calls, self._rows, self._exc)


# ── platform stays a dimension (finding: "Cross-platform outcomes are incomparable") ──────────────
async def test_by_cell_groups_by_platform_not_just_asset_kind_and_pillar():
    """Pooling Facebook and Instagram into one mean lets platform mix, not the content choice,
    decide which cell looks best — platform must be selected and grouped on, never pooled away."""
    eng = _FakeEngine(rows=[])
    await performance.by_cell("ge", engine=eng)
    sql = eng.calls[0][0].lower()
    assert "m.platform" in sql
    assert "group by 1, 2, 3" in sql


# ── null pillars excluded (finding: "Null pillars become ranked cells") ────────────────────────────
async def test_by_cell_excludes_campaigns_with_no_pillar():
    """A campaign with an asset_kind but no pillar (matrix-selection fallback) is not a matrix cell
    and must not be admitted into the GROUP BY as a rankable (asset_kind, NULL) group."""
    eng = _FakeEngine(rows=[])
    await performance.by_cell("ge", engine=eng)
    sql = eng.calls[0][0].lower()
    assert "choices->>'pillar' is not null" in sql


# ── unmeasured rows excluded (finding: "Missing metrics become zero engagement") ───────────────────
async def test_by_cell_excludes_rows_where_every_engagement_component_is_null():
    """A metric row where likes/comments/shares/clicks are ALL null was never actually measured (a
    failed or partial collector read), not a genuine zero-engagement post. Counting it drags the
    cell's mean down and inflates the sample count on fabricated observations."""
    eng = _FakeEngine(rows=[])
    await performance.by_cell("ge", engine=eng)
    sql = eng.calls[0][0].lower()
    assert ("not (m.likes is null and m.comments is null and m.shares is null "
            "and m.clicks is null)") in sql


# ── query failure distinguishable from no evidence (finding: "Query failures mimic insufficient
#    evidence") ─────────────────────────────────────────────────────────────────────────────────
async def test_by_cell_raises_a_typed_error_on_query_failure_instead_of_returning_empty():
    """An empty list must mean 'the loop looked and found nothing'. A DB/SQL failure has to surface
    as something a caller can tell apart from that, or an outage silently disables learning."""
    eng = _FakeEngine(exc=RuntimeError("connection refused"))
    with pytest.raises(performance.PerformanceQueryError):
        await performance.by_cell("ge", engine=eng)


def _cell(kind, pillar, platform, n, mean):
    return {"asset_kind": kind, "pillar": pillar, "platform": platform, "n": n,
            "mean_engagement": mean, "total_engagement": n * mean}


# ── ranking never crosses platforms (finding: "Rank incomparable platform cells") ──────────────────
def test_summarise_never_concludes_from_two_different_platforms_alone():
    """A Facebook cell and an Instagram cell for the same (asset_kind, pillar) choice have
    incomparable absolute engagement scales — one rankable cell per platform must not satisfy
    can_conclude just because two platforms are present."""
    s = performance.summarise([
        _cell("comparison", "p", "facebook", 5, 50.0),
        _cell("comparison", "p", "instagram", 5, 5.0),
    ])
    assert s["can_conclude"] is False


def test_summarise_ranks_within_a_platform_once_two_choices_exist_there():
    """Two distinct content choices measured on the SAME platform are a valid comparison."""
    s = performance.summarise([
        _cell("comparison", "p", "facebook", 5, 50.0),
        _cell("statement", "p", "facebook", 5, 5.0),
        _cell("comparison", "p", "instagram", 5, 999.0),   # lone Instagram cell: not comparable
    ])
    assert s["can_conclude"] is True
    facebook_ranked = [c for c in s["ranked"] if c["platform"] == "facebook"]
    assert [c["asset_kind"] for c in facebook_ranked] == ["comparison", "statement"]


def test_summarise_never_ranks_an_instagram_cell_above_a_facebook_cell():
    """Guards the exact shape of the bug: a single, much larger Instagram mean must never be
    reported ahead of a smaller Facebook mean as though the platforms were interchangeable."""
    s = performance.summarise([
        _cell("comparison", "p", "facebook", 5, 10.0),
        _cell("statement", "p", "facebook", 5, 1.0),
        _cell("comparison", "p", "instagram", 5, 1000.0),
    ])
    # the Instagram cell has no same-platform partner, so it must never lead the ranked list
    assert s["ranked"][0]["platform"] == "facebook"
    assert s["ranked"][0]["asset_kind"] == "comparison"
