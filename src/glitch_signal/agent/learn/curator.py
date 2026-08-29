"""Curator (AGENT-LEARN) — the agent's self-improvement step, Hermes-style.

After the loop runs, episodes ("what I did") accumulate in memory. The curator periodically
distills recent, not-yet-curated episodes into a few **durable lessons** — generalized,
reusable facts stored as `kind='fact'` (upserted by a stable `lesson:<slug>` key, so re-running
updates rather than duplicates). Those facts are surfaced by the loop's seed-recall on future
runs, so the agent gets better over time. Processed episodes are marked `curated` in metadata so
they aren't distilled again and recall favors the distilled lessons.

Pure orchestration with every dependency injectable (llm, remember_fn, fetch_fn, mark_fn) so it
unit-tests without network or DB. `curate()` uses the real Claude LLM + Postgres by default.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Awaitable, Callable

import structlog
from sqlalchemy import text

from glitch_signal.agent.loop import llm as agent_llm
from glitch_signal.agent.memory import store
from glitch_signal.db.session import _engine

log = structlog.get_logger(__name__)

CURATOR_SYSTEM = (
    "You are a curator that distills an autonomous marketing agent's activity log into a few "
    "DURABLE, reusable lessons for ONE brand. Generalize across episodes, deduplicate, and keep "
    "only what would help the agent act better next time (playbook heuristics, what worked / "
    "what to avoid, brand preferences). Ignore one-off specifics. Output ONLY a JSON array of "
    '{"key": "<short-stable-slug>", "content": "<one durable lesson>", "importance": <0..1>} — '
    "at most 5 items, no prose, no markdown fences."
)

_FETCH = text(
    "SELECT id, content FROM agent_memory "
    "WHERE brand_id = :brand AND kind = 'episode' "
    "AND coalesce(metadata->>'curated', '') <> 'true' "
    "ORDER BY created_at ASC LIMIT :lim"
)
_MARK = text(
    "UPDATE agent_memory SET metadata = metadata || '{\"curated\": true}'::jsonb, updated_at = now() "
    "WHERE id = ANY(string_to_array(:ids_csv, ',')::uuid[])"
)

FetchFn = Callable[[str, int], Awaitable[list[tuple[str, str]]]]
MarkFn = Callable[[list[str]], Awaitable[None]]


def _slug(s: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:48] or "lesson"
    # short hash keeps distinct lessons from colliding on a truncated slug
    h = hashlib.sha1(str(s).encode("utf-8")).hexdigest()[:8]
    return f"{base}-{h}"


def _parse_lessons(raw: str) -> list[dict]:
    """Extract the first JSON array of lesson objects from the model output."""
    if not raw:
        return []
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    for candidate in ([m.group(0)] if m else []) + [raw]:
        try:
            val = json.loads(candidate)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
        except Exception:  # noqa: BLE001
            continue
    return []


def _build_prompt(episodes: list[tuple[str, str]]) -> str:
    lines = ["Recent episodes (most recent last):", ""]
    for i, (_id, content) in enumerate(episodes, 1):
        lines.append(f"{i}. {str(content)[:600]}")
    lines += ["", "Distill these into durable lessons as the JSON array described. JSON only:"]
    return "\n".join(lines)


async def _fetch_uncurated_episodes(brand_id: str, limit: int, *, engine: Any = None) -> list[tuple[str, str]]:
    eng = engine or _engine()
    async with eng.connect() as conn:
        rows = (await conn.execute(_FETCH, {"brand": brand_id, "lim": limit})).fetchall()
    return [(str(r[0]), r[1]) for r in rows]


async def _mark_curated(ids: list[str], *, engine: Any = None) -> None:
    if not ids:
        return
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(_MARK, {"ids_csv": ",".join(ids)})


async def curate(
    brand_id: str,
    *,
    llm: Callable[..., Awaitable[str]] | None = None,
    remember_fn: Callable[..., Awaitable[Any]] | None = None,
    fetch_fn: FetchFn | None = None,
    mark_fn: MarkFn | None = None,
    limit: int = 20,
) -> dict:
    """Distill up to `limit` uncurated episodes into durable lessons. Returns counts."""
    llm = llm or agent_llm.complete
    remember_fn = remember_fn or store.remember
    fetch_fn = fetch_fn or _fetch_uncurated_episodes
    mark_fn = mark_fn or _mark_curated

    episodes = await fetch_fn(brand_id, limit)
    if not episodes:
        return {"episodes": 0, "lessons": 0}

    raw = await llm(_build_prompt(episodes), system=CURATOR_SYSTEM)
    lessons = _parse_lessons(raw)

    stored = 0
    for lesson in lessons:
        content = str(lesson.get("content", "")).strip()
        if not content:
            continue
        key = "lesson:" + _slug(lesson.get("key") or content)
        try:
            importance = float(lesson.get("importance", 0.7))
        except (TypeError, ValueError):
            importance = 0.7
        await remember_fn(brand_id, "fact", content, key=key,
                          importance=max(0.0, min(1.0, importance)), source="curator")
        stored += 1

    await mark_fn([e[0] for e in episodes])
    log.info("agent.curator.ran", brand=brand_id, episodes=len(episodes), lessons=stored)
    return {"episodes": len(episodes), "lessons": stored}
