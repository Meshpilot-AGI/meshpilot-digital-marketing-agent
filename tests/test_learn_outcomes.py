"""Strategy revision from MEASURED outcomes — the step that closes the loop.

`curator.py` distils episodes: the agent's own record of what it DID, which can only ever produce
lessons about intentions. This one reads what happened. Its most important behaviour is refusing to
conclude anything when the samples cannot support it.
"""
from glitch_signal.agent.learn import outcomes
from glitch_signal.agent.social import performance
from glitch_signal.agent.social.matrix import MIN_SAMPLES_TO_RANK


def _cell(kind, pillar, n, mean):
    return {"asset_kind": kind, "pillar": pillar, "n": n, "mean_engagement": mean,
            "total_engagement": n * mean}


# ── the evidence gate ───────────────────────────────────────────────────────────────────────────
def test_a_single_rankable_cell_is_not_enough_to_conclude():
    """One ranked cell has nothing to be better THAN."""
    s = performance.summarise([_cell("comparison", "p", MIN_SAMPLES_TO_RANK, 4.0)])
    assert s["cells_rankable"] == 1 and s["can_conclude"] is False


def test_two_rankable_cells_can_conclude():
    s = performance.summarise([_cell("comparison", "p", MIN_SAMPLES_TO_RANK, 4.0),
                               _cell("statement", "p", MIN_SAMPLES_TO_RANK, 1.0)])
    assert s["can_conclude"] is True and s["ranked"][0]["asset_kind"] == "comparison"


def test_under_sampled_cells_are_reported_but_never_ranked():
    """A mean over one post is not a ranking; ordering those is superstition."""
    s = performance.summarise([_cell("comparison", "p", 1, 99.0),
                               _cell("statement", "p", 1, 0.0)])
    assert s["ranked"] == [] and len(s["under_sampled"]) == 2 and s["can_conclude"] is False


def test_evidence_block_states_there_is_none_rather_than_being_empty():
    """An empty evidence section reads to a model as an invitation to use its priors — which is
    exactly how an unfounded lesson gets written down as durable."""
    block = performance.evidence_block(performance.summarise([]))
    assert "NOT ENOUGH EVIDENCE" in block and "Draw NO conclusions" in block


def test_evidence_block_discloses_that_reach_is_unavailable():
    """Engagement here is absolute, not per-impression — the reader must not take it as a rate."""
    s = performance.summarise([_cell("a", "p", 5, 1.0), _cell("b", "p", 5, 2.0)])
    assert "reach is not available" in performance.evidence_block(s)


# ── the curator ─────────────────────────────────────────────────────────────────────────────────
async def test_curator_writes_nothing_without_enough_evidence():
    """THE point of this module. Below threshold it must not hedge, soften, or note a trend."""
    called = {"llm": 0}

    async def by_cell(brand, *, engine=None):
        return [_cell("comparison", "p", 1, 9.0)]

    async def complete(*a, **k):
        called["llm"] += 1
        return "[]"

    out = await outcomes.curate_performance("ge", by_cell=by_cell, complete=complete)
    assert out["wrote"] == 0 and out["reason"] == "insufficient evidence"
    assert called["llm"] == 0                      # never even asked the model


async def test_curator_writes_lessons_when_the_evidence_supports_it():
    written = []

    async def by_cell(brand, *, engine=None):
        return [_cell("comparison", "p", 6, 4.0), _cell("statement", "p", 5, 1.0)]

    async def complete(prompt, **k):
        assert "MEASURED PERFORMANCE" in prompt
        return '[{"key":"comparison-leads","content":"Comparison posts lead on n=6","importance":0.7}]'

    async def remember(brand, content, key, importance):
        written.append((key, content))

    out = await outcomes.curate_performance("ge", by_cell=by_cell, complete=complete,
                                            remember=remember)
    assert out["wrote"] == 1
    assert written[0][0].startswith("perf:")       # stable key → updates, never duplicates


async def test_curator_survives_an_llm_failure():
    async def by_cell(brand, *, engine=None):
        return [_cell("a", "p", 5, 4.0), _cell("b", "p", 5, 1.0)]

    async def complete(*a, **k):
        raise RuntimeError("model down")

    out = await outcomes.curate_performance("ge", by_cell=by_cell, complete=complete)
    assert out["wrote"] == 0 and "llm" in out["reason"]


async def test_curator_ignores_malformed_lessons():
    written = []

    async def by_cell(brand, *, engine=None):
        return [_cell("a", "p", 5, 4.0), _cell("b", "p", 5, 1.0)]

    async def complete(*a, **k):
        return '[{"key":"","content":"no key"},{"key":"ok","content":""},{"key":"good","content":"c"}]'

    async def remember(brand, content, key, importance):
        written.append(key)

    out = await outcomes.curate_performance("ge", by_cell=by_cell, complete=complete,
                                            remember=remember)
    assert out["wrote"] == 1 and written == ["perf:good"]


async def test_curator_caps_the_number_of_lessons():
    written = []

    async def by_cell(brand, *, engine=None):
        return [_cell("a", "p", 5, 4.0), _cell("b", "p", 5, 1.0)]

    async def complete(*a, **k):
        return ("[" + ",".join(f'{{"key":"k{i}","content":"c{i}"}}' for i in range(9)) + "]")

    async def remember(brand, content, key, importance):
        written.append(key)

    await outcomes.curate_performance("ge", by_cell=by_cell, complete=complete, remember=remember)
    assert len(written) == 3
