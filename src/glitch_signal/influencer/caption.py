"""Caption + hashtag composition for the influencer posting step.

Turns a content-plan row into a publish-ready Instagram caption in the
persona's voice: a few first-person lines, a soft save/follow nudge, a
deduped hashtag line, and the persona's AI-creator disclosure appended
for platform compliance.

Used by pipeline.posting_tick so every post gets a proper caption
automatically — no operator copywriting required. If the operator DID
author a full caption (multi-line or already has hashtags), it's kept
verbatim; otherwise we generate one from the row's hook/pillar.

Gemini-first via influencer.llm; deterministic fallback so posting never
blocks on the LLM.
"""
from __future__ import annotations

import re

from glitch_signal.influencer import llm
from glitch_signal.influencer.persona import Persona

_IG_MAX = 2200  # Instagram caption hard limit


def _clean(text: str) -> str:
    """Strip 'Caption:'/'Hashtags:' labels, split body vs tags, dedupe tags."""
    text = re.sub(r"(?im)^\s*(caption|hashtags?)\s*:\s*", "", text or "")
    lines = [l.strip() for l in text.splitlines()]
    body = [l for l in lines if l and not l.startswith("#")]
    tags = [w for l in lines for w in l.split() if w.startswith("#")]
    cap = "\n".join(body[:5]).strip()
    if tags:
        cap += "\n\n" + " ".join(dict.fromkeys(tags))  # dedupe, single line
    return cap.strip()


def _looks_authored(caption: str | None) -> bool:
    """Heuristic: did a human write a full caption already?"""
    c = (caption or "").strip()
    return bool(c) and ("#" in c or "\n" in c or len(c) > 120)


def _disclosure(persona: Persona) -> str:
    d = (persona.raw.get("disclosure") or "").strip()
    return f"\n\nℹ️ {d}" if d else ""


async def compose(persona: Persona, row: dict) -> str:
    """Generate a fresh, publish-ready caption for this row."""
    pillar = row.get("pillar") or "pet care"
    hook = row.get("hook") or row.get("caption") or "a moment from my day"
    companion = (persona.companion or {}).get("name", "")
    system = (
        f"You are {persona.display_name}, {persona.archetype}. Output ONLY the "
        "Instagram caption text — no preamble, and do NOT write the words "
        "'Caption' or 'Hashtags'. Format: 3-4 short first-person lines (at most "
        "one emoji per line), then a soft 'save this / follow' nudge, then a "
        "blank line, then 10-14 relevant hashtags on ONE line mixing pet care, "
        "dogs, natural/ayurvedic pet health and UK/London. Educational and warm, "
        "never salesy, never give individual medical advice."
    )
    user = (
        f"Pillar: {pillar}\nTopic/hook: {hook}\n"
        + (f"Your dog {companion} can feature.\n" if companion else "")
        + "Write the caption now."
    )
    raw = await llm.complete(user, system=system, max_tokens=380, temperature=0.7)
    cap = _clean(raw)
    if not cap or len(cap) < 30:
        # deterministic fallback
        cap = (
            f"{hook}\n\nA little moment from my day"
            + (f" with {companion}" if companion else "")
            + ". Save this for later and follow along! 🐾\n\n"
            "#VetLife #PetCare #DogsOfInstagram #NaturalPetHealth #AyurvedaForPets "
            "#LondonPets #HealthyPets #PetWellness #DogCare #FollowForMore"
        )
    cap = cap + _disclosure(persona)
    return cap[:_IG_MAX].rstrip()


async def final_caption(persona: Persona, row: dict) -> str:
    """Caption to actually publish: keep an operator-authored caption,
    else compose one. Always ensures the disclosure is present."""
    existing = (row.get("caption") or "").strip()
    if _looks_authored(existing):
        disc = (persona.raw.get("disclosure") or "").strip()
        if disc and disc not in existing:
            existing = f"{existing}\n\nℹ️ {disc}"
        return existing[:_IG_MAX].rstrip()
    return await compose(persona, row)
