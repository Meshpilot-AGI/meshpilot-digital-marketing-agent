"""Discovery — run the brand's enabled sources, filter, dedup, store.

The order is load-bearing:

    fetch → filter (cheap, no LLM) → canonicalize → dedup → store

Filtering before storage keeps the table honest: `job_listing` holds postings we would consider,
not everything the internet emitted. Canonicalizing before dedup is what lets the same posting
arrive from three sources and land as one row.

Nothing here scores, drafts or applies. Discovery is read-only with respect to the outside world.
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog

from glitch_signal.agent.jobs import filters, store
from glitch_signal.agent.jobs.sources import REGISTRY

log = structlog.get_logger()


def jobs_config(brand_id: str) -> dict:
    from glitch_signal.config import brand_config

    return (brand_config(brand_id) or {}).get("jobs") or {}


def _enabled_sources(cfg: dict) -> dict:
    """Which sources the brand turned on. Absent → off; a source ships inert like everything else."""
    src = cfg.get("sources") or {}
    out = {}
    if src.get("jobbank_ca"):
        out["jobbank_ca"] = cfg.get("target_titles") or []
    if src.get("ats_boards"):
        out["ats"] = cfg.get("ats_boards") or []
    return out


async def _gather(coros: list) -> list[dict]:
    """Run source fetches concurrently; one failing source must not lose the others' results."""
    got: list[dict] = []
    for res in await asyncio.gather(*coros, return_exceptions=True):
        if isinstance(res, BaseException):
            log.warning("jobs.discover.source_failed", error=str(res)[:200])
            continue
        got.extend(res or [])
    return got


async def discover(brand_id: str, *, dry_run: bool = False, engine: Any = None) -> dict:
    """Run discovery for a brand. Returns a summary dict (never raises on a single bad source)."""
    cfg = jobs_config(brand_id)
    enabled = _enabled_sources(cfg)
    if not enabled:
        return {"brand": brand_id, "sources": [], "fetched": 0, "kept": 0,
                "stored": {"seen": 0, "inserted": 0, "updated": 0},
                "note": "no sources enabled in brand config `jobs.sources`"}

    coros = []
    used: list[str] = []
    for kw in enabled.get("jobbank_ca", [])[:8]:   # bounded: each keyword is its own paged sweep
        coros.append(REGISTRY["jobbank_ca"](kw))
        used.append("jobbank_ca")
    for board in enabled.get("ats", []):
        provider, slug = (board.get("provider"), board.get("slug")) if isinstance(board, dict) else (None, None)
        if provider in REGISTRY and slug:
            coros.append(REGISTRY[provider](slug))
            used.append(provider)

    raw = await _gather(coros)

    kept, dropped = [], 0
    seen_urls: set[str] = set()
    for item in raw:
        url = item.get("canonical_url")
        if not url or url in seen_urls:          # in-batch dedup; the DB handles cross-run dedup
            dropped += 1
            continue
        ok, _why = filters.passes(item.get("title"), item.get("location"), cfg)
        if not ok:
            dropped += 1
            continue
        seen_urls.add(url)
        kept.append(item)

    stored = {"seen": 0, "inserted": 0, "updated": 0}
    if kept and not dry_run:
        stored = store.upsert_many(brand_id, kept, engine=engine)

    summary = {"brand": brand_id, "sources": sorted(set(used)), "fetched": len(raw),
               "kept": len(kept), "filtered_out": dropped, "stored": stored, "dry_run": dry_run}
    log.info("jobs.discover", **{k: v for k, v in summary.items() if k != "stored"},
             inserted=stored["inserted"])
    return summary
