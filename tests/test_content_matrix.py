"""The content matrix — deliberate variation so outcomes are attributable.

Two ends of one problem. MEASUREMENT: a metric is only useful if you can say what produced it.
VARIANCE: an LLM asked freely converges on the same shape, and with no variation every measurement
describes that one shape — the loop has no contrast to learn from however well it measures.
"""
from glitch_signal.agent.social import matrix

P = ("rule mechanics", "how accounts die")


def test_grid_is_every_kind_by_every_pillar():
    assert len(matrix.cells(P)) == len(matrix.ASSET_KINDS) * len(P)


def test_no_pillars_falls_back_rather_than_producing_an_empty_grid():
    """A brand that has not declared pillars must still get variation, not zero cells."""
    assert len(matrix.cells([])) == len(matrix.ASSET_KINDS) * len(matrix.DEFAULT_PILLARS)


def test_selection_is_least_sampled_first():
    hist = [{"asset_kind": "comparison", "pillar": "rule mechanics"}]
    assert matrix.next_cell(P, hist) != matrix.Cell("comparison", "rule mechanics")


def test_selection_is_deterministic():
    """Reproducible selection is what makes the schedule auditable — two runs with the same history
    must choose the same cell, or 'we covered the matrix' is unverifiable."""
    hist = [{"asset_kind": "comparison", "pillar": "rule mechanics"}]
    assert matrix.next_cell(P, hist) == matrix.next_cell(P, hist)


def test_selection_covers_the_whole_grid_before_repeating():
    """The core property: every cell is tried once before any is tried twice."""
    hist: list[dict] = []
    grid_size = len(matrix.cells(P))
    for _ in range(grid_size):
        c = matrix.next_cell(P, hist)
        hist.append(c.as_choices())
    assert len({(h["asset_kind"], h["pillar"]) for h in hist}) == grid_size


def test_unknown_history_entries_are_ignored():
    """Choices from a previous strategy (a pillar that no longer exists) must not skew sampling."""
    hist = [{"asset_kind": "comparison", "pillar": "a-retired-pillar"}, {"nonsense": 1}, {}]
    assert matrix.next_cell(P, hist) == matrix.next_cell(P, [])


def test_coverage_reports_exploring_until_the_grid_is_sampled():
    assert matrix.coverage(P, [])["exploring"] is True
    assert matrix.coverage(P, [])["unsampled"] == len(matrix.cells(P))


def test_coverage_stays_exploring_below_the_ranking_threshold():
    """One observation cannot rank a cell. An agent that 'exploits' on n=1 is amplifying noise into
    a durable lesson — so the loop must be able to say 'still exploring' honestly."""
    hist = [c.as_choices() for c in matrix.cells(P)]          # every cell sampled exactly once
    cov = matrix.coverage(P, hist)
    assert cov["unsampled"] == 0
    assert cov["rankable"] == 0 and cov["exploring"] is True


def test_coverage_becomes_rankable_at_the_threshold():
    cell = matrix.cells(P)[0]
    hist = [cell.as_choices()] * matrix.MIN_SAMPLES_TO_RANK
    assert matrix.coverage(P, hist)["rankable"] == 1


def test_directive_binds_the_shape_and_pillar():
    d = matrix.directive(matrix.Cell("comparison", "rule mechanics"))
    assert "comparison" in d and "rule mechanics" in d
    assert "binding" in d.lower()          # a suggestion would be ignored; this must be a constraint
