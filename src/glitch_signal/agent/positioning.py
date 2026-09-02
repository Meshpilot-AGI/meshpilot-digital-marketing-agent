"""Per-brand narrative positioning — the ground truth the content pipeline writes FROM.

Separate from `agent_memory` facts (atomic "what is true" — pricing, features, brokers) because
voice, the never-say list, and positioning rationale are judgements, not facts. Without this, the
agent once generated prop-firm payout content for a brand that is not a prop firm — every individual
claim was plausible, but off-brand. Facts stop the agent being wrong; this stops it being off-brand.
Read by the ideator, the caption writer, and the conscience critic.

Stored in the DB, not on disk: the repo is open-core, so brand-specific content must never be
committed, and gitignored files under `brand/prompts/` don't survive a deploy.
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text

from glitch_signal.db.session import _engine

log = structlog.get_logger(__name__)

# Cap on what we splice into a prompt. Must stay large enough not to silently truncate mid-section —
# for a doc whose job is stating prohibitions, that means quietly dropping the rules at the bottom.
MAX_LEN = 20000


async def get(brand_id: str, *, engine: Any = None) -> str:
    """This brand's positioning doc, or '' if none is set. Never raises — a missing doc degrades to
    "no extra guidance", not a failed campaign."""
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

    Kept as values rather than parsed from the prose doc — scraping markdown for an exact hex would
    be fragile and could silently drift from what the doc says.
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

    States for CODE what the prose doc states for the models, so a prohibited phrase fails the draft
    deterministically before any paid generation instead of relying on a critic to catch it after.
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


async def get_strategy(brand_id: str, *, engine: Any = None) -> dict:
    """Content strategy for the brand ({} when unset) — currently the matrix's pillars. Lives with
    the brand, not in code, since a second brand's different pillars shouldn't need a deploy."""
    try:
        eng = engine or _engine()
        async with eng.connect() as conn:
            row = (await conn.execute(
                text("SELECT strategy FROM brand_positioning WHERE brand_id = :brand"),
                {"brand": brand_id})).first()
        val = row[0] if row else None
        if isinstance(val, str):
            import json
            val = json.loads(val)
        return val if isinstance(val, dict) else {}
    except Exception as exc:  # noqa: BLE001
        log.warning("brand.strategy_read_failed", brand_id=brand_id, error=str(exc)[:200])
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
    """Render the doc as a labelled prompt section, or '' when there is none — an empty header still
    reads to the model as "this brand has no positioning", worse than omitting the section."""
    doc = (doc or "").strip()
    return f"\n--- BRAND POSITIONING (authoritative) ---\n{doc}\n" if doc else ""
