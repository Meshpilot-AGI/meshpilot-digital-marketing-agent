"""JOBS-3 acceptance — the work-auth gate and the two-pass rule.

Design: docs/plans/2026-09-15-job-application-agent.md §§ 2, 11.
"""
from __future__ import annotations

import pytest

from glitch_signal.agent.jobs import score, workauth

CFG = {
    "min_score": 4.0,
    "work_authorization": {"authorized_in": ["Canada"], "needs_sponsorship_outside": True},
}


# --- work authorization: only ONE verdict blocks ---------------------------------------

def test_role_in_authorized_country_is_not_blocked():
    v = workauth.classify("Must be authorized to work in Canada.", "Toronto, ON, Canada", CFG)
    assert v["verdict"] == workauth.NOT_NEEDED
    assert not v["hard_stop"]


def test_generic_authorization_requirement_in_home_country_is_not_a_refusal():
    """THE subtle case. 'must be authorized to work in Canada' is a requirement the operator MEETS.
    Reading it as a refusal inverts the check and deletes the entire domestic market."""
    jd = "We are unable to sponsor visas. Must be legally authorized to work in Canada."
    v = workauth.classify(jd, "Remote, Canada", CFG)
    assert v["verdict"] == workauth.NOT_NEEDED
    assert not v["hard_stop"], "a Canadian role must never hard-stop, even if the JD refuses sponsorship"


def test_explicit_refusal_outside_authorized_is_the_only_hard_stop():
    jd = "This role is based in Austin. We are unable to sponsor visas for this position."
    v = workauth.classify(jd, "Austin, TX, United States", CFG)
    assert v["verdict"] == workauth.NO_SPONSORSHIP
    assert v["hard_stop"]
    assert "unable to sponsor" in (v["evidence"] or "").lower()


def test_silence_is_neutral_not_a_refusal():
    """Most JDs never mention sponsorship. Treating silence as a block erases most of the market."""
    v = workauth.classify("Great team, competitive salary.", "New York, NY", CFG)
    assert v["verdict"] == workauth.UNSTATED
    assert not v["hard_stop"]


def test_explicit_offer_is_recognized():
    v = workauth.classify("Visa sponsorship is available for exceptional candidates.", "London, UK", CFG)
    assert v["verdict"] == workauth.SPONSORS
    assert not v["hard_stop"]


def test_missing_location_does_not_block():
    """A missing location field is not evidence the role is abroad."""
    v = workauth.classify("We cannot sponsor.", None, CFG)
    assert not v["hard_stop"]


@pytest.mark.parametrize("phrase", [
    "We are unable to sponsor visas.",
    "No visa sponsorship available.",
    "We do not offer sponsorship.",
    "Sponsorship is not available for this role.",
    "We cannot sponsor work authorization.",
])
def test_refusal_phrasings_are_caught(phrase):
    v = workauth.classify(phrase, "Berlin, Germany", CFG)
    assert v["verdict"] == workauth.NO_SPONSORSHIP and v["hard_stop"]


def test_evidence_is_quoted_verbatim_not_paraphrased():
    jd = "About us. We are unable to sponsor visas for this position. Apply now."
    v = workauth.classify(jd, "Austin, TX", CFG)
    assert "unable to sponsor visas for this position" in v["evidence"]


def test_brand_that_needs_no_sponsorship_never_blocks():
    cfg = {"work_authorization": {"authorized_in": ["Canada"], "needs_sponsorship_outside": False}}
    v = workauth.classify("We cannot sponsor.", "Tokyo, Japan", cfg)
    assert not v["hard_stop"]


# --- the floor ------------------------------------------------------------------------

def test_floor_is_four_and_blocks_below():
    assert score.meets_floor(4.0, False, CFG)
    assert score.meets_floor(4.5, False, CFG)
    assert not score.meets_floor(3.9, False, CFG)


def test_hard_stop_beats_a_high_score():
    """A role the operator legally cannot take is not rescued by scoring well."""
    assert not score.meets_floor(5.0, True, CFG)


def test_unscored_never_meets_the_floor():
    assert not score.meets_floor(None, False, CFG)


# --- two-pass rule --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_importance_from_pass1_survives_pass2(monkeypatch):
    """THE mechanism. If pass 2 re-rates importance, the anchor the design exists to prevent is back."""
    import json as _json

    from glitch_signal.agent.loop import llm

    calls = []

    async def fake_complete(messages, *, model=None, tier=None, **kw):
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        calls.append(system)
        if "NOT seen any candidate" in system:
            return _json.dumps({"role_summary": "Perf marketer",
                                "requirements": [{"requirement": "Paid media at scale",
                                                  "jd_signal": "manage $1M+ budgets",
                                                  "importance": "critical"}]})
        # Pass 2 tries to DOWNGRADE the requirement the candidate is weak on.
        return _json.dumps({"requirements": [{"requirement": "Paid media at scale",
                                              "importance": "low_signal",
                                              "match": "none", "evidence": "CV silent"}],
                            "score": 4.6, "verdict": "ok", "strengths": [], "gaps": []})

    monkeypatch.setattr(llm, "complete_messages", fake_complete)
    out = await score.score_listing(
        {"title": "Perf Marketing Manager", "company": "Acme", "location": "Toronto, Canada",
         "canonical_url": "https://x.com/1",
         "jd_text": "manage $1M+ budgets. " * 40}, "CV text", CFG)

    assert out["score_parts"]["importance_overridden"] == 1, "the downgrade must be detected"
    assert "| critical |" in out["report_md"], "pass 1's importance must win in the report"


@pytest.mark.asyncio
async def test_pass1_never_sees_the_cv(monkeypatch):
    """The CV must be absent from pass 1's context — that absence IS the anti-anchoring mechanism."""
    import json as _json

    from glitch_signal.agent.loop import llm

    seen = {}

    async def fake_complete(messages, *, model=None, tier=None, **kw):
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        prompt = next((m["content"] for m in messages if m["role"] == "user"), "")
        if "NOT seen any candidate" in system:
            seen["pass1_prompt"] = prompt
            return _json.dumps({"role_summary": "r", "requirements": [
                {"requirement": "x", "jd_signal": "y", "importance": "high"}]})
        return _json.dumps({"requirements": [], "score": 4.0, "verdict": "", "strengths": [], "gaps": []})

    monkeypatch.setattr(llm, "complete_messages", fake_complete)
    await score.score_listing(
        {"title": "t", "company": "c", "location": "Toronto, Canada", "canonical_url": "u",
         "jd_text": "the posting text. " * 40}, "SECRET_CV_MARKER", CFG)
    assert "SECRET_CV_MARKER" not in seen["pass1_prompt"]


@pytest.mark.asyncio
async def test_no_jd_text_returns_no_score_rather_than_guessing(monkeypatch):
    """Scoring a listing with no archived JD would be a fabricated judgement."""
    out = await score.score_listing(
        {"title": "t", "company": "c", "location": "Toronto, Canada", "canonical_url": "u",
         "jd_text": ""}, "cv", CFG)
    assert out["score"] is None and "too short to score" in out["error"]


def test_score_is_clamped_to_the_scale():
    assert score._clamp_score(9.9) == 5.0
    assert score._clamp_score(-3) == 0.0
    assert score._clamp_score("not a number") is None


def test_json_parsing_tolerates_fences_and_prose():
    assert score._json_from('```json\n{"a": 1}\n```') == {"a": 1}
    assert score._json_from('Sure! {"a": 2} hope that helps') == {"a": 2}
    assert score._json_from("no json here") == {}


# --- fact base ------------------------------------------------------------------------

def test_empty_factbase_returns_empty_not_a_fallback(monkeypatch):
    """An empty fact base must fail loudly upstream, never quietly source claims from elsewhere."""
    from glitch_signal.agent.jobs import factbase

    assert factbase.cv_text("tejas", {}) == ""


def test_factbase_reads_inline_cv():
    from glitch_signal.agent.jobs import factbase

    assert factbase.cv_text("tejas", {"cv_markdown": "# CV\nreal content"}).startswith("# CV")


def test_scorer_uses_the_budgeted_call_not_the_2048_default():
    """Regression guard. The scorer briefly called `llm.complete` (2048-token default), which
    truncated an 18-requirement pass 2 mid-JSON. The tests kept patching `complete` and so stopped
    testing anything — CI caught it. Pin the call site."""
    import inspect

    src = inspect.getsource(score.score_listing)
    assert "complete_messages" in src
    assert "llm.complete(" not in src, "must not use the 2048-token default"
    assert "_MAX_TOKENS" in src


# --- thin-JD confidence gate (JOBS-11) -------------------------------------------------

def test_a_thin_posting_cannot_clear_the_floor():
    """The top score in a real 28-role sweep (4.0) came from a JD yielding FOUR requirements and
    zero criticals. That score describes the posting's length, not the candidate."""
    thin = {"requirements": 4, "critical": 0}
    assert not score.meets_floor(4.0, False, CFG, parts=thin)
    assert not score.meets_floor(5.0, False, CFG, parts=thin)


def test_a_substantive_posting_still_clears():
    fat = {"requirements": 18, "critical": 6}
    assert score.meets_floor(4.0, False, CFG, parts=fat)


def test_the_gate_is_confidence_not_a_penalty():
    """The score itself is untouched — only the OFFER decision changes. A caller that does not pass
    `parts` keeps the old behaviour, so this cannot silently change anything that has not opted in."""
    assert score.meets_floor(4.0, False, CFG) is True
    assert score.MIN_REQUIREMENTS_FOR_CONFIDENCE == 8


# --- thin JD TEXT guard (JOBS-13) ------------------------------------------------------

@pytest.mark.asyncio
async def test_a_listing_summary_is_refused_before_any_model_call(monkeypatch):
    """Job Bank's RSS gives "Job number / Location / Employer / Salary" (~120 chars), not a job
    description. Scoring one produced a 4.0 off ONE requirement — the top score in the whole pool,
    from a posting the model could not fail anyone on."""
    from glitch_signal.agent.loop import llm

    called = []

    async def spy(*a, **kw):
        called.append(1)
        return "{}"

    monkeypatch.setattr(llm, "complete_messages", spy)
    out = await score.score_listing(
        {"title": "marketing manager", "company": "X", "location": "Milton (ON), Canada",
         "canonical_url": "u",
         "jd_text": "Job number: 10263948001 Location: Boucherville (QC) Salary: $39,991.00"},
        "cv text", CFG)
    assert out["score"] is None
    assert "too short to score" in out["error"]
    assert called == [], "must refuse BEFORE paying for a model call"


@pytest.mark.asyncio
async def test_a_real_posting_is_not_refused(monkeypatch):
    import json as _json

    from glitch_signal.agent.loop import llm

    async def fake(messages, **kw):
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        if "NOT seen any candidate" in system:
            return _json.dumps({"role_summary": "r", "requirements": [
                {"requirement": "paid media", "jd_signal": "x", "importance": "critical"}]})
        return _json.dumps({"requirements": [], "score": 4.0, "verdict": "", "strengths": [], "gaps": []})

    monkeypatch.setattr(llm, "complete_messages", fake)
    out = await score.score_listing(
        {"title": "t", "company": "c", "location": "Toronto, Canada", "canonical_url": "u",
         "jd_text": "x" * 5000}, "cv", CFG)
    assert out["score"] == 4.0


# --- cost-first router + detected-failure escalation (JOBS-15) --------------------------

def test_critical_stays_quality_first():
    """`critical` carries the conscience critic — "the last thing between the agent and the public" —
    and irreversible work. A previous lane deliberately moved that critic OFF the cheapest model;
    cost-first ordering here would silently revert that fix."""
    from glitch_signal.agent.loop import conscience, routing

    assert conscience.CRITIC_TIER == "critical"
    assert routing.resolve("critical")[0] == "anthropic/claude-opus-5"


def test_every_tier_still_has_real_fallbacks():
    from glitch_signal.agent.loop import routing

    for tier in ("critical", "complex", "moderate", "simple"):
        models = routing.resolve(tier)
        assert len(models) >= 2, f"{tier} has no failover"
        assert len(set(models)) == len(models)


@pytest.mark.asyncio
async def test_unparseable_pass2_escalates_to_a_stronger_tier(monkeypatch):
    """The cheap model answering badly is exactly when paying for a better one is worth it —
    and only then."""
    import json as _json

    from glitch_signal.agent.loop import llm

    tiers = []

    async def fake(messages, *, tier=None, **kw):
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        if "NOT seen any candidate" in system:
            return _json.dumps({"role_summary": "r", "requirements": [
                {"requirement": "paid media", "jd_signal": "x", "importance": "critical"}]})
        tiers.append(tier)
        if tier == "complex":
            return "not json at all — truncated"        # cheap model fails
        return _json.dumps({"requirements": [], "score": 4.0, "verdict": "ok",
                            "strengths": [], "gaps": []})

    monkeypatch.setattr(llm, "complete_messages", fake)
    out = await score.score_listing(
        {"title": "t", "company": "c", "location": "Toronto, Canada", "canonical_url": "u",
         "jd_text": "x" * 5000}, "cv", CFG, tier="complex")
    assert tiers == ["complex", "critical"], "must retry pass 2 on the next tier up"
    assert out["score"] == 4.0
    assert out["model"] == "critical"


@pytest.mark.asyncio
async def test_a_good_cheap_answer_does_not_escalate(monkeypatch):
    """Escalation must be rare — it exists to remove the downside of cheapest-first, not to undo it."""
    import json as _json

    from glitch_signal.agent.loop import llm

    tiers = []

    async def fake(messages, *, tier=None, **kw):
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        if "NOT seen any candidate" in system:
            return _json.dumps({"role_summary": "r", "requirements": [
                {"requirement": "x", "jd_signal": "y", "importance": "high"}]})
        tiers.append(tier)
        return _json.dumps({"requirements": [], "score": 3.0, "verdict": "", "strengths": [], "gaps": []})

    monkeypatch.setattr(llm, "complete_messages", fake)
    await score.score_listing(
        {"title": "t", "company": "c", "location": "Toronto, Canada", "canonical_url": "u",
         "jd_text": "x" * 5000}, "cv", CFG, tier="complex")
    assert tiers == ["complex"], "no escalation when the cheap answer parses"


# --- escalation must cover the failures actually observed (JOBS-16) ---------------------

@pytest.mark.asyncio
async def test_an_empty_completion_escalates_rather_than_failing(monkeypatch):
    """Measured 2026-09-15: a cheap primary returned an EMPTY completion (whole token budget spent on
    internal reasoning) on 14 of 18 real postings, and OpenRouter did NOT fail over — an empty
    response is a SUCCESSFUL HTTP response, not an error. Escalating is the only thing that catches
    it."""
    import json as _json

    from glitch_signal.agent.loop import llm

    tiers = []

    async def fake(messages, *, tier=None, **kw):
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        tiers.append((("p1" if "NOT seen any candidate" in system else "p2"), tier))
        if "NOT seen any candidate" in system:
            if tier == "complex":
                raise RuntimeError("empty completion from z-ai/glm-5.3 (stop_reason=max_tokens)")
            return _json.dumps({"role_summary": "r", "requirements": [
                {"requirement": "paid media", "jd_signal": "x", "importance": "critical"}]})
        return _json.dumps({"requirements": [], "score": 3.5, "verdict": "", "strengths": [], "gaps": []})

    monkeypatch.setattr(llm, "complete_messages", fake)
    out = await score.score_listing(
        {"title": "t", "company": "c", "location": "Toronto, Canada", "canonical_url": "u",
         "jd_text": "x" * 5000}, "cv", CFG, tier="complex")
    assert ("p1", "complex") in tiers and ("p1", "critical") in tiers, "pass 1 must escalate"
    assert out["score"] == 3.5


def test_the_scoring_tier_is_cost_first_and_critical_is_not():
    """glm-5.3 scored 0/18 as the `complex` primary — which was OUR bug, not the model: the
    empty-completion retry was gated out at exactly the 8000 the scorer asks for, and nothing capped
    reasoning effort. Both fixed; glm-5.3 completes the same scoring call for 74% less. Cheapest-first
    is safe HERE because score_listing escalates on a detected bad answer — `critical` has no such
    check and stays quality-first."""
    from glitch_signal.agent.loop import routing

    assert routing.resolve("complex")[0] == "z-ai/glm-5.3"
    assert routing.resolve("complex")[1] == "anthropic/claude-sonnet-5"
    assert routing.resolve("critical")[0] == "anthropic/claude-opus-5"
