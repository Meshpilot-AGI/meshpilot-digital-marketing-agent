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
    """Contact fields, taken from the brand config — never inferred, never guessed."""
    c = cfg.get("contact") or {}
    full = (c.get("full_name") or "").strip()
    first, _, last = full.partition(" ")
    return {"full_name": full, "first_name": first, "last_name": last,
            "email": c.get("email", ""), "phone": c.get("phone", "")}


async def one_pass() -> dict:
    from glitch_signal.agent.jobs import store, submit
    from glitch_signal.agent.jobs.discover import jobs_config
    from glitch_signal.agent.jobs.drivers import for_ats
    from glitch_signal.agent.loop import policy

    cfg = jobs_config(BRAND)
    out = {"considered": 0, "submitted": 0, "manual": 0, "skipped": 0, "errors": []}

    approved = store.applications_by_status(BRAND, ["approved", "edited"])
    if not approved:
        return out

    bank = store.answer_bank(BRAND)
    identity = identity_for(cfg)
    pathlib.Path(SHOT_DIR).mkdir(parents=True, exist_ok=True)

    for app in approved[:MAX_PER_RUN]:
        out["considered"] += 1

        # The policy gate owns the daily cap and both kill-switches. Asking it here means the
        # submitter cannot outrun a limit the rest of the system believes is in force.
        allowed, reason = policy.allow("job_apply", {}, BRAND)
        if not allowed:
            log.info("submitter.blocked_by_policy reason=%s", reason)
            out["skipped"] += 1
            break

        ats = submit.ats_of(app.get("canonical_url") or "")
        driver_cls = for_ats(ats or "")
        if not driver_cls:
            store.set_application_status(str(app["id"]), "manual_required",
                                         reason=f"no driver for ats={ats}")
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
            if store.mark_submitted(str(app["id"]), res.get("evidence") or {}):
                out["submitted"] += 1
                log.info("submitter.submitted app=%s url=%s", app["id"], app.get("canonical_url"))
            else:
                log.warning("submitter.race app=%s already submitted", app["id"])
        else:
            outcome = res.get("outcome") or "failed"
            if outcome in ("manual_required", "failed"):
                # A DRY RUN is not a failure — leave the row approved so a later live pass can send it.
                if not LIVE and "dry run" in (res.get("reason") or ""):
                    log.info("submitter.dry_run app=%s reason=%s", app["id"], res.get("reason"))
                else:
                    store.set_application_status(str(app["id"]), outcome, reason=res.get("reason"))
                    out["manual"] += 1
            log.info("submitter.not_submitted app=%s outcome=%s reason=%s",
                     app["id"], outcome, (res.get("reason") or "")[:160])
    return out


async def main() -> None:
    log.info("submitter.start brand=%s LIVE=%s poll=%ss max_per_run=%s", BRAND, LIVE, POLL_S, MAX_PER_RUN)
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
