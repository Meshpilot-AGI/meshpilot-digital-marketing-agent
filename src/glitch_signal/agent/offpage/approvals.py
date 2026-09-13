"""OFFPAGE-2 APPROVALS — the operator's one-tap loop, over Discord REST.

A candidate becomes a card in `#approvals`; the operator reacts; a cron tick reads the reactions
back into the row. REST polling, not a gateway session: a bot token allows exactly one gateway
connection and the Railway bridge holds it.

    ✅  I'll post this            → approved
    ✏️  posted my own version     → edited
    📤  posted as-is              → posted_by_operator
    ❌  no                        → rejected

Only reactions from `offpage.approvers` (Discord user ids) count; the bot's own legend reactions
never do. Precedence when several are present: 📤, ✏️, ❌, ✅ — an action beats an intention, and a no
beats a yes. Cards expire after `offer_ttl_hours` (threads go stale); expiry is not a rejection.
Design: docs/plans/2026-09-12-offpage-seo.md § 6.
"""
from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import structlog

from glitch_signal.agent.offpage import store

log = structlog.get_logger()

LEVER = "reply"
REACTIONS = {"📤": "posted_by_operator", "✏️": "edited", "❌": "rejected", "✅": "approved"}
LEGEND = "✅ I'll post it · ✏️ posted my own version · 📤 posted as-is · ❌ no"


def settings_for(brand_id: str) -> dict:
    from glitch_signal.config import brand_config

    op = brand_config(brand_id).get("offpage") or {}
    return {"channel_id": str(op.get("approvals_channel_id") or ""),
            "approvers": {str(a) for a in op.get("approvers", [])},
            "token": os.environ.get("DISCORD_BOT_TOKEN", "")}


def card(brand_id: str, cand: dict) -> str:
    meta = cand.get("draft_meta") or {}
    parts = meta.get("score_parts") or {}
    why = " · ".join(f"{k} {v:.2f}" if isinstance(v, (int, float)) else f"{k} {v}" for k, v in parts.items())
    head = (f"**[reply · r/{cand.get('surface')} · score {float(cand.get('score') or 0):.2f}]** "
            f"{brand_id}\n{cand.get('target_url')}\n"
            f"*{(meta.get('title') or '')[:160]}*\n"
            f"why: {why or 'n/a'} · brand mention {'allowed' if meta.get('mention_allowed') else 'not allowed'}\n")
    body = f"```\n{cand.get('draft', '')[:1800]}\n```\n{LEGEND}"
    return (head + body)[:1990]


async def _api(method: str, path: str, token: str, *, json_body: dict | None = None) -> Any:
    from glitch_signal.comms.discord import _api as discord_api

    return await discord_api(method, path, token, json_body=json_body)


async def offer(brand_id: str, cand: dict, *, api: Any = None) -> str:
    """Post the card and pre-seed the legend reactions; returns the Discord message id."""
    s = settings_for(brand_id)
    if not (s["channel_id"] and s["token"]):
        raise RuntimeError("offpage.approvals: approvals_channel_id or DISCORD_BOT_TOKEN missing")
    api = api or _api
    msg = await api("POST", f"/channels/{s['channel_id']}/messages", s["token"],
                    json_body={"content": card(brand_id, cand),
                               "allowed_mentions": {"parse": []}})
    mid = str(msg["id"])
    for emoji in REACTIONS:
        try:
            await api("PUT", f"/channels/{s['channel_id']}/messages/{mid}/reactions/{quote(emoji)}/@me",
                      s["token"])
        except Exception as exc:  # noqa: BLE001 — a missing legend reaction is cosmetic
            log.warning("offpage.approvals.legend_failed", emoji=emoji, error=str(exc)[:120])
    return mid


async def read_decision(brand_id: str, msg_id: str, *, api: Any = None) -> str | None:
    """The operator's decision on a card, or None if none yet.

    One GET for the message: its `reactions` carry counts, and the bot's own legend reaction makes
    every count 1 — so only an emoji with count > 1 is worth the per-emoji users call. Four users
    calls per card per tick was a 429 on the first real tick (Discord's reaction route is tight)."""
    s = settings_for(brand_id)
    api = api or _api
    msg = await api("GET", f"/channels/{s['channel_id']}/messages/{msg_id}", s["token"])
    counts = {r.get("emoji", {}).get("name"): int(r.get("count") or 0) for r in (msg or {}).get("reactions", [])}
    for emoji, status in REACTIONS.items():           # dict order = precedence
        if counts.get(emoji, 0) < 2 and counts.get(emoji.rstrip("\ufe0f"), 0) < 2:
            continue
        await asyncio.sleep(0.35)                     # stay under the per-route bucket
        users = await api("GET", f"/channels/{s['channel_id']}/messages/{msg_id}/reactions/{quote(emoji)}",
                          s["token"])
        if any(str(u.get("id")) in s["approvers"] for u in (users or [])):
            return status
    return None


async def run(brand_id: str, args: dict | None = None, *, engine: Any = None,
              deps: dict | None = None) -> dict:
    """The decide tick: read reactions on every offered card; expire the stale ones; re-offer
    drafts whose card never posted."""
    d = deps or {}
    read = d.get("read_decision") or read_decision
    do_offer = d.get("offer") or offer
    out: dict[str, Any] = {"ran": "offpage_decide", "decided": [], "expired": [], "reoffered": 0,
                           "errors": []}

    out["expired"] = await store.expire_stale(brand_id, LEVER, engine=engine)
    for c in await store.by_status(brand_id, LEVER, ["offered"], engine=engine):
        try:
            await asyncio.sleep(0.35)
            status = await read(brand_id, c["discord_msg_id"])
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"{c['id']}: {str(exc)[:120]}")
            continue
        if status:
            await store.set_status(c["id"], status, decided=True, engine=engine)
            out["decided"].append({"id": c["id"], "status": status, "url": c["target_url"]})
            log.info("offpage.decided", candidate=c["id"], status=status)
    for c in await store.by_status(brand_id, LEVER, ["drafted"], engine=engine):
        created = c["created_at"]
        created = created.replace(tzinfo=UTC) if created.tzinfo is None else created
        if (datetime.now(UTC) - created).total_seconds() > 36 * 3600:
            await store.set_status(c["id"], "expired", engine=engine)
            out["expired"].append(c["id"])
            continue
        try:
            mid = await do_offer(brand_id, c)
            await store.mark_offered(c["id"], mid, ttl_hours=36, engine=engine)
            out["reoffered"] += 1
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"{c['id']}: offer {str(exc)[:120]}")
    return out
