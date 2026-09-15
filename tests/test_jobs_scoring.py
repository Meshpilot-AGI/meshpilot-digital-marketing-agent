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

    async def fake_complete(prompt, *, system=None, tier=None, **kw):
        calls.append(system or "")
        if "NOT seen any candidate" in (system or ""):
            return _json.dumps({"role_summary": "Perf marketer",
                                "requirements": [{"requirement": "Paid media at scale",
                                                  "jd_signal": "manage $1M+ budgets",
                                                  "importance": "critical"}]})
        # Pass 2 tries to DOWNGRADE the requirement the candidate is weak on.
        return _json.dumps({"requirements": [{"requirement": "Paid media at scale",
                                              "importance": "low_signal",
                                              "match": "none", "evidence": "CV silent"}],
                            "score": 4.6, "verdict": "ok", "strengths": [], "gaps": []})

    monkeypatch.setattr(llm, "complete", fake_complete)
    out = await score.score_listing(
        {"title": "Perf Marketing Manager", "company": "Acme", "location": "Toronto, Canada",
         "canonical_url": "https://x.com/1", "jd_text": "manage $1M+ budgets"}, "CV text", CFG)

    assert out["score_parts"]["importance_overridden"] == 1, "the downgrade must be detected"
    assert "| critical |" in out["report_md"], "pass 1's importance must win in the report"


@pytest.mark.asyncio
async def test_pass1_never_sees_the_cv(monkeypatch):
    """The CV must be absent from pass 1's context — that absence IS the anti-anchoring mechanism."""
    import json as _json

    from glitch_signal.agent.loop import llm

    seen = {}

    async def fake_complete(prompt, *, system=None, tier=None, **kw):
        if "NOT seen any candidate" in (system or ""):
            seen["pass1_prompt"] = prompt
            return _json.dumps({"role_summary": "r", "requirements": [
                {"requirement": "x", "jd_signal": "y", "importance": "high"}]})
        return _json.dumps({"requirements": [], "score": 4.0, "verdict": "", "strengths": [], "gaps": []})

    monkeypatch.setattr(llm, "complete", fake_complete)
    await score.score_listing(
        {"title": "t", "company": "c", "location": "Toronto, Canada", "canonical_url": "u",
         "jd_text": "the posting text"}, "SECRET_CV_MARKER", CFG)
    assert "SECRET_CV_MARKER" not in seen["pass1_prompt"]


@pytest.mark.asyncio
async def test_no_jd_text_returns_no_score_rather_than_guessing(monkeypatch):
    """Scoring a listing with no archived JD would be a fabricated judgement."""
    out = await score.score_listing(
        {"title": "t", "company": "c", "location": "Toronto, Canada", "canonical_url": "u",
         "jd_text": ""}, "cv", CFG)
    assert out["score"] is None and "no jd_text" in out["error"]


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
