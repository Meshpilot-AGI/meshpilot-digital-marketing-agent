"""JOBS-5 APPROVALS — one card, one role, one decision.

Operator decision 3 (design § 11): approve EACH application. No batching, no "apply to all of
these". A card carries everything that would be sent, and nothing is submitted that the operator has
not seen in full.

    ✅  apply — send it as drafted
    ✏️  apply with my edits — the operator edits in-thread first
    ⏸️  hold — keep it, re-surface tomorrow
    ❌  skip

Precedence when several are present: ❌, ⏸️, ✏️, ✅ — a no beats a yes, and an explicit hold beats an
approval. The asymmetry is deliberate: an accidental extra ✅ next to a ❌ must never send.

**Expiry is not approval.** A card that ages out is `expired`, never submitted. The failure mode this
prevents is an operator who never saw the card — silence is not consent, and a system that treats a
timeout as a yes will eventually apply to something behind their back.

Mechanics reuse the OFF-PAGE pattern (`agent/offpage/approvals.py`), including its rate-limit
lesson: read reactions with ONE message GET and only spend a per-emoji `users` call when a count
exceeds the bot's own legend reaction. Four users-calls per card per tick 429'd on its first real
tick.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any
from urllib.parse import quote

import structlog

log = structlog.get_logger()

# Dict order IS the precedence order. Do not reorder casually.
REACTIONS = {"❌": "rejected", "⏸️": "hold", "✏️": "edited", "✅": "approved"}
LEGEND = "✅ apply · ✏️ apply with my edits · ⏸️ hold · ❌ skip"
DEFAULT_TTL_HOURS = 48


def settings_for(brand_id: str) -> dict:
    from glitch_signal.config import brand_config

    jobs = (brand_config(brand_id) or {}).get("jobs") or {}
    return {"channel_id": str(jobs.get("approvals_channel_id") or ""),
            "approvers": {str(a) for a in jobs.get("approvers", [])},
            "ttl_hours": int(jobs.get("offer_ttl_hours") or DEFAULT_TTL_HOURS),
            "token": os.environ.get("DISCORD_BOT_TOKEN", "")}


def card(brand_id: str, application: dict) -> str:
    """The approval card. Everything that would be submitted must be visible here."""
    parts = application.get("score_parts") or {}
    why = " · ".join(f"{k} {v}" for k, v in parts.items() if k in
                     ("requirements", "critical", "strong", "none"))
    wa = application.get("work_auth") or "unknown"
    answers = application.get("answers") or {}
    ans_txt = "\n".join(f"  • {q}: {a}" for q, a in list(answers.items())[:6]) or "  • (none)"
    head = (f"**[apply · score {application.get('score')}/5]** {application.get('company') or '?'}\n"
            f"**{application.get('title') or '?'}** — {application.get('location') or 'location not stated'}\n"
            f"{application.get('canonical_url')}\n"
            f"work-auth: {wa} · {why or 'n/a'}\n\n"
            f"__Answers that would be submitted:__\n{ans_txt}\n\n"
            f"__Tailored CV (first lines):__")
    cv = (application.get("tailored_cv") or "").strip().splitlines()
    body = "```\n" + "\n".join(cv[:14])[:1200] + "\n```\n" + LEGEND
    return (head + "\n" + body)[:1990]


async def _api(method: str, path: str, token: str, *, json_body: dict | None = None) -> Any:
    from glitch_signal.comms.discord import _api as discord_api

    return await discord_api(method, path, token, json_body=json_body)


async def offer(brand_id: str, application: dict, *, api: Any = None) -> str:
    """Post the card and pre-seed the legend reactions. Returns the Discord message id."""
    s = settings_for(brand_id)
    if not (s["channel_id"] and s["token"]):
        raise RuntimeError("jobs.approvals: jobs.approvals_channel_id or DISCORD_BOT_TOKEN missing")
    api = api or _api
    msg = await api("POST", f"/channels/{s['channel_id']}/messages", s["token"],
                    json_body={"content": card(brand_id, application),
                               "allowed_mentions": {"parse": []}})
    mid = str(msg["id"])
    for emoji in REACTIONS:
        try:
            await api("PUT", f"/channels/{s['channel_id']}/messages/{mid}/reactions/{quote(emoji)}/@me",
                      s["token"])
        except Exception as exc:  # noqa: BLE001 — a missing legend reaction is cosmetic
            log.warning("jobs.approvals.legend_failed", emoji=emoji, error=str(exc)[:120])
    return mid


async def read_decision(brand_id: str, msg_id: str, *, api: Any = None) -> str | None:
    """The operator's decision, or None. Thin wrapper — see `read_decision_actor` for the approver."""
    decided = await read_decision_actor(brand_id, msg_id, api=api)
    return decided[0] if decided else None


async def read_decision_actor(brand_id: str, msg_id: str, *,
                              api: Any = None) -> tuple[str, str] | None:
    """(decision, approver's Discord id), or None if they have not reacted.

    ⚠️ This function already had to identify the reacting user in order to check them against the
    allowlist — and it threw the id away, so every approval recorded WHO as NULL. On the one action
    in this system that is irreversible and taken in the operator's name, "someone on the allowlist"
    is a weaker audit trail than the code can trivially provide.

    Only reactions from `jobs.approvers` count. The bot's own legend reaction makes every count 1,
    so a count of 1 is noise; only >1 is worth a per-emoji users call (rate-limit lesson from
    OFF-PAGE). An empty approvers list means NOBODY can approve — deliberately fail-safe.
    """
    s = settings_for(brand_id)
    api = api or _api
    msg = await api("GET", f"/channels/{s['channel_id']}/messages/{msg_id}", s["token"])
    counts: dict[str, int] = {}
    for r in (msg or {}).get("reactions", []) or []:
        name = (r.get("emoji") or {}).get("name")
        if name:
            counts[name] = int(r.get("count") or 0)
    for emoji, status in REACTIONS.items():           # dict order = precedence
        if counts.get(emoji, 0) < 2 and counts.get(emoji.rstrip("️"), 0) < 2:
            continue
        await asyncio.sleep(0.35)                     # stay under the per-route bucket
        users = await api("GET",
                          f"/channels/{s['channel_id']}/messages/{msg_id}/reactions/{quote(emoji)}",
                          s["token"])
        actor = next((str(u.get("id")) for u in (users or []) if str(u.get("id")) in s["approvers"]),
                     None)
        if actor:
            return status, actor
    return None


async def run(brand_id: str, args: dict | None = None, *, engine: Any = None,
              deps: dict | None = None) -> dict:
    """The decide tick: expire stale cards, then read reactions on every offered card.

    Order matters. Expiry runs FIRST so a card that timed out is never read for a late reaction —
    once expired it stays expired, and a reaction arriving after the window does not resurrect it.
    Treating a late yes as approval would mean submitting on the operator's behalf long after they
    stopped paying attention to that role.
    """
    from glitch_signal.agent.jobs import store

    d = deps or {}
    read = d.get("read_decision") or read_decision_actor
    out: dict[str, Any] = {"ran": "jobs_decide", "decided": [], "expired": [], "errors": []}

    out["expired"] = await store.expire_stale(brand_id, engine=engine)
    for app in await store.applications_by_status(brand_id, ["awaiting_approval"], engine=engine):
        if not app.get("discord_msg_id"):
            continue
        try:
            await asyncio.sleep(0.35)
            decided = await read(brand_id, app["discord_msg_id"])
        except Exception as exc:  # noqa: BLE001 — one unreadable card must not stop the rest
            out["errors"].append(f"{app['id']}: {str(exc)[:120]}")
            continue
        if not decided:
            continue
        status, actor = decided
        if status == "hold":
            # Keep it queued and push the window out; a hold is explicitly NOT a decision.
            await store.mark_offered(str(app["id"]), app["discord_msg_id"],
                               ttl_hours=settings_for(brand_id)["ttl_hours"], engine=engine)
        else:
            await store.set_application_status(str(app["id"]), status, by=actor,
                                         approved=(status in ("approved", "edited")), engine=engine)
        out["decided"].append({"id": str(app["id"]), "status": status, "by": actor,
                               "url": app.get("canonical_url")})
        log.info("jobs.decided", application=str(app["id"]), status=status, by=actor)
    return out
