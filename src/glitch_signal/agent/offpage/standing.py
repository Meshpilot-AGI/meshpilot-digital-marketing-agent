"""OFFPAGE-2 STANDING — the reply ladder's stage, derived from evidence, never set.

    R0  the operator posts by hand                         (always available)
    R1  the agent posts after a 2h veto window   entry: comment_karma ≥ 100 AND age ≥ 180 d
                                                        AND approvals+operator posts (30 d) ≥ 20
                                                        AND rejections (30 d) ≤ 2
    R2  no veto window                          entry: R1 AND 30 consecutive agent posts with no
                                                        rejection and no moderator removal

A removal (a `removed` status, written when a posted comment is gone 24h later) drops the stage
to R0 — it is the most recent event, so any history that starts with it fails R2, and the
30-day rejection count carries it into R1's gate. Mirrors `seo.track.standing`.
Design: docs/plans/2026-09-12-offpage-seo.md § 4 S3.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from glitch_signal.agent.offpage import store

log = structlog.get_logger()

LEVER = "reply"
SURFACE_KIND = "subreddit"
R1 = {"comment_karma": 100, "account_age_days": 180, "approvals_30d": 20, "rejections_30d": 2}
R2_CLEAN_RUN = 30


def stage_for(standing: dict | None, history: list[dict]) -> tuple[str, dict]:
    """(stage, evidence). `history` is newest-first statuses of agent posts / rejections / removals."""
    if not standing:
        return "R0", {"reason": "no standing measured yet"}
    got = {k: standing.get(k) for k in ("comment_karma", "account_age_days", "approvals_30d", "rejections_30d")}
    ev = {"karma": f"{got['comment_karma']}/{R1['comment_karma']}",
          "age_days": f"{got['account_age_days']}/{R1['account_age_days']}",
          "approvals_30d": f"{got['approvals_30d']}/{R1['approvals_30d']}",
          "rejections_30d": f"{got['rejections_30d']}/≤{R1['rejections_30d']}"}
    r1 = (int(got["comment_karma"] or 0) >= R1["comment_karma"]
          and int(got["account_age_days"] or 0) >= R1["account_age_days"]
          and int(got["approvals_30d"] or 0) >= R1["approvals_30d"]
          and int(got["rejections_30d"] or 0) <= R1["rejections_30d"])
    if not r1:
        return "R0", ev
    clean = 0
    for h in history:                      # newest first: the run must be unbroken from now
        if h["status"] == "posted_by_agent":
            clean += 1
        else:
            break
    ev["clean_run"] = f"{clean}/{R2_CLEAN_RUN}"
    return ("R2" if clean >= R2_CLEAN_RUN else "R1"), ev


def _age_days(created_utc: Any, now: datetime) -> int | None:
    try:
        return int((now - datetime.fromtimestamp(float(created_utc), tz=UTC)).days)
    except (TypeError, ValueError, OSError):
        return None


async def run(brand_id: str, args: dict | None = None, *, engine: Any = None,
              deps: dict | None = None) -> dict:
    """Measure the account and the last 30 days of decisions; write one standing row; say the stage."""
    from glitch_signal.config import brand_config

    d = deps or {}
    op = brand_config(brand_id).get("offpage") or {}
    username = str((op.get("reply") or {}).get("reddit_username") or "").strip()
    if not username:
        return {"skipped": "no_reddit_username", "detail": "brand config offpage.reply.reddit_username"}
    now = d.get("now") or datetime.now(UTC)

    if "user" in d:
        user = d["user"]
    else:
        from glitch_signal.agent.discovery.reddit import user
    profile = await user(username)
    recent = await (d.get("recent") or store.recent)(brand_id, LEVER, hours=24 * 30, engine=engine)
    counts = {"approvals_30d": sum(1 for c in recent if c["status"] in ("approved", "edited")),
              "rejections_30d": sum(1 for c in recent if c["status"] in ("rejected", "removed")),
              "posted_by_operator_30d": sum(1 for c in recent if c["status"] == "posted_by_operator")}
    row = {"account_age_days": _age_days(profile.get("created_utc"), now),
           "comment_karma": profile.get("comment_karma"), "link_karma": profile.get("link_karma"),
           "approvals_30d": counts["approvals_30d"] + counts["posted_by_operator_30d"],
           "rejections_30d": counts["rejections_30d"],
           "posted_by_operator_30d": counts["posted_by_operator_30d"]}
    await store.record_standing(brand_id, SURFACE_KIND, engine=engine, **row)
    history = await (d.get("history") or store.agent_post_history)(brand_id, LEVER, engine=engine)
    stage, ev = stage_for(row, history)
    log.info("offpage.standing", brand_id=brand_id, stage=stage, **{k: str(v) for k, v in ev.items()})
    return {"ran": "offpage_reply_standing", "username": username, "stage": stage, "evidence": ev,
            "suspended": bool(profile.get("is_suspended")), **row}


async def current_stage(brand_id: str, *, engine: Any = None) -> tuple[str, dict]:
    standing = await store.latest_standing(brand_id, SURFACE_KIND, engine=engine)
    history = await store.agent_post_history(brand_id, LEVER, engine=engine)
    return stage_for(standing, history)
