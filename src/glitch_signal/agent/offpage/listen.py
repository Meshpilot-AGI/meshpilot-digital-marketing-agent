"""OFFPAGE-2 LISTEN (Reddit) — perceive before speaking; read-only, ~$0.002 a read.

For each of the brand's declared `offpage.audience_queries`, search Reddit (relevance sort — the
only sort that targets, measured 2026-09-02), remember every thread in `signal_item`, and remember
every community the query surfaced in `surface` so scoring and the rules sync have something to
work on. Then rescore surfaces and fetch rules for rooms that have none (Zernio, idempotent).

Nothing here decides anything. Design: docs/plans/2026-09-12-offpage-seo.md § 4 S2.
"""
from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger()

SOURCE = "reddit"
_POSTS_PER_QUERY = 25
_COMMUNITIES_PER_QUERY = 10


def queries_for(brand_id: str) -> list[str]:
    from glitch_signal.config import brand_config

    return [q for q in (brand_config(brand_id).get("offpage") or {}).get("audience_queries", [])
            if isinstance(q, str) and q.strip()]


async def run(brand_id: str, args: dict | None = None, *, engine: Any = None,
              deps: dict | None = None) -> dict:
    d = deps or {}
    queries = queries_for(brand_id)
    if not queries:
        return {"skipped": "no_audience_queries", "detail": "brand config offpage.audience_queries is empty"}

    if "search_posts" in d:
        search_posts, search_communities = d["search_posts"], d["search_communities"]
    else:
        from glitch_signal.agent.discovery.reddit import search_communities, search_posts
    if "record" in d:
        record, upsert, rescore, sync_rules = d["record"], d["upsert"], d["rescore"], d["sync_rules"]
    else:
        from glitch_signal.agent.discovery.store import record
        from glitch_signal.agent.social.surfaces import rescore, sync_rules
        from glitch_signal.agent.social.surfaces import upsert_discovered as upsert

    out: dict[str, Any] = {"ran": "offpage_listen_reddit", "queries": len(queries), "posts": 0,
                           "communities": 0, "dropped_communities": 0, "errors": []}
    rooms_with_threads: set[str] = set()
    found: dict[str, dict] = {}
    for q in queries:
        try:
            posts = (await search_posts(q, sort="relevance", time_window="week",
                                        limit=_POSTS_PER_QUERY)).get("posts", [])
            out["posts"] += await record(brand_id, SOURCE, "post", posts, query=q, engine=engine)
            rooms_with_threads |= {str(p.get("subreddit") or "").lower() for p in posts if p.get("subreddit")}
            for c in (await search_communities(q, limit=_COMMUNITIES_PER_QUERY)).get("communities", []):
                if c.get("name"):
                    found.setdefault(str(c["name"]).lower(), c)
        except Exception as exc:  # noqa: BLE001 — one query failing must not blind the rest
            out["errors"].append(f"{q[:40]}: {str(exc)[:120]}")
            log.warning("offpage.listen.query_failed", query=q, error=str(exc)[:160])
    # A community search for "prop firm challenge failed rule" returns r/electrical and r/tattooadvice
    # on the strength of a shared word. A room is a surface only if a query actually surfaced a
    # thread IN it — the same relevance-density opinion the scorer holds.
    keep = [c for name, c in found.items() if name in rooms_with_threads]
    out["dropped_communities"] = len(found) - len(keep)
    # ...and every room a thread lives in IS a surface, whether or not community search named it:
    # r/Forex and r/algotrading hold most of the threads and community search never returns them.
    known = {str(c["name"]).lower() for c in keep}
    keep += [{"name": r} for r in sorted(rooms_with_threads) if r and r not in known]
    if keep:
        try:
            out["communities"] = await upsert(brand_id, "subreddit", keep, engine=engine)
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"upsert: {str(exc)[:120]}")
    try:
        await rescore(brand_id, engine=engine)
        out["rules_synced"] = await sync_rules(brand_id, limit=10, engine=engine)
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"surfaces: {str(exc)[:120]}")
    return out
