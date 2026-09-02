"""Persistence for what discovery has SEEN (TARGET-1).

Discovery used to be ephemeral — a pull, a model read, and the observation died with the run. That
makes two useful questions unanswerable: *have we seen this thread before?* and *which rooms keep
producing things worth answering?* Both need memory, so observations land in `signal_item`.

Deliberately dumb: this records perception, it does not decide anything. Scoring and surface
selection are separate concerns reading from here — keeping them apart means re-scoring never
requires re-fetching, which is the difference between changing our mind for free and paying the
vendor again.

Never raises into the caller's path. A failure to remember an observation must not lose the
observation itself, which the caller already holds.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)

_UPSERT = text(
    "INSERT INTO signal_item (brand_id, source, kind, external_id, surface, title, excerpt, "
    "  author, url, score, comment_count, query, raw) "
    "VALUES (:brand_id, :source, :kind, :external_id, :surface, :title, :excerpt, "
    "  :author, :url, :score, :comment_count, :query, CAST(:raw AS jsonb)) "
    "ON CONFLICT (brand_id, source, external_id) DO UPDATE SET "
    # Re-observing refreshes traction and recency; it must never duplicate the item, or "seen before"
    # stops meaning anything.
    "  score = EXCLUDED.score, comment_count = EXCLUDED.comment_count, "
    "  observed_at = now(), raw = EXCLUDED.raw"
)

_RECENT = text(
    "SELECT source, kind, external_id, surface, title, excerpt, author, url, score, "
    "       comment_count, query, observed_at "
    "FROM signal_item WHERE brand_id = :brand_id "
    "  AND (CAST(:source AS text) IS NULL OR source = :source) "
    "  AND (CAST(:surface AS text) IS NULL OR surface = :surface) "
    "ORDER BY observed_at DESC LIMIT :limit"
)

_SEEN = text(
    "SELECT external_id FROM signal_item "
    "WHERE brand_id = :brand_id AND source = :source AND external_id = ANY(:ids)"
)


def _engine_or(engine: Any):
    from glitch_signal.db.session import _engine

    return engine or _engine()


async def record(brand_id: str, source: str, kind: str, items: Iterable[dict], *,
                 query: str = "", engine: Any = None) -> int:
    """Persist observations. Returns how many rows were written, 0 on any failure."""
    import json

    rows = list(items or [])
    if not rows:
        return 0
    try:
        eng = _engine_or(engine)
        async with eng.begin() as conn:
            for it in rows:
                ext = str(it.get("id") or it.get("name") or "").strip()
                if not ext:
                    continue          # nothing to dedup on — skip rather than write a dupe magnet
                await conn.execute(_UPSERT, {
                    "brand_id": brand_id, "source": source, "kind": kind, "external_id": ext,
                    "surface": it.get("subreddit") or it.get("name"),
                    "title": it.get("title"), "excerpt": it.get("excerpt") or it.get("description"),
                    "author": it.get("author"), "url": it.get("permalink") or it.get("url"),
                    "score": it.get("upvotes") or it.get("subscribers") or it.get("score"),
                    "comment_count": it.get("comments"),
                    "query": query, "raw": json.dumps(it),
                })
        return len(rows)
    except Exception as exc:  # noqa: BLE001 — remembering must never break perceiving
        log.warning("discovery.record_failed", source=source, error=str(exc)[:200])
        return 0


async def recent(brand_id: str, *, source: str | None = None, surface: str | None = None,
                 limit: int = 25, engine: Any = None) -> list[dict]:
    """What this brand has observed lately, newest first. Empty list on any failure."""
    try:
        eng = _engine_or(engine)
        async with eng.connect() as conn:
            res = await conn.execute(_RECENT, {"brand_id": brand_id, "source": source,
                                               "surface": surface, "limit": max(1, min(limit, 200))})
            return [dict(r) for r in res.mappings().all()]
    except Exception as exc:  # noqa: BLE001
        log.warning("discovery.recent_failed", error=str(exc)[:200])
        return []


async def seen_ids(brand_id: str, source: str, ids: list[str], *, engine: Any = None) -> set[str]:
    """Which of these have we already observed — so a caller can show only what is NEW.

    Fails OPEN (empty set = "nothing seen"): a lookup failure should make us re-surface something
    already seen, never hide something new.
    """
    if not ids:
        return set()
    try:
        eng = _engine_or(engine)
        async with eng.connect() as conn:
            res = await conn.execute(_SEEN, {"brand_id": brand_id, "source": source, "ids": ids})
            return {r[0] for r in res.all()}
    except Exception as exc:  # noqa: BLE001
        log.warning("discovery.seen_failed", error=str(exc)[:200])
        return set()
