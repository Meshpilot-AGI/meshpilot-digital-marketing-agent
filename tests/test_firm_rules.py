"""Firm-rule knowledge base — the only source of firm thresholds the agent may publish.

A firm threshold is a precise, dated claim about a THIRD PARTY's product, published under an
affiliate relationship. Left to itself the model invents one confidently, and the conscience critic
cannot catch it: its prohibitions cover OUR invented figures, and a competitor's rule reads to it
as an ordinary fact.
"""
from glitch_signal.agent import firms
from tests.test_agent_memory import FakeEngine, _Result, _Row


def _rules():
    return [
        {"firm_id": "ftmo", "firm_name": "FTMO Phase 1", "rule_key": "daily_loss",
         "value_num": 0.05, "value_text": "5% daily loss limit", "stage": "eval",
         "source": "s", "as_of": "2026-09-01"},
        {"firm_id": "apex", "firm_name": "Apex Trader Funding", "rule_key": "max_drawdown",
         "value_num": 0.05, "value_text": "5% maximum drawdown (trailing)", "stage": "eval",
         "source": "s", "as_of": "2026-09-01"},
    ]


async def test_lookup_returns_only_publishable_rows():
    """The engine table holds values that are right for backtesting and WRONG in public — synthetic
    gates, sentinel zeros, and rules for a firm that is not currently selling."""
    eng = FakeEngine()
    eng.queue(_Result(rows=[]))
    await firms.publishable_rules(engine=eng)
    sql, _params = eng.calls[0]
    assert "where publishable" in sql.lower()


async def test_lookup_degrades_to_empty_on_db_failure():
    """No rules must mean 'the post says nothing about thresholds', not a crashed campaign."""
    class _Boom:
        def connect(self):
            raise RuntimeError("db down")
    assert await firms.publishable_rules(engine=_Boom()) == []


def test_rules_block_is_empty_when_there_are_no_rules():
    """An empty 'VERIFIED FIRM RULES' header would invite the model to fill the gap from its own
    priors — which is exactly the failure this table exists to prevent."""
    assert firms.rules_block({}) == ""


def test_rules_block_states_the_hard_prohibition():
    block = firms.rules_block({"FTMO Phase 1": [_rules()[0]]})
    assert "5% daily loss limit" in block
    assert "eval" in block and "2026-09-01" in block          # stage + date are load-bearing
    assert "do not infer, estimate or recall one" in block


def test_rules_block_qualifies_the_stage():
    """Eval and funded rules differ; an unqualified threshold is a different, wrong claim."""
    block = firms.rules_block({"FTMO Phase 1": [_rules()[0]]})
    assert "eval stage" in block


async def test_rules_for_names_matches_what_the_agent_wrote(monkeypatch):
    async def _pub(firm_id=None, *, engine=None):
        return _rules()
    monkeypatch.setattr(firms, "publishable_rules", _pub)
    got = await firms.rules_for_names(["FTMO", "Apex"])
    assert set(got) == {"FTMO Phase 1", "Apex Trader Funding"}


async def test_rules_for_names_yields_nothing_for_a_withheld_firm(monkeypatch):
    """MyForexFunds is pending-relaunch: every rule is withheld, so the agent gets no thresholds
    for it and must write the post without them."""
    async def _pub(firm_id=None, *, engine=None):
        return _rules()
    monkeypatch.setattr(firms, "publishable_rules", _pub)
    assert await firms.rules_for_names(["MyForexFunds"]) == {}


def test_mentioned_finds_firms_in_copy():
    assert set(firms.mentioned("Comparing FTMO and Apex Trader Funding")) == {"ftmo", "apex"}


def test_mentioned_prefers_the_longest_alias():
    """'apex trader funding' must not also register as a second, separate 'apex' hit."""
    assert firms.mentioned("apex trader funding rules") == ["apex"]


def test_mentioned_is_empty_when_no_firm_is_named():
    assert firms.mentioned("a post about broker time resets") == []


def test_mentioned_handles_spacing_variants():
    assert firms.mentioned("the 5ers consistency rule") == ["the5ers"]
    assert firms.mentioned("funding pips zero") == ["fundingpips_zero"]


# ── degenerate-text screening (2026-09-02) ──
def test_a_formatted_zero_is_screened_out_of_the_facts():
    """A published post said "The5ers lists payout cadence as every 0 days" — faithful to a row that
    said exactly that. Grounding guarantees fidelity to our data, not the correctness of it."""
    from glitch_signal.agent import firms

    block = firms.rules_block({"X": [{"firm_name": "X", "stage": "funded",
                                      "rule_key": "payout_cadence",
                                      "value_text": "payouts every 0 days", "as_of": "2026-09-01"}]})
    assert "0 days" not in block


def test_a_correctly_worded_sentinel_is_kept():
    """`payoutCadenceDays: 0` is a deliberate sentinel for ON-DEMAND payouts — a real differentiator.
    The first version of this filter screened on value_num <= 0 and would have suppressed it; the
    row was wrong in its wording, not in what it held."""
    from glitch_signal.agent import firms

    block = firms.rules_block({"X": [{"firm_name": "X", "stage": "funded",
                                      "rule_key": "payout_cadence", "value_num": 0,
                                      "value_text": "on-demand payouts (no fixed cadence)",
                                      "as_of": "2026-09-01"}]})
    assert "on-demand payouts" in block
