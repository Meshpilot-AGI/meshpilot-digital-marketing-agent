"""Per-brand narrative positioning — the ground truth the content pipeline writes FROM.

Why this exists as its own thing, separate from `agent_memory` facts:

`agent_memory` facts are atomic and answer *"what is true about this brand"* — pricing, features,
which brokers are supported. They cannot express VOICE, the never-say list, or the reasoning behind
a positioning choice, because those aren't facts, they're judgements. That gap is not academic: with
no voice or never-say guidance reaching it, the agent generated prop-firm payout content for a brand
that is emphatically not a prop firm, and every claim in it was individually plausible.

Facts stop the agent being WRONG. This stops it being OFF-BRAND. Both are needed, and they are read
by the same three places: the ideator (what to say), the caption writer (how to say it), and the
conscience critic (whether it should have been said at all).

Stored in the DB rather than on disk because the repo is open-core — brand-specific content must
never be committed — and gitignored files under `brand/prompts/` do not survive a deploy.
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text

from glitch_signal.db.session import _engine

log = structlog.get_logger(__name__)

# Hard cap on what we splice into a prompt. A real positioning doc with voice, prohibitions AND
# visual direction runs well past a few thousand characters — the first cap silently TRUNCATED the
# doc mid-section, which for a document whose whole job is stating prohibitions means quietly
# dropping the rules at the bottom. Bounded so a runaway row still can't blow the context window.
MAX_LEN = 20000


async def get(brand_id: str, *, engine: Any = None) -> str:
    """This brand's positioning doc, or '' if none is set. Never raises.

    A missing doc must degrade to "no extra guidance", NOT to a failed campaign — the pipeline still
    has verified facts to work from.
    """
    try:
        eng = engine or _engine()
        async with eng.connect() as conn:
            row = (await conn.execute(
                text("SELECT content FROM brand_positioning WHERE brand_id = :brand"),
                {"brand": brand_id})).first()
        return (str(row[0]).strip()[:MAX_LEN]) if row and row[0] else ""
    except Exception as exc:  # noqa: BLE001 — grounding is additive; never break the run
        log.warning("brand.positioning_read_failed", brand_id=brand_id, error=str(exc)[:200])
        return ""


async def get_visual(brand_id: str, *, engine: Any = None) -> dict:
    """This brand's design tokens for the card renderer ({} when unset). Never raises.

    Kept as VALUES rather than parsed out of the prose doc: the renderer needs an exact hex, and
    scraping markdown for it would be fragile and would silently drift from what the doc says.
    """
    try:
        eng = engine or _engine()
        async with eng.connect() as conn:
            row = (await conn.execute(
                text("SELECT visual FROM brand_positioning WHERE brand_id = :brand"),
                {"brand": brand_id})).first()
        val = row[0] if row else None
        if isinstance(val, str):
            import json
            val = json.loads(val)
        return val if isinstance(val, dict) else {}
    except Exception as exc:  # noqa: BLE001 — fall back to the renderer's own defaults
        log.warning("brand.visual_read_failed", brand_id=brand_id, error=str(exc)[:200])
        return {}


async def get_guardrails(brand_id: str, *, engine: Any = None) -> dict:
    """Machine-checkable guardrails: prohibited phrases + banned imagery. {} when unset.

    The prose doc states these for the models; this states them for CODE, so a prohibited phrase
    fails the draft deterministically BEFORE any paid generation rather than depending on a critic
    noticing it afterwards.
    """
    try:
        eng = engine or _engine()
        async with eng.connect() as conn:
            row = (await conn.execute(
                text("SELECT guardrails FROM brand_positioning WHERE brand_id = :brand"),
                {"brand": brand_id})).first()
        val = row[0] if row else None
        if isinstance(val, str):
            import json
            val = json.loads(val)
        return val if isinstance(val, dict) else {}
    except Exception as exc:  # noqa: BLE001
        log.warning("brand.guardrails_read_failed", brand_id=brand_id, error=str(exc)[:200])
        return {}


async def put(brand_id: str, content: str, *, updated_by: str = "operator",
              engine: Any = None) -> None:
    """Upsert this brand's positioning doc. Operator-only by contract — see the /internal routes."""
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(
            text("INSERT INTO brand_positioning (brand_id, content, updated_by) "
                 "VALUES (:brand, :content, :by) "
                 "ON CONFLICT (brand_id) DO UPDATE SET content = excluded.content, "
                 "updated_at = now(), updated_by = excluded.updated_by"),
            {"brand": brand_id, "content": content[:MAX_LEN], "by": updated_by})


def section(doc: str) -> str:
    """Render the doc as a labelled prompt section, or '' when there is none.

    Returning '' rather than an empty header matters: an empty '--- BRAND POSITIONING ---' block
    reads to the model as "this brand has no positioning", which is worse than staying silent.
    """
    doc = (doc or "").strip()
    return f"\n--- BRAND POSITIONING (authoritative) ---\n{doc}\n" if doc else ""
