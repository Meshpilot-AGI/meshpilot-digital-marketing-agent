"""Brief → route → author: the self-driving front of the content pipeline
(GROW-SOCIAL-RENDER-4, blueprint §4.2 Stage 1–2).

Given a social post brief (hook / body / notes / platform / asset kind /
brand), this module:

  1. ROUTES (deterministic) to the right renderer:
       - text-bearing  -> design-as-code  (media/html_render.py)
       - illustrative  -> diffusion        (prompt_recipes -> muapi image)
       - motion        -> generative video (prompt_recipes -> muapi video)
       - skip          -> nothing renderable
  2. AUTHORS the structured spec the renderer needs. For text cards an LLM
     turns the brief into a CardSpec (headline/eyebrow/subhead/rows/bullets)
     with the brand VOICE injected and a COMPLIANCE guard (no profit claims,
     prohibited words, mandatory disclaimer in the footer) — the one AI step
     is layout/copy; the pixels stay deterministic (html_render).

Multi-tenant: brand voice/disclaimer/prohibited come from the brand kit
(`BrandVoice`), neutral defaults for unknown clients. The LLM completion is
injectable (`complete_fn`) so this unit-tests with no network; the default
backend uses glitch_signal's Claude API shim (`glitch_signal.agent.llm.chat`).
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

import structlog

from glitch_signal.media.html_render import CardSpec

log = structlog.get_logger(__name__)

Route = Literal["text_card", "illustrative_image", "video", "skip"]

# asset_spec.kind -> route. Text-bearing kinds go design-as-code.
_TEXT_KINDS = {"image", "screenshot", "diagram", "infographic", "poll", "carousel", "thread", "table", "quote", "stat"}
_ILLUSTRATIVE_KINDS = {"photo", "photoreal", "hero", "illustration", "background"}
_VIDEO_KINDS = {"video", "video_script", "broll", "hook", "ugc"}


def route_for(asset_kind: str) -> Route:
    k = (asset_kind or "none").lower()
    if k in _TEXT_KINDS:
        return "text_card"
    if k in _ILLUSTRATIVE_KINDS:
        return "illustrative_image"
    if k in _VIDEO_KINDS:
        return "video"
    return "skip"


# ── brand voice / compliance (from the brand kit; fintech defaults) ────
# Blueprint §5.2: no profit/guarantee claims; mandatory disclaimer.
_DEFAULT_PROHIBITED = (
    "guarantee", "guaranteed", "risk-free", "riskless", "no risk", "sure thing",
    "get rich", "moon", "lambo", "can't lose", "cant lose", "double your",
)


@dataclass
class BrandVoice:
    tone: str = "professional, confident, evidence-first; never hype"
    avoid: tuple[str, ...] = _DEFAULT_PROHIBITED
    disclaimer: str = ""        # e.g. "Educational only. Trading involves risk."
    footer: str = ""            # e.g. "glitchexecutor.com"


@dataclass
class AssetPlan:
    route: Route
    card_spec: CardSpec | None = None       # when route == text_card
    image_prompt: str | None = None          # when route == illustrative_image
    video_prompt: str | None = None          # when route == video
    aspect: str = "16:9"
    notes: str = ""
    compliance_flags: list[str] = field(default_factory=list)


class ComplianceError(RuntimeError):
    """A drafted spec contained a prohibited (e.g. profit-claim) phrase."""


def find_prohibited(text: str, avoid: tuple[str, ...]) -> list[str]:
    low = (text or "").lower()
    return sorted({w for w in avoid if w in low})


# ── LLM completion backend (injectable) ────────────────────────────────


def _default_complete(prompt: str, system: str, tier: str = "smart") -> str:
    """Real LLM call via glitch_signal's Claude API shim.

    This module's public API (`author_card_spec`, `route_and_author`) is
    synchronous, but the underlying transport is async — bridge with
    `asyncio.run` here rather than making the whole call chain async.
    """
    from glitch_signal.agent import llm as agent_llm

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    return asyncio.run(
        agent_llm.chat(messages, tier=tier, max_tokens=700, temperature=0.4)
    ) or ""


def _strip_json(s: str) -> dict[str, Any]:
    """Parse a JSON object out of an LLM response (tolerates code fences/prose)."""
    s = s.strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.MULTILINE).strip()
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in LLM output: {s[:120]!r}")
    return json.loads(s[start : end + 1])


_AUTHOR_SYSTEM = (
    "You are a social-media art director. You turn a post brief into the STRUCTURED "
    "TEXT for a clean infographic card. You write tight, factual, on-brand copy. "
    "You NEVER make profit/return guarantees or use hype. Output STRICT JSON only."
)


def author_card_spec(
    *,
    hook: str,
    body: str = "",
    notes: str = "",
    voice: BrandVoice | None = None,
    complete_fn: Callable[[str, str], str] | None = None,
) -> CardSpec:
    """LLM-author a CardSpec from a brief. Falls back to a deterministic
    card if the LLM is unavailable or returns invalid JSON. Scrubs/validates
    compliance: prohibited phrases raise; the brand disclaimer is forced into
    the footer for any brand that defines one.
    """
    voice = voice or BrandVoice()
    complete = complete_fn or _default_complete

    prompt = (
        f"BRIEF\nhook: {hook}\nbody: {body}\nasset notes: {notes}\n\n"
        f"BRAND VOICE: {voice.tone}\n"
        f"PROHIBITED words/phrases (must NOT appear): {', '.join(voice.avoid)}\n\n"
        "Produce a JSON object for an infographic card with these keys:\n"
        '  "eyebrow": short ALL-CAPS kicker (<=4 words),\n'
        '  "headline": the single punchy claim (<=10 words, exact + accurate),\n'
        '  "subhead": one clarifying sentence (optional, "" if none),\n'
        '  "rows": optional list of {"label","a","b"} for a 2-col comparison (else []),\n'
        '  "col_a","col_b": headers for the two columns (else ""),\n'
        '  "bullets": optional list of <=3 short strings (use ONLY if no rows).\n'
        "Keep all numbers/figures EXACT as given in the brief. JSON only."
    )

    spec: CardSpec
    try:
        data = _strip_json(complete(prompt, _AUTHOR_SYSTEM))
        spec = CardSpec(
            headline=str(data.get("headline") or hook).strip(),
            eyebrow=str(data.get("eyebrow") or "").strip(),
            subhead=str(data.get("subhead") or "").strip(),
            rows=[{"label": str(r.get("label", "")), "a": str(r.get("a", "")), "b": str(r.get("b", ""))}
                  for r in (data.get("rows") or []) if isinstance(r, dict)],
            col_a=str(data.get("col_a") or "").strip(),
            col_b=str(data.get("col_b") or "").strip(),
            bullets=[str(b) for b in (data.get("bullets") or [])][:3],
            footer=voice.footer,
        )
    except Exception as e:  # noqa: BLE001 — any LLM/parse failure → deterministic fallback
        log.warning("content_router.author_fallback", error=str(e)[:160])
        spec = CardSpec(headline=hook.strip(), subhead=(notes or body).strip()[:120], footer=voice.footer)

    # Compliance: prohibited phrases anywhere in the authored copy → hard error.
    blob = " ".join([spec.eyebrow, spec.headline, spec.subhead,
                     *[f"{r.get('label','')} {r.get('a','')} {r.get('b','')}" for r in spec.rows],
                     *spec.bullets])
    hits = find_prohibited(blob, voice.avoid)
    if hits:
        raise ComplianceError(f"authored card contains prohibited phrases: {hits}")

    # Force the brand disclaimer into the footer (append, don't replace a CTA footer).
    if voice.disclaimer and voice.disclaimer.lower() not in (spec.footer or "").lower():
        spec.footer = (f"{spec.footer}  ·  {voice.disclaimer}" if spec.footer else voice.disclaimer)
    return spec


def plan_asset(
    *,
    hook: str,
    body: str = "",
    notes: str = "",
    platform: str = "x",
    asset_kind: str = "screenshot",
    voice: BrandVoice | None = None,
    complete_fn: Callable[[str, str], str] | None = None,
) -> AssetPlan:
    """Route a brief and author the spec the chosen renderer needs."""
    from glitch_signal.media import prompt_recipes as pr

    route = route_for(asset_kind)
    aspect = {"x": "16:9", "reddit": "1:1", "linkedin": "1:1", "youtube": "9:16",
              "tiktok": "9:16", "instagram": "1:1"}.get(platform, "1:1")

    if route == "text_card":
        spec = author_card_spec(hook=hook, body=body, notes=notes, voice=voice, complete_fn=complete_fn)
        return AssetPlan(route=route, card_spec=spec, aspect=aspect)
    if route == "illustrative_image":
        return AssetPlan(route=route, image_prompt=pr.illustrative_image_prompt(notes or hook), aspect=aspect)
    if route == "video":
        ar, _secs = pr.platform_video_spec(platform)
        return AssetPlan(route=route, video_prompt=pr.cinematic_video_prompt(hook, "", notes), aspect=ar)
    return AssetPlan(route="skip", notes=f"no renderable route for kind={asset_kind!r}")
