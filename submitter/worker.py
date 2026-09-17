"""MeshPilot job submitter — the poll loop that actually applies.

The ONLY process in this system with a browser. It drains applications the operator has APPROVED in
Discord and drives the ATS's public form.

Every guard it relies on lives in the agent package (`agent/jobs/submit.py`, `store.py`), not here,
so there is exactly one implementation of the rules. This file is the loop and the switches.

Env:
  MESHPILOT_BRAND            brand id (default: tejas)
  SUBMITTER_LIVE             "true" to actually CLICK SUBMIT. Anything else = dry run. Default OFF.
  SUBMITTER_POLL_SECONDS     loop cadence (default 300)
  SUBMITTER_MAX_PER_RUN      hard ceiling per loop pass (default 1)
  SUBMITTER_SCREENSHOT_DIR   where to write evidence screenshots (default /tmp/evidence)
  DATABASE_URL / the agent's usual DB env

Three independent things must ALL be true before anything is sent:
  1. the operator reacted ✅ (status is approved/edited),
  2. `agent_job_apply_enabled` AND the publish kill-switch are on (policy gate),
  3. SUBMITTER_LIVE is true in THIS container.
Any one of them off means the run is a dry run. That redundancy is deliberate: the irreversible step
should need more than one mistake to happen by accident.
"""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("meshpilot.submitter")

BRAND = os.environ.get("MESHPILOT_BRAND", "tejas")
LIVE = os.environ.get("SUBMITTER_LIVE", "").strip().lower() == "true"
POLL_S = int(os.environ.get("SUBMITTER_POLL_SECONDS", "300"))
MAX_PER_RUN = int(os.environ.get("SUBMITTER_MAX_PER_RUN", "1"))
SHOT_DIR = os.environ.get("SUBMITTER_SCREENSHOT_DIR", "/tmp/evidence")


def identity_for(cfg: dict) -> dict:
    """Contact fields, taken from the brand config — never inferred, never guessed.

    ⚠️ `location` in the config is one string ("Toronto, ON, Canada") but Greenhouse asks for City
    and Country as SEPARATE required fields. Split on the last comma rather than parsing: the last
    segment is the country in every form of that string, and a wrong split leaves a field the form
    rejects rather than a wrong value sent to an employer. A config without a comma yields a city and
    no country, which fails visibly instead of guessing "Canada".
    """
    c = cfg.get("contact") or {}
    full = (c.get("full_name") or "").strip()
    first, _, last = full.partition(" ")
    loc = (c.get("location") or "").strip()
    city, _, country = (loc.rpartition(",") if "," in loc else (loc, "", ""))
    return {"full_name": full, "first_name": first, "last_name": last,
            "email": c.get("email", ""), "phone": c.get("phone", ""),
            "city": city.strip(), "country": country.strip(),
            "linkedin": c.get("linkedin", "")}


async def one_pass() -> dict:
    from glitch_signal.agent.jobs import artifact, factbase, store, submit
    from glitch_signal.agent.jobs.discover import jobs_config
    from glitch_signal.agent.jobs.drivers import for_ats
    from glitch_signal.agent.loop import policy

    cfg = jobs_config(BRAND)
    out = {"considered": 0, "submitted": 0, "manual": 0, "skipped": 0, "errors": []}

    approved = await store.applications_by_status(BRAND, ["approved", "edited"])
    if not approved:
        return out

    bank = await store.answer_bank(BRAND)
    identity = identity_for(cfg)
    pathlib.Path(SHOT_DIR).mkdir(parents=True, exist_ok=True)

    for app in approved[:MAX_PER_RUN]:
        out["considered"] += 1

        # The policy gate owns the daily cap and both kill-switches. Asking it here means the
        # submitter cannot outrun a limit the rest of the system believes is in force.
        allowed, reason = await policy.allow_async("job_apply", {}, BRAND)
        if not allowed:
            log.info("submitter.blocked_by_policy reason=%s", reason)
            out["skipped"] += 1
            break

        ats = submit.ats_of(app.get("canonical_url") or "")
        driver_cls = for_ats(ats or "")
        if not driver_cls:
            await store.set_application_status(str(app["id"]), "manual_required",
                                         reason=f"no driver for ats={ats}")
            out["manual"] += 1
            continue

        # Materialize the APPROVED document. `prepare()` refuses without a CV artifact, and the
        # artifact is deliberately not created until now: the PDF has nowhere durable to live (this
        # container is a poll loop that restarts), so the markdown in the database is the record and
        # this is a deterministic re-render of it. Never a fresh tailoring — what is uploaded must
        # descend from what the operator approved.
        try:
            app = dict(app)
            app["tailored_cv_path"] = artifact.ensure_cv_file(
                app, factbase.cv_text(BRAND, cfg), out_dir=SHOT_DIR)
        except Exception as exc:  # noqa: BLE001 — see below
            # Deliberately broad. This caught only (FileNotFoundError, UnverifiedCvError), so an
            # HtmlRenderError from the PDF step propagated out of one_pass and killed the WHOLE
            # sweep — one unrenderable CV stopped every other application from being considered
            # (observed live 2026-09-16: a missing Chromium binary took the loop down every pass).
            # Anything that stops this row is this row's problem, not the queue's.
            log.warning("submitter.no_approved_cv id=%s reason=%s", app.get("id"), exc)
            await store.set_application_status(str(app["id"]), "manual_required", reason=str(exc)[:300])
            out["manual"] += 1
            continue

        submit.register_driver(driver_cls(identity=identity, live=LIVE, screenshot_dir=SHOT_DIR))
        try:
            # Screening questions are whatever the form asks; we only ever answer from the bank.
            res = await submit.submit(app, list((app.get("answers") or {}).keys()), bank)
        except Exception as exc:  # noqa: BLE001 — one bad posting must not kill the loop
            out["errors"].append(f"{app['id']}: {str(exc)[:160]}")
            continue
        finally:
            submit.register_driver(None)

        if res.get("submitted"):
            if await store.mark_submitted(str(app["id"]), res.get("evidence") or {}):
                out["submitted"] += 1
                log.info("submitter.submitted app=%s url=%s", app["id"], app.get("canonical_url"))
            else:
                log.warning("submitter.race app=%s already submitted", app["id"])
        else:
            outcome = res.get("outcome") or "failed"
            if outcome in ("manual_required", "failed"):
                # A DRY RUN is not a failure — leave the row approved so a later live pass can send it.
                if not LIVE and "dry run" in (res.get("reason") or ""):
                    # Persist what the rehearsal SAW. Without this the evidence lives on this
                    # container's /tmp, which is to say nowhere — and a rehearsal nobody can inspect
                    # proves only that the code did not crash.
                    await store.record_rehearsal(str(app["id"]), res.get("evidence") or {})
                    log.info("submitter.dry_run app=%s reason=%s", app["id"], res.get("reason"))
                else:
                    await store.set_application_status(str(app["id"]), outcome, reason=res.get("reason"))
                    out["manual"] += 1
            log.info("submitter.not_submitted app=%s outcome=%s reason=%s",
                     app["id"], outcome, (res.get("reason") or "")[:160])
    return out


def preflight() -> list[str]:
    """Say plainly, at startup, what is missing — instead of letting it show up as a connection
    error every 5 minutes with no stated cause.

    An unset DATABASE_URL does NOT fail loudly on its own: `_raw_db_url()` falls back to the LOCAL
    default, so a container with no database quietly tries localhost forever. That is the failure
    mode this exists to name.
    """
    problems: list[str] = []
    try:
        from glitch_signal.config import brand_config, settings

        s = settings()
        if not s.database_url and "localhost" in s._raw_db_url():
            problems.append("DATABASE_URL is unset — falling back to the LOCAL default, so every "
                            "poll will fail to connect. Set it on this service.")
        try:
            cfg = brand_config(BRAND)
        except KeyError:
            problems.append(f"brand {BRAND!r} is not in BRAND_CONFIGS_JSON — brand config FILES are "
                            "gitignored, so that env var is the only source that reaches a container.")
        else:
            jobs = cfg.get("jobs") or {}
            if not jobs:
                problems.append(f"brand {BRAND!r} has no `jobs` block — nothing to submit for.")
            if not (jobs.get("contact") or {}).get("email"):
                problems.append("jobs.contact.email is missing — the form would be submitted with "
                                "blank contact fields.")
            if not jobs.get("approvers"):
                problems.append("jobs.approvers is empty — nobody can approve, so nothing will ever "
                                "reach this worker.")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"config could not be loaded: {str(exc)[:200]}")
    return problems


async def main() -> None:
    log.info("submitter.start brand=%s LIVE=%s poll=%ss max_per_run=%s", BRAND, LIVE, POLL_S, MAX_PER_RUN)
    for problem in preflight():
        log.error("submitter.preflight: %s", problem)
    if not LIVE:
        log.warning("submitter.DRY_RUN — forms will be filled but NOT submitted "
                    "(set SUBMITTER_LIVE=true to send)")
    while True:
        try:
            result = await one_pass()
            if result["considered"]:
                log.info("submitter.pass %s", result)
        except Exception as exc:  # noqa: BLE001 — the loop must survive a bad pass
            log.exception("submitter.pass_failed: %s", exc)
        await asyncio.sleep(POLL_S)


if __name__ == "__main__":
    asyncio.run(main())
