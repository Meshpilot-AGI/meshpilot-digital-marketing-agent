"""Per-platform audience and register — what the caption writer was missing.

Until now one caption was written per MEDIUM and reused across every platform of that medium: the
identical text went to X, LinkedIn and Facebook. Those are different rooms. A caption tuned for none
of them is tuned for all of them badly, and on a brand whose entire positioning is "sounds like
someone who has been there", generic copy is the specific thing that breaks it.

This is knowledge, not strategy: it says who is in the room and how to speak there. WHAT to say
still comes from the positioning doc and the matrix, and nothing here can loosen a prohibition —
the profile is additive context, the positioning remains authoritative.
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text

from glitch_signal.db.session import _engine

log = structlog.get_logger(__name__)


async def profile(brand_id: str, platform: str, *, engine: Any = None) -> dict:
    """One platform's profile, or {} when unset. Never raises — an absent profile degrades to the
    previous behaviour (a medium-level caption), not a failed post."""
    try:
        eng = engine or _engine()
        async with eng.connect() as conn:
            row = (await conn.execute(
                text("SELECT platform, audience, register, max_chars, hashtags, avoid "
                     "FROM platform_profile WHERE brand_id = :b AND platform = :p"),
                {"b": brand_id, "p": (platform or "").lower()})).mappings().first()
        return dict(row) if row else {}
    except Exception as exc:  # noqa: BLE001
        log.warning("social.platform_profile_failed", platform=platform, error=str(exc)[:200])
        return {}


def section(p: dict) -> str:
    """Render a profile as prompt context, or '' when there is none.

    '' rather than an empty header, for the same reason as everywhere else in this pipeline: an
    empty labelled block invites the model to fill it from its own priors.
    """
    if not p:
        return ""
    lines = [f"\n--- WRITING FOR {str(p.get('platform', '')).upper()} ---",
             f"Audience here: {p['audience']}",
             f"Register: {p['register']}"]
    if p.get("max_chars"):
        lines.append(f"Hard limit: {p['max_chars']} characters. Stay comfortably under it.")
    if p.get("hashtags"):
        lines.append(f"Hashtags: {p['hashtags']}")
    if p.get("avoid"):
        lines.append(f"Does NOT work here: {p['avoid']}")
    lines.append("This shapes HOW you say it. The brand positioning still governs WHAT you may say "
                 "and must never be relaxed to suit the platform.")
    return "\n".join(lines) + "\n"


def mention_line(handles: list[str], platform: str) -> str:
    """Instruction to tag the accounts we hold VERIFIED handles for, or '' when we hold none.

    Never guessed. A wrong handle tags a real stranger's account in public — a worse outcome than
    not tagging at all — so an unknown handle simply means the post names the company in plain text.
    """
    real = [h for h in handles if h]
    if not real:
        return ""
    return (f"\nTag these accounts naturally in the copy where they are already mentioned: "
            f"{', '.join(real)}. Do not invent any other handle, and do not add tags for companies "
            f"the post does not discuss.\n")


async def handles_for(brand_id: str, firm_names: list[str], platform: str,
                      *, engine: Any = None) -> list[str]:
    """Verified handles for the named companies on this platform. Absent handle -> not tagged."""
    if not firm_names:
        return []
    try:
        from glitch_signal.agent import assets

        found = await assets.resolve_named(brand_id, firm_names, kind="logo", engine=engine)
        out: list[str] = []
        for a in found:
            h = (a.get("handles") or {}).get((platform or "").lower())
            if h:
                out.append(str(h))
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("social.handles_lookup_failed", error=str(exc)[:200])
        return []
