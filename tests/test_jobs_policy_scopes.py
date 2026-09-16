"""JOBS-1 acceptance — the safety properties, proven rather than asserted.

Design: docs/plans/2026-09-15-job-application-agent.md §§ 9, 11.
"""
from __future__ import annotations

import pytest

from glitch_signal.agent.loop import scopes
from glitch_signal.agent.loop.policy import JOB_TOOLS, PUBLISH_TOOLS, Policy

ALL_JOB_TOOLS = sorted(JOB_TOOLS)


@pytest.mark.parametrize("tool", ALL_JOB_TOOLS)
def test_chat_scope_cannot_reach_any_job_tool(tool):
    """The default scope is safe read+plan. It must not offer a single job tool."""
    assert not scopes.resolve("chat").allows(tool)


@pytest.mark.parametrize("scope_name", ["discovery", "content", "content_draft", "orm"])
@pytest.mark.parametrize("tool", ALL_JOB_TOOLS)
def test_preexisting_scopes_cannot_reach_job_tools(scope_name, tool):
    """Adding a capability must not widen a scope that already existed."""
    assert not scopes.resolve(scope_name).allows(tool)


def test_job_discovery_scope_cannot_apply():
    """Scoring roles must not imply the ability to submit one."""
    s = scopes.resolve("job_discovery")
    assert s.allows("search_jobs")
    assert s.allows("score_job")
    assert not s.allows("job_apply")
    assert not s.allows("tailor_cv")


def test_job_draft_scope_cannot_apply():
    s = scopes.resolve("job_draft")
    assert s.allows("tailor_cv")
    assert not s.allows("job_apply")


def test_job_apply_is_also_a_publish_tool():
    """Submission is outward and irreversible: it inherits the publish kill-switch too."""
    assert "job_apply" in PUBLISH_TOOLS


def test_everything_ships_off_by_default():
    """A default Policy denies every job tool — the capability ships inert."""
    p = Policy()
    for tool in ALL_JOB_TOOLS:
        assert not p.check(tool, {}, "tejas").allow


def test_tiers_deny_independently():
    on = dict(jobs_enabled=True, publish_enabled=True)
    assert not Policy(**on).check("search_jobs", {}, "tejas").allow
    assert not Policy(**on).check("tailor_cv", {}, "tejas").allow
    assert not Policy(**on).check("job_apply", {}, "tejas").allow

    assert Policy(**on, job_discovery_enabled=True).check("search_jobs", {}, "tejas").allow
    assert Policy(**on, job_tailor_enabled=True).check("tailor_cv", {}, "tejas").allow
    assert Policy(**on, job_apply_enabled=True).check("job_apply", {}, "tejas").allow


def test_apply_still_denied_when_publish_is_off():
    """job_apply is in PUBLISH_TOOLS, so the publish kill-switch alone must stop it."""
    p = Policy(jobs_enabled=True, job_apply_enabled=True, publish_enabled=False)
    d = p.check("job_apply", {}, "tejas")
    assert not d.allow
    assert "posting is disabled" in d.reason


def test_daily_cap_is_enforced_at_three():
    """Operator decision 1 (design § 11): 3 applications/day."""
    base = dict(jobs_enabled=True, job_apply_enabled=True, publish_enabled=True)
    assert Policy(**base, job_applications_today=2).check("job_apply", {}, "tejas").allow
    d = Policy(**base, job_applications_today=3).check("job_apply", {}, "tejas")
    assert not d.allow
    assert "daily application cap" in d.reason


def test_daily_cap_counts_submissions_not_loop_runs():
    """A per-run counter would reset on restart; the cap must survive that."""
    base = dict(jobs_enabled=True, job_apply_enabled=True, publish_enabled=True)
    p = Policy(**base, job_applications_today=3)
    # `counts` is the per-run tally — an empty one must NOT rescue a capped brand.
    assert not p.check("job_apply", {}, "tejas", counts={}).allow


def test_the_settings_floor_stays_aligned_with_the_live_one():
    """`agent_job_min_score` is NOT what runs — `jobs.min_score` in the brand config is, via
    `score.meets_floor`. It is kept aligned anyway so a reader who finds this constant does not
    mistake a stale value for the live threshold. Tracks the brand config: 4.0 → 4.3 → 4.0."""
    from glitch_signal.config import Settings

    assert Settings().agent_job_min_score == 4.0
    assert Settings().agent_job_max_applications_per_day == 3
