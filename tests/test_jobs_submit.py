"""JOBS-6 acceptance — the guards on the irreversible step.

⚠️ The lane's stated acceptance ("one real application submitted with a stored confirmation
artifact") is NOT met and is NOT simulated here. No submission driver exists, because neither
Greenhouse nor Lever offers a candidate-side application API. These tests prove the guards.
"""
from __future__ import annotations

import pytest

from glitch_signal.agent.jobs import submit

BANK = {"are you legally authorized to work in canada": "Yes",
        "will you now or in the future require sponsorship": "No"}

APPROVED = {"id": "app-1", "status": "approved", "submitted_at": None,
            "canonical_url": "https://job-boards.greenhouse.io/acme/jobs/1",
            "tailored_cv_path": "/tmp/cv.pdf"}


# --- approval is required -------------------------------------------------------------

@pytest.mark.parametrize("status", ["drafted", "awaiting_approval", "rejected", "expired", "skipped", None])
def test_only_an_approved_application_may_submit(status):
    r = submit.prepare(dict(APPROVED, status=status), [], BANK)
    assert r["outcome"] == "refused" and not r["ok"]


@pytest.mark.parametrize("status", ["approved", "edited"])
def test_approved_and_edited_may_submit(status):
    r = submit.prepare(dict(APPROVED, status=status), [], BANK)
    assert r["ok"] and r["outcome"] == "ready"


# --- idempotency ----------------------------------------------------------------------

def test_an_already_submitted_application_is_refused():
    """Submitting twice to one req is not recoverable."""
    r = submit.prepare(dict(APPROVED, submitted_at="2026-09-15T00:00:00Z"), [], BANK)
    assert r["outcome"] == "refused" and "already submitted" in r["reason"]


def test_mark_submitted_sql_is_atomic():
    from glitch_signal.agent.jobs.store import _MARK_SUBMITTED

    sql = str(_MARK_SUBMITTED).lower()
    assert "submitted_at is null" in sql, "the guard must be in the UPDATE, not in Python"
    assert "returning id" in sql, "must report whether THIS call won the race"


# --- operator decision 4: never compose a screening answer -----------------------------

def test_an_unknown_question_makes_it_manual_not_a_guess():
    r = submit.prepare(APPROVED, ["What is your expected salary?"], BANK)
    assert r["outcome"] == "manual_required"
    assert "expected salary" in r["reason"]


def test_a_known_question_is_answered_from_the_bank():
    r = submit.prepare(APPROVED, ["Are you legally authorized to work in Canada?"], BANK)
    assert r["ok"]
    assert r["package"]["answers"]["Are you legally authorized to work in Canada?"] == "Yes"


def test_matching_is_exact_after_normalization_only():
    """Case, whitespace and trailing punctuation are normalized. Nothing else."""
    assert submit.answer_for("  ARE YOU LEGALLY AUTHORIZED TO WORK IN CANADA?  ", BANK) == "Yes"
    assert submit.answer_for("Are you legally authorized to work in Canada", BANK) == "Yes"


def test_a_near_match_is_a_miss_not_a_clever_guess():
    """A confident near-match is how a wrong answer gets submitted under someone's name."""
    assert submit.answer_for("Are you authorized to work in Canada?", BANK) is None
    assert submit.answer_for("Do you have Canadian work authorization?", BANK) is None


def test_one_unanswered_question_makes_the_whole_application_manual():
    qs = ["Are you legally authorized to work in Canada?", "Why do you want to work here?"]
    r = submit.prepare(APPROVED, qs, BANK)
    assert r["outcome"] == "manual_required"


# --- ATS scope ------------------------------------------------------------------------

@pytest.mark.parametrize("url,ats", [
    ("https://job-boards.greenhouse.io/acme/jobs/1", "greenhouse"),
    ("https://jobs.lever.co/acme/abc", "lever"),
    ("https://jobs.ashbyhq.com/acme/abc", "ashby"),
    ("https://acme.wd5.myworkdayjobs.com/x", "workday"),
    ("https://example.com/careers/1", None),
])
def test_ats_detection(url, ats):
    assert submit.ats_of(url) == ats


@pytest.mark.parametrize("url", ["https://jobs.ashbyhq.com/acme/abc",
                                 "https://acme.wd5.myworkdayjobs.com/x",
                                 "https://example.com/careers/1"])
def test_out_of_scope_ats_is_manual_not_attempted(url):
    """Workday is the worst of them. Guessing at an unknown form is how a broken application is sent."""
    r = submit.prepare(dict(APPROVED, canonical_url=url), [], BANK)
    assert r["outcome"] == "manual_required"


def test_no_cv_artifact_is_manual():
    r = submit.prepare(dict(APPROVED, tailored_cv_path=None), [], BANK)
    assert r["outcome"] == "manual_required"


# --- no driver: the honest outcome ----------------------------------------------------

@pytest.mark.asyncio
async def test_with_no_driver_the_result_is_manual_required_not_silent_success():
    submit.register_driver(None)
    r = await submit.submit(APPROVED, [], BANK)
    assert not r["submitted"]
    assert r["outcome"] == "manual_required"
    assert "no submission driver" in r["reason"]


# --- evidence or it did not happen ----------------------------------------------------

@pytest.mark.asyncio
async def test_a_success_with_no_evidence_is_treated_as_not_submitted():
    """Believing an unevidenced claim is how the tracker drifts away from reality — in the
    direction that looks good."""
    class NoEvidence:
        async def submit(self, package):
            return {"ok": True, "evidence": {}}

    submit.register_driver(NoEvidence())
    try:
        r = await submit.submit(APPROVED, [], BANK)
    finally:
        submit.register_driver(None)
    assert not r["submitted"] and r["outcome"] == "failed"
    assert "no confirmation artifact" in r["reason"]


@pytest.mark.asyncio
async def test_a_success_with_evidence_is_recorded_as_submitted():
    class Good:
        async def submit(self, package):
            return {"ok": True, "evidence": {"confirmation": "Thanks for applying", "screenshot": "s3://x"}}

    submit.register_driver(Good())
    try:
        r = await submit.submit(APPROVED, [], BANK)
    finally:
        submit.register_driver(None)
    assert r["submitted"] and r["outcome"] == "submitted"
    assert r["evidence"]["confirmation"]


@pytest.mark.asyncio
async def test_a_driver_failure_does_not_mark_submitted():
    class Fails:
        async def submit(self, package):
            return {"ok": False, "failure_reason": "captcha encountered", "evidence": {}}

    submit.register_driver(Fails())
    try:
        r = await submit.submit(APPROVED, [], BANK)
    finally:
        submit.register_driver(None)
    assert not r["submitted"] and "captcha" in r["reason"]


def test_captcha_and_account_creation_stay_out_of_scope():
    """Design § 7. Prove no solver crept in."""
    import pathlib

    src = pathlib.Path("src/glitch_signal/agent/jobs").rglob("*.py")
    joined = "\n".join(p.read_text() for p in src).lower()
    for banned in ("capsolver", "2captcha", "anticaptcha", "deathbycaptcha"):
        assert banned not in joined


# --- the daily cap is no longer inert -------------------------------------------------

def test_allow_counts_real_submissions_for_the_apply_tool(monkeypatch):
    """The cap read 0 forever until `allow()` supplied the count — the switch existed, the tests
    passed, and it enforced nothing in production."""
    from glitch_signal.agent.jobs import store as jobstore
    from glitch_signal.agent.loop import policy as pol

    monkeypatch.setattr(pol, "from_config", lambda: pol.Policy(
        jobs_enabled=True, job_apply_enabled=True, publish_enabled=True,
        max_job_applications_per_day=3))
    monkeypatch.setattr(jobstore, "submitted_today", lambda b, **kw: 3)
    ok, reason = pol.allow("job_apply", {}, "tejas")
    assert not ok and "daily application cap" in reason


def test_allow_fails_closed_when_the_count_cannot_be_read(monkeypatch):
    """If we cannot count today's submissions we must NOT assume zero."""
    from glitch_signal.agent.jobs import store as jobstore
    from glitch_signal.agent.loop import policy as pol

    monkeypatch.setattr(pol, "from_config", lambda: pol.Policy(
        jobs_enabled=True, job_apply_enabled=True, publish_enabled=True))

    def boom(b, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(jobstore, "submitted_today", boom)
    ok, reason = pol.allow("job_apply", {}, "tejas")
    assert not ok and "cannot verify the daily application cap" in reason


def test_other_tools_do_not_pay_for_the_count(monkeypatch):
    """Only the submitting tool queries the DB."""
    from glitch_signal.agent.jobs import store as jobstore
    from glitch_signal.agent.loop import policy as pol

    called = []
    monkeypatch.setattr(jobstore, "submitted_today", lambda b, **kw: called.append(b) or 0)
    monkeypatch.setattr(pol, "from_config", lambda: pol.Policy(jobs_enabled=True, job_discovery_enabled=True))
    pol.allow("search_jobs", {}, "tejas")
    assert called == []
