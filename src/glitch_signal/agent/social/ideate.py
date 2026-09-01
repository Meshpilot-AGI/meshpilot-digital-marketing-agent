from __future__ import annotations

import json
import re
from typing import Any

import structlog

from glitch_signal.agent.social.spec import Idea

log = structlog.get_logger(__name__)

_PROMPT = (
    "You plan ONE social content idea for brand '{brand}'. Ground it ONLY in the positioning, trend "
    "notes and brand facts below — never in prior assumptions about what a brand with this name "
    "probably does. If the positioning and your instincts disagree, the positioning wins. "
    "Reply with ONLY a JSON object: "
    '{{"angle": "<theme>", "hook": "<=12-word hook", "key_points": ["..."], '
    '"dedup_key": "<short-stable-slug-of-the-angle>"}}.\n'
    "{positioning}\n"
    "--- TREND NOTES ---\n{notes}\n\n--- BRAND FACTS ---\n{facts}\n"
)


def _parse(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw or "", re.DOTALL)
    for cand in ([m.group(0)] if m else []) + [raw or ""]:
        try:
            v = json.loads(cand)
            if isinstance(v, dict):
                return v
        except Exception:  # noqa: BLE001
            continue
    return {}


async def propose_idea(brand_id: str, *, complete=None, recall=None, positioning=None,
                       recent_keys: set[str] | None = None, engine: Any = None) -> Idea | None:
    from glitch_signal.agent.loop import llm as agent_llm
    from glitch_signal.agent.memory.store import recall as mem_recall
    from glitch_signal.agent import positioning as _positioning
    complete = complete or agent_llm.complete
    recall = recall or mem_recall
    positioning = positioning or _positioning.get
    recent_keys = recent_keys or set()
    try:
        notes = await recall(brand_id, "trending angle idea for content", k=6,
                             kinds=["episode", "fact"], engine=engine)
        facts = await recall(brand_id, "brand identity product audience", k=6,
                             kinds=["fact"], verified_only=True, engine=engine)
        notes_txt = "\n".join(f"- {m.content}" for m in notes)[:2000] or "(none)"
        facts_txt = "\n".join(f"- {m.content}" for m in facts)[:2000] or "(none)"
        pos_txt = _positioning.section(await positioning(brand_id, engine=engine))
        raw = await complete(_PROMPT.format(brand=brand_id, notes=notes_txt, facts=facts_txt,
                                            positioning=pos_txt),
                             tier="complex", timeout_s=60)
    except Exception as exc:  # noqa: BLE001
        log.warning("social.ideate_failed", error=str(exc)[:200])
        return None
    obj = _parse(raw)
    key = str(obj.get("dedup_key", "")).strip()
    if not key or not obj.get("angle") or key in recent_keys:
        return None
    return Idea(angle=str(obj["angle"]), hook=str(obj.get("hook", "")),
                key_points=[str(p) for p in (obj.get("key_points") or [])], dedup_key=key)
