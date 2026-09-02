"""Per-platform audience and register — what the caption writer was missing.

Previously one caption was written per medium and reused verbatim across X, LinkedIn and Facebook —
different rooms, so copy tuned for none of them is tuned for all of them badly.

Knowledge, not strategy: it says who is in the room and how to speak there. WHAT to say still comes
from the positioning doc and the matrix; nothing here can loosen a prohibition.
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text

from glitch_signal.db.session import _engine

log = structlog.get_logger(__name__)

# Reserved brand_id holding generic, public-knowledge per-platform defaults (seeded in the
# `platform_profile_defaults` migration). This repo is open-core, so a real brand's specific
# voice/register can never be committed — but a brand can still ship with a non-empty profile by
# falling back to this row when it has not set its own.
_DEFAULT_BRAND = "_default"


async def profile(brand_id: str, platform: str, *, engine: Any = None) -> dict:
    """One platform's profile: the brand's own if it has set one, else the generic default, else {}.

    Never raises — an absent profile degrades to the previous behaviour (a medium-level caption),
    not a failed post."""
    try:
        eng = engine or _engine()
        p = (platform or "").lower()
        async with eng.connect() as conn:
            row = (await conn.execute(
                text("SELECT platform, audience, register, max_chars, hashtags, avoid "
                     "FROM platform_profile WHERE platform = :p "
                     "  AND brand_id IN (:b, :default_brand) "
                     "ORDER BY (brand_id = :b) DESC LIMIT 1"),
                {"b": brand_id, "p": p, "default_brand": _DEFAULT_BRAND})).mappings().first()
        return dict(row) if row else {}
    except Exception as exc:  # noqa: BLE001
        log.warning("social.platform_profile_failed", platform=platform, error=str(exc)[:200])
        return {}


def section(p: dict) -> str:
    """Render a profile as prompt context, or '' when there is none — an empty labelled block would
    invite the model to fill it from its own priors."""
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
    """Instruction to tag verified handles, or '' when we hold none — never guessed, since a wrong
    handle tags a real stranger's account in public, worse than not tagging at all."""
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
        key = (platform or "").lower()
        if key.startswith("_"):
            return []                       # reserved provenance keys are not platforms
        for a in found:
            h = (a.get("handles") or {}).get(key)
            if h:
                out.append(str(h))
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("social.handles_lookup_failed", error=str(exc)[:200])
        return []
