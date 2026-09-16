"""JOBS-8 — the deterministic `job_hunt` ticks: discover → score → tailor → offer, and submit.

The design (docs/plans/2026-09-15-job-application-agent.md § 3) specified one `job_hunt` pipeline.
JOBS-0..7 shipped every PIECE of it — discovery, scoring, tailoring, the verifier, approval cards,
the submission guards — as agent TOOLS, and nothing that sequences them. So the capability was
complete and inert: the only way to apply for a job was for a model to pick the five tools in the
right order, and `approvals.run` — the tick that reads the operator's reactions back — was not in
the capability registry at all, which made it unreachable by any route.

**Why this is deterministic rather than an agent goal.** Every other capability family here ends in
a draft a human reads. This one ends in an irreversible act performed in the operator's name, under
a hard 3/day cap. Sequencing that with a model would put "did it call the tools in the right order"
on the safety path. Nothing is delegated to judgement that a `for` loop can decide: the model's job
is the writing (scoring reports, the tailored CV), which is exactly where it belongs.

Three ticks, deliberately separate — the same split OFFPAGE uses:

  jobs_hunt    discover → score → tailor → offer a card      (writes nothing outward but a Discord card)
  jobs_decide  read the operator's reactions back            (`approvals.run`)
  jobs_submit  submit what they approved                     (the only outward, irreversible one)

They are separate capabilities because they need different powers, and because the run that offers a
role must not be the same run that decides it was approved.
"""
from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger(__name__)

def _off(*flags: str) -> list[str]:
    """Which of these kill-switches are currently OFF.

    ⚠️ Load-bearing. The four `agent_job*_enabled` switches are enforced in `loop/policy.py`, on TOOL
    DISPATCH — and a `capability` cron job calls these coroutines directly, without a model or a tool
    call, so it never passes through that gate. Without this check, registering `jobs_submit` in the
    capability registry would have made it submit applications while `agent_job_apply_enabled` was
    False, which is precisely the switch the operator relies on. A gate that one entry point bypasses
    is not a gate.
    """
    from glitch_signal.config import settings

    s = settings()
    return [f for f in flags if not getattr(s, f, False)]


# How many listings to score in one tick. Scoring is two LLM calls per listing, so this bounds the
# tick's spend; the rest stay unscored and are picked up by the next one.
_SCORE_BATCH = 8


async def run(brand_id: str, args: dict | None = None, *, engine: Any = None,
              deps: dict | None = None) -> dict:
    """The hunt tick: discover, score what is unscored, then tailor + offer what clears the floor.

    Offers are capped at the operator's daily application cap. Queueing more decisions than the cap
    can ever act on would train them to ignore the cards, which is the one failure mode an approval
    gate cannot survive.
    """
    from glitch_signal.agent.jobs import factbase, store
    from glitch_signal.agent.jobs import score as _score
    from glitch_signal.agent.jobs import tailor as _tailor
    from glitch_signal.agent.jobs.discover import discover, jobs_config

    a = args or {}
    d = deps or {}
    _discover = d.get("discover") or discover
    _tailor_cv = d.get("tailor_cv") or _tailor.tailor_cv
    _offer = d.get("offer")
    if _offer is None:
        from glitch_signal.agent.jobs.approvals import offer as _offer  # noqa: PLC0415

    cfg = jobs_config(brand_id)
    out: dict[str, Any] = {"ran": "jobs_hunt", "brand": brand_id, "discovered": {}, "scored": 0,
                           "offered": [], "skipped": [], "errors": []}

    if blocked := _off("agent_jobs_enabled"):
        out["refused"] = f"kill-switch off: {', '.join(blocked)}"
        return out

    cv = factbase.cv_text(brand_id, cfg)
    if not cv:
        # Fail loudly rather than scoring against an empty fact base: with no CV every match is a
        # fabrication, and a fabricated 4.3 would put the operator in front of an employer.
        out["errors"].append("no CV in the fact base — set jobs.cv_markdown or jobs.cv_path")
        return out

    if a.get("discover", True) and not _off("agent_job_discovery_enabled"):
        try:
            out["discovered"] = await _discover(brand_id, dry_run=False)
        except Exception as exc:  # noqa: BLE001 — a dead source must not stop scoring what we hold
            out["errors"].append(f"discover: {str(exc)[:160]}")

    for row in await store.unscored(brand_id, int(a.get("score_limit") or _SCORE_BATCH),
                                    engine=engine):
        try:
            res = await _score.score_listing(row, cv, cfg)
        except Exception as exc:  # noqa: BLE001 — one bad posting must not end the tick
            out["errors"].append(f"score {row.get('canonical_url')}: {str(exc)[:160]}")
            continue
        if res.get("report_md"):
            await store.record_evaluation(brand_id, str(row["id"]), res, engine=engine)
            out["scored"] += 1

    budget = max(0, int(cfg.get("max_applications_per_day", 3))
                 - await store.submitted_today(brand_id, engine=engine))
    if not budget:
        out["skipped"].append({"reason": "daily application cap already met"})
        return out

    for cand in await store.offer_candidates(brand_id, limit=int(a.get("offer_limit") or 10),
                                             engine=engine):
        if len(out["offered"]) >= budget:
            break
        url = cand.get("canonical_url")
        parts = cand.get("score_parts")
        if isinstance(parts, str):
            import json  # noqa: PLC0415

            parts = json.loads(parts or "{}")
        hard_stop = (cand.get("work_auth") == "no_sponsorship")
        score = float(cand["score"]) if cand.get("score") is not None else None
        if not _score.meets_floor(score, hard_stop, cfg, parts=parts or {}):
            # Below the floor is SKIPPED, never surfaced for a yes/no (operator decision 2).
            out["skipped"].append({"url": url, "score": score, "reason": "below floor / work-auth"})
            continue
        if blocked := _off("agent_job_tailor_enabled"):
            out["skipped"].append({"url": url, "reason": f"kill-switch off: {', '.join(blocked)}"})
            continue
        try:
            tailored = await _tailor_cv(dict(cand), cv)
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"tailor {url}: {str(exc)[:160]}")
            continue
        if not tailored.get("ok"):
            # The verifier failed closed. A CV with an unsupported claim never reaches a card —
            # which is the whole point of verifying, so this is a correct outcome, not an error.
            out["skipped"].append({"url": url, "reason": "cv failed fact verification",
                                   "findings": tailored.get("findings", [])[:3]})
            continue
        try:
            data = dict(cand)
            data["tailored_cv"] = tailored.get("markdown") or ""
            data["answers"] = {}
            app_id = await store.upsert_application(brand_id, str(cand["listing_id"]),
                                                    status="drafted", engine=engine)
            msg_id = await _offer(brand_id, data)
            await store.mark_offered(app_id, msg_id, engine=engine)
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"offer {url}: {str(exc)[:160]}")
            continue
        out["offered"].append({"application_id": app_id, "discord_msg_id": msg_id,
                               "url": url, "score": score})
        log.info("jobs.offered", brand=brand_id, url=url, score=score, application=app_id)
    return out


async def run_submit(brand_id: str, args: dict | None = None, *, engine: Any = None,
                     deps: dict | None = None) -> dict:
    """Submit applications the operator APPROVED, up to the remaining daily cap.

    The cap is re-read from the database on every iteration rather than computed once: two workers
    can run this tick concurrently, and a cap enforced from a stale count is not a cap.
    """
    from glitch_signal.agent.jobs import store
    from glitch_signal.agent.jobs import submit as _submit
    from glitch_signal.agent.jobs.discover import jobs_config

    d = deps or {}
    _do = d.get("submit") or _submit.submit
    cfg = jobs_config(brand_id)
    cap = int(cfg.get("max_applications_per_day", 3))
    out: dict[str, Any] = {"ran": "jobs_submit", "brand": brand_id, "submitted": [],
                           "manual_required": [], "errors": []}

    # Both switches, checked before a single row is read. This is the irreversible tick.
    if blocked := _off("agent_jobs_enabled", "agent_job_apply_enabled"):
        out["refused"] = f"kill-switch off: {', '.join(blocked)}"
        return out

    for app in await store.applications_by_status(brand_id, ["approved", "edited"], engine=engine):
        if await store.submitted_today(brand_id, engine=engine) >= cap:
            out["errors"].append(f"daily cap of {cap} reached; {app.get('canonical_url')} left queued")
            break
        bank = await store.answer_bank(brand_id, engine=engine)
        try:
            res = await _do(app, list((args or {}).get("questions") or []), bank)
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"submit {app.get('canonical_url')}: {str(exc)[:160]}")
            continue
        if res.get("submitted"):
            # mark_submitted is the atomic double-submit guard: False means another worker won.
            if await store.mark_submitted(str(app["id"]), res.get("evidence") or {}, engine=engine):
                out["submitted"].append({"id": str(app["id"]), "url": app.get("canonical_url")})
                log.info("jobs.submitted", brand=brand_id, url=app.get("canonical_url"))
            else:
                out["errors"].append(f"{app['id']}: already submitted by another worker")
        else:
            outcome = res.get("outcome") or "manual_required"
            await store.set_application_status(str(app["id"]), outcome, reason=res.get("reason"),
                                               engine=engine)
            out["manual_required"].append({"id": str(app["id"]), "outcome": outcome,
                                           "reason": res.get("reason"),
                                           "url": app.get("canonical_url")})
    return out
