"""Content discovery for the influencer pipeline.

Produces ranked *idea* rows for the content plan so the operator always
has a populated queue to approve from. Collectors are deliberately
owned-surface + first-party (no scraping, no platform ToS grey areas):

  - pillar      : for each of the persona's content pillars, ask the LLM
                  for fresh, specific hooks in the persona's voice.
  - seasonal    : UK pet-care almanac — month-aware angles (heat, fleas,
                  fireworks, festive hazards) so posts feel timely.
  - catalog     : Ayurpet-product-anchored education (soft, value-first).

Each idea becomes a core.influencer_post_plan row at status='idea' via
content_plan.add_idea. The operator approves in the cockpit; generation
picks up from there. Ranking is a simple score the cockpit can sort by.

See docs/plans/2026-06-03-ai-influencer-engagement-research.md §discovery.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from glitch_signal.influencer.llm import complete as complete_with_fallback
from glitch_signal.influencer import content_plan
from glitch_signal.influencer.persona import Persona, load_persona

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class Idea:
    persona_id: str
    pillar: str
    hook: str
    caption: str
    platform: str = "instagram"
    format: str = "reel"
    discovery_source: str = "pillar"
    score: float = 0.5
    notes: str | None = None


# UK pet-care seasonal almanac — month -> timely angles. Kept here (not in
# the LLM) so timeliness is deterministic and auditable.
_UK_SEASONAL: dict[int, list[str]] = {
    1: ["post-festive weight reset for dogs", "winter joint stiffness in senior dogs"],
    2: ["dental health month", "kennel cough season care"],
    3: ["spring shedding & coat care", "early flea/tick prevention as it warms"],
    4: ["allergy season for dogs (pollen)", "safe spring walks & ticks"],
    5: ["heat-awareness before summer", "adder/snake awareness on UK walks"],
    6: ["heatstroke prevention", "hot-pavement paw checks", "summer hydration"],
    7: ["never-leave-dogs-in-cars", "summer grooming & cooling"],
    8: ["holiday boarding stress", "BBQ & picnic food hazards"],
    9: ["back-to-school separation anxiety", "autumn tick resurgence"],
    10: ["conker & acorn toxicity", "darker-walk visibility safety"],
    11: ["fireworks anxiety (Bonfire Night)", "joint care as cold returns"],
    12: ["festive food hazards (chocolate, raisins, xylitol)", "winter coat & paw care"],
}


def _safe_json_array(text: str) -> list[dict]:
    """Best-effort parse of an LLM JSON array; tolerant of code fences."""
    if not text:
        return []
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _persona_platform(persona: Persona) -> str:
    plats = ((persona.raw.get("posting_cadence") or {}).get("platforms")) or ["instagram"]
    return plats[0]


async def _llm_hooks(
    persona: Persona, pillar: str, context: str, *, n: int, source: str, base_score: float,
) -> list[Idea]:
    system = (
        f"You are the content strategist for {persona.display_name}, "
        f"{persona.archetype} ({persona.raw.get('backstory', '')[:240]}). "
        "Generate short-form social hooks in this creator's authentic voice. "
        "Each must be specific, scroll-stopping, and educational (not salesy). "
        "Return ONLY a JSON array of objects "
        '{"hook": str, "caption": str, "format": "reel|carousel|still"}.'
    )
    user = (
        f"Pillar: {pillar}\nContext: {context}\n"
        f"Give {n} distinct ideas as JSON. Captions <= 2 sentences, "
        "first-person, with one soft call to save/share. No hashtags."
    )
    raw = await complete_with_fallback(
        user, tier="smart", system=system, max_tokens=700, temperature=0.8
    )
    plat = _persona_platform(persona)
    out: list[Idea] = []
    for i, obj in enumerate(_safe_json_array(raw)):
        hook = (obj.get("hook") or "").strip()
        if not hook:
            continue
        out.append(Idea(
            persona_id=persona.persona_id, pillar=pillar, hook=hook,
            caption=(obj.get("caption") or "").strip(),
            platform=plat, format=(obj.get("format") or "reel").strip().lower(),
            discovery_source=source,
            score=round(base_score - i * 0.02, 3),
        ))
    return out


async def collect_pillar(persona: Persona, *, per_pillar: int = 2) -> list[Idea]:
    ideas: list[Idea] = []
    for pillar in persona.content_pillars:
        ideas += await _llm_hooks(
            persona, pillar, f"Evergreen ideas for the '{pillar}' pillar.",
            n=per_pillar, source="pillar", base_score=0.55,
        )
    return ideas


async def collect_seasonal(persona: Persona, *, month: int | None = None) -> list[Idea]:
    month = month or _dt.date.today().month
    angles = _UK_SEASONAL.get(month, [])
    if not angles:
        return []
    pillar = persona.content_pillars[0] if persona.content_pillars else "seasonal"
    ideas: list[Idea] = []
    for angle in angles:
        ideas += await _llm_hooks(
            persona, pillar, f"Timely UK seasonal angle: {angle}.",
            n=1, source="seasonal", base_score=0.7,  # timely => rank higher
        )
    return ideas


async def collect_catalog(persona: Persona, *, products: list[str] | None = None) -> list[Idea]:
    if not products:
        return []
    pillar = persona.content_pillars[-1] if persona.content_pillars else "product"
    ideas: list[Idea] = []
    for p in products:
        ideas += await _llm_hooks(
            persona, pillar,
            f"Value-first education that naturally features {p} (no hard sell).",
            n=1, source="catalog", base_score=0.5,
        )
    return ideas


async def discover(
    persona_id: str,
    *,
    per_pillar: int = 2,
    products: list[str] | None = None,
    write: bool = True,
) -> list[int]:
    """Run all collectors for a persona, writing each collector's ideas
    as soon as they're produced so partial progress always persists (the
    LLM fallback chain can be slow under provider rate-limits, and a
    timeout must not lose everything). Returns row ids."""
    persona = load_persona(persona_id)
    ids: list[int] = []

    async def _flush(ideas: list[Idea]) -> None:
        if not write:
            return
        for idea in ideas:
            try:
                rid = await content_plan.add_idea(
                    persona.brand_id, persona.persona_id,
                    discovery_source=idea.discovery_source,
                    pillar=idea.pillar, platform=idea.platform, format=idea.format,
                    hook=idea.hook, caption=idea.caption, score=idea.score,
                )
                ids.append(rid)
            except Exception as e:  # noqa: BLE001
                log.warning("influencer.discover.write_failed", error=str(e)[:160])

    # Each collector runs + persists independently; one slow/failed
    # collector can't wipe the others' output.
    for name, coro in (
        ("pillar", collect_pillar(persona, per_pillar=per_pillar)),
        ("seasonal", collect_seasonal(persona)),
        ("catalog", collect_catalog(persona, products=products)),
    ):
        try:
            batch = await coro
        except Exception as e:  # noqa: BLE001
            log.warning("influencer.discover.collector_failed", collector=name, error=str(e)[:160])
            continue
        await _flush(batch)
        log.info("influencer.discover.collector", persona=persona_id, collector=name, written=len(batch))

    log.info("influencer.discover.written", persona=persona_id, rows=len(ids))
    return ids
