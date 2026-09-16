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

_MAX_JOBBANK_KEYWORDS = 20
# Indeed is billed per result, so breadth costs money here in a way it does not on a free feed. Six
# queries × the per-query cap is the most one tick can order, whatever the config says.
_MAX_INDEED_QUERIES = 6


def jobs_config(brand_id: str) -> dict:
    from glitch_signal.config import brand_config

    return (brand_config(brand_id) or {}).get("jobs") or {}


def _enabled_sources(cfg: dict) -> dict:
    """Which sources the brand turned on. Absent → off; a source ships inert like everything else."""
    src = cfg.get("sources") or {}
    out = {}
    if src.get("jobbank_ca"):
        # Prefer an explicit keyword list. `target_titles` is a FILTER vocabulary — precise phrases
        # meant to match a title we already have — and it makes a poor SEARCH vocabulary: Job Bank
        # does free-text matching, so narrow phrases return almost nothing.
        out["jobbank_ca"] = cfg.get("jobbank_keywords") or cfg.get("target_titles") or []
    if src.get("ats_boards"):
        out["ats"] = cfg.get("ats_boards") or []
    if src.get("indeed"):
        # Separate from `jobbank_keywords` on purpose: this source is BILLED PER RESULT, so the
        # breadth that is free on Job Bank is not free here. A brand opts into Indeed with a short,
        # deliberate query list, not by inheriting a filter vocabulary.
        out["indeed"] = cfg.get("indeed_queries") or []
    if src.get("linkedin_alerts"):
        out["linkedin_alerts"] = [cfg.get("linkedin_alerts") or {}]
    return out


async def _gather(coros: list) -> list[dict]:
    """Run source fetches concurrently; one failing source must not lose the others' results."""
    got: list[dict] = []
    for res in await asyncio.gather(*coros, return_exceptions=True):
        if isinstance(res, BaseException):
            # The TYPE matters as much as the message: this logged eight bare `error=` lines on the
            # first live run, because several exception classes stringify to "". An error report that
            # does not say what failed is why a broken source can look like an empty one.
            log.warning("jobs.discover.source_failed", error_type=type(res).__name__,
                        error=str(res)[:200] or "(no message)")
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
    # Bounded, but generously: Job Bank is free and national, and each keyword honours a 5s crawl
    # delay, so the cost of breadth here is wall-clock rather than money or rate-limit risk.
    for kw in enabled.get("jobbank_ca", [])[:_MAX_JOBBANK_KEYWORDS]:
        coros.append(REGISTRY["jobbank_ca"](kw))
        used.append("jobbank_ca")
    for board in enabled.get("ats", []):
        provider, slug = (board.get("provider"), board.get("slug")) if isinstance(board, dict) else (None, None)
        if provider in REGISTRY and slug:
            coros.append(REGISTRY[provider](slug))
            used.append(provider)

    idx = cfg.get("indeed_options") or {}
    for q in enabled.get("indeed", [])[:_MAX_INDEED_QUERIES]:
        coros.append(REGISTRY["indeed"](q, country=idx.get("country", "CA"),
                                        location=idx.get("location"),
                                        max_items=int(idx.get("max_items_per_query", 25))))
        used.append("indeed")
    for opts in enabled.get("linkedin_alerts", []):
        coros.append(REGISTRY["linkedin_alerts"](opts))
        used.append("linkedin_alerts")

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
        stored = await store.upsert_many(brand_id, kept, engine=engine)

    summary = {"brand": brand_id, "sources": sorted(set(used)), "fetched": len(raw),
               "kept": len(kept), "filtered_out": dropped, "stored": stored, "dry_run": dry_run}
    log.info("jobs.discover", **{k: v for k, v in summary.items() if k != "stored"},
             inserted=stored["inserted"])
    return summary
