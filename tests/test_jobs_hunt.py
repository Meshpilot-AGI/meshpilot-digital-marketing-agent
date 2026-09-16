"""JOBS-8 — the hunt/submit ticks. The guards are the reason this module exists, so they are what
is tested: below-floor never reaches a card, an unverified CV never reaches a card, and neither tick
can exceed the operator's daily cap."""
from __future__ import annotations

from glitch_signal.agent.jobs import hunt

CFG = {"max_applications_per_day": 3, "min_score": 4.3, "cv_markdown": "# CV\nreal experience"}


class _Store:
    """Stand-in for agent.jobs.store — every call the ticks make, recorded."""

    def __init__(self, *, unscored=(), candidates=(), submitted=0, approved=()):
        self._unscored, self._candidates = list(unscored), list(candidates)
        self._submitted, self._approved = submitted, list(approved)
        self.offered, self.evaluated, self.statuses, self.marked = [], [], [], []
        self.cv_md = None

    async def unscored(self, brand, limit, *, engine=None):
        return self._unscored

    async def offer_candidates(self, brand, limit=10, *, engine=None):
        return self._candidates

    async def record_evaluation(self, brand, listing_id, result, *, engine=None):
        self.evaluated.append(listing_id)

    async def submitted_today(self, brand, *, engine=None):
        return self._submitted

    async def upsert_application(self, brand, listing_id, *, status="drafted", engine=None, **kw):
        self.cv_md = kw.get("cv_md")
        return f"app-{listing_id}"

    async def mark_offered(self, app_id, msg_id, *, engine=None, **kw):
        self.offered.append((app_id, msg_id))

    async def applications_by_status(self, brand, statuses, *, engine=None):
        return self._approved

    async def answer_bank(self, brand, *, engine=None):
        return {}

    async def mark_submitted(self, app_id, evidence, *, engine=None):
        self.marked.append(app_id)
        self._submitted += 1
        return True

    async def set_application_status(self, app_id, status, *, engine=None, **kw):
        self.statuses.append((app_id, status))


def _cand(score, **kw):
    d = {"listing_id": f"l{score}", "canonical_url": f"https://boards.example.com/{score}",
         "company": "Example", "title": "Growth Marketing Manager", "location": "Toronto",
         "jd_text": "x" * 900, "score": score, "score_parts": {"requirements": 20, "critical": 5},
         "work_auth": "authorized"}
    d.update(kw)
    return d


# Every switch this family owns, ON — these tests are about the tick's own guards (floor,
# verification, cap), so the kill-switches must not be what stops them. `test_the_kill_switches_*`
# below covers the other direction.
_ALL_ON = ("agent_jobs_enabled", "agent_job_discovery_enabled", "agent_job_tailor_enabled",
           "agent_job_apply_enabled")


def _flags(monkeypatch, *, on=_ALL_ON):
    from glitch_signal.config import settings

    s = settings()
    for f in _ALL_ON:
        monkeypatch.setattr(s, f, f in on, raising=False)


def _patch(monkeypatch, store, cfg=None):
    from glitch_signal.agent.jobs import discover as _disc

    _flags(monkeypatch)
    monkeypatch.setattr("glitch_signal.agent.jobs.store", store, raising=False)
    monkeypatch.setattr(_disc, "jobs_config", lambda b: dict(cfg or CFG))
    monkeypatch.setattr("glitch_signal.agent.jobs.factbase.cv_text", lambda b, c: c.get("cv_markdown", ""))


async def _run(monkeypatch, store, *, candidates_ok=True, cfg=None, **deps):
    _patch(monkeypatch, store, cfg)
    base = {"discover": _noop_discover,
            "tailor_cv": _ok_tailor if candidates_ok else _failed_tailor,
            "offer": _offer}
    base.update(deps)
    return await hunt.run("tejas", {}, deps=base)


async def _noop_discover(brand, dry_run=False):
    return {"stored": 0}


async def _ok_tailor(listing, cv):
    return {"ok": True, "markdown": "# Tailored\nreal experience", "findings": [], "attempts": 1}


async def _failed_tailor(listing, cv):
    return {"ok": False, "markdown": None, "attempts": 2,
            "findings": ["'grew revenue 400%' is not supported by the fact base"]}


async def _offer(brand, application):
    return f"msg-{application['listing_id']}"


async def test_a_below_floor_role_is_skipped_and_never_offered(monkeypatch):
    """Operator decision 2: below the floor a role is SKIPPED, not surfaced for a yes/no. Offering
    it 'just to ask' would quietly turn the floor into a suggestion."""
    store = _Store(candidates=[_cand(4.0)])          # 4.0 < the 4.3 floor
    out = await _run(monkeypatch, store)
    assert out["offered"] == [] and store.offered == []
    assert out["skipped"][0]["reason"] == "below floor / work-auth"


async def test_a_cv_that_fails_verification_never_reaches_a_card(monkeypatch):
    """The verifier fails closed. A tailored CV carrying an unsupported metric is a lie told in the
    operator's name — it must die before the card, not at the card."""
    store = _Store(candidates=[_cand(4.5)])
    out = await _run(monkeypatch, store, candidates_ok=False)
    assert store.offered == []
    assert out["skipped"][0]["reason"] == "cv failed fact verification"


async def test_offers_are_capped_by_the_remaining_daily_budget(monkeypatch):
    """Queueing more decisions than the cap can ever act on trains the operator to ignore the cards,
    which is the one failure an approval gate cannot survive."""
    store = _Store(candidates=[_cand(4.9), _cand(4.8), _cand(4.7), _cand(4.6)], submitted=1)
    out = await _run(monkeypatch, store)             # cap 3, one already sent today → budget 2
    assert len(out["offered"]) == 2 and len(store.offered) == 2


async def test_the_cap_being_met_stops_the_tick_before_any_card(monkeypatch):
    store = _Store(candidates=[_cand(4.9)], submitted=3)
    out = await _run(monkeypatch, store)
    assert out["offered"] == [] and store.offered == []
    assert out["skipped"] == [{"reason": "daily application cap already met"}]


async def test_no_cv_fails_loudly_instead_of_scoring_against_nothing(monkeypatch):
    """With an empty fact base every match is a fabrication, and a fabricated 4.3 would put the
    operator in front of an employer on the strength of nothing."""
    store = _Store(candidates=[_cand(4.9)])
    out = await _run(monkeypatch, store, cfg={**CFG, "cv_markdown": ""})
    assert out["scored"] == 0 and out["offered"] == []
    assert "no CV in the fact base" in out["errors"][0]


async def test_a_dead_source_does_not_stop_scoring_what_we_already_hold(monkeypatch):
    async def _boom(brand, dry_run=False):
        raise RuntimeError("jobbank 503")

    store = _Store(candidates=[_cand(4.9)])
    out = await _run(monkeypatch, store, discover=_boom)
    assert "jobbank 503" in out["errors"][0]
    assert len(out["offered"]) == 1, "a broken source must not block roles already in the pool"


# ── submit ──

async def test_submit_rechecks_the_cap_every_iteration(monkeypatch):
    """A cap computed once and reused is not a cap: two workers run this tick concurrently, so the
    count is re-read from the database before each send."""
    apps = [{"id": f"a{i}", "canonical_url": f"https://x.example/{i}"} for i in range(4)]
    store = _Store(approved=apps, submitted=0)

    async def _ok(app, questions, bank):
        return {"submitted": True, "evidence": {"confirmation": "ok"}}

    _patch(monkeypatch, store)
    out = await hunt.run_submit("tejas", {}, deps={"submit": _ok})
    assert len(out["submitted"]) == 3, "the 4th must be refused by the 3/day cap"
    assert "daily cap of 3 reached" in out["errors"][0]


async def test_an_unresolved_form_becomes_manual_required_not_a_guess(monkeypatch):
    """Operator decision 4: the agent never composes an unattended free-text answer."""
    store = _Store(approved=[{"id": "a1", "canonical_url": "https://x.example/1"}])

    async def _manual(app, questions, bank):
        return {"submitted": False, "outcome": "manual_required",
                "reason": "1 screening question has no exact match in the answer bank"}

    _patch(monkeypatch, store)
    out = await hunt.run_submit("tejas", {}, deps={"submit": _manual})
    assert out["submitted"] == [] and store.marked == []
    assert store.statuses == [("a1", "manual_required")]
    assert out["manual_required"][0]["outcome"] == "manual_required"


async def test_the_kill_switch_stops_the_hunt_before_anything_runs(monkeypatch):
    """⚠️ The four `agent_job*_enabled` switches are enforced on TOOL DISPATCH, and a `capability`
    cron job calls these coroutines directly — no model, no tool call, no policy gate. Without the
    check inside the tick, registering `jobs_submit` would have submitted applications while
    `agent_job_apply_enabled` was False. A gate that one entry point bypasses is not a gate."""
    store = _Store(candidates=[_cand(4.9)])
    _patch(monkeypatch, store)
    _flags(monkeypatch, on=())
    out = await hunt.run("tejas", {}, deps={"discover": _noop_discover, "tailor_cv": _ok_tailor,
                                            "offer": _offer})
    assert out["offered"] == [] and store.offered == []
    assert "agent_jobs_enabled" in out["refused"]


async def test_submit_refuses_unless_its_own_switch_is_on(monkeypatch):
    """`agent_jobs_enabled` alone must not be enough to send an application."""
    store = _Store(approved=[{"id": "a1", "canonical_url": "https://x.example/1"}])

    async def _ok(app, questions, bank):
        raise AssertionError("submit must not be reached with the apply switch off")

    _patch(monkeypatch, store)
    _flags(monkeypatch, on=("agent_jobs_enabled",))
    out = await hunt.run_submit("tejas", {}, deps={"submit": _ok})
    assert out["submitted"] == []
    assert "agent_job_apply_enabled" in out["refused"]


async def test_the_approved_cv_is_stored_with_the_application(monkeypatch):
    """⚠️ The first real approval (2026-09-16) approved a CV that no longer existed. `hunt.run`
    generated the tailored markdown, verified it, put it in the Discord card and dropped it —
    `tailored_cv_path` stayed NULL and nothing held the document. A later submission would have
    re-tailored and sent something the operator never saw, which makes the approval gate theatre.

    The markdown goes in with the row, before the card exists."""
    store = _Store(candidates=[_cand(4.9)])
    _patch(monkeypatch, store)
    await hunt.run("tejas", {}, deps={"discover": _noop_discover, "tailor_cv": _ok_tailor,
                                      "offer": _offer})
    assert store.cv_md and "Tailored" in store.cv_md, "the approved document must be persisted"
