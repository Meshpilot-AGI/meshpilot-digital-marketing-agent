"""Brief → ROUTE → AUTHOR: the self-driving front of the creative pipeline.

Adapted from the monorepo's `media/content_router.py`. The shape that matters, and the thing the
previous pipeline lacked entirely:

  1. ROUTE, deterministically, on what the post IS. A comparison of two rules wants a structured
     card; a conceptual idea wants a generated still; a demonstration wants motion. Nothing here is
     hardcoded to one renderer — `asset_kind` comes from the agent when it decides what to post, so
     "today I should contrast our 50M rule against another firm's" routes itself.
  2. AUTHOR the spec that renderer needs, refining a LOOSE brief into a model-ready one. This is the
     step whose absence made the last campaign generic: it sent `f"{angle}: {hook}"` straight to a
     photorealism model. One LLM step shapes structure and copy; the technique functions and the
     card renderer stay deterministic.
  3. GUARD. Prohibited phrases fail the draft closed, before any paid generation.

Brand voice, palette and prohibitions are read from the brand's own positioning row — never
hardcoded here — so a second brand gets its own art direction with no code change.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

import structlog

from glitch_signal.agent.social import technique

log = structlog.get_logger(__name__)

Route = Literal["card", "image", "poster", "video", "skip"]

# asset_kind -> route. Text-BEARING and structured kinds render deterministically (exact copy,
# exact brand type); conceptual kinds go to the image model; motion goes to video.
_CARD_KINDS = {"comparison", "definition", "glossary", "list", "numbered", "checklist",
               "statement", "quote", "diagram", "mechanism", "table"}
_IMAGE_KINDS = {"concept", "conceptual", "illustration", "metaphor", "object", "photo", "hero"}
_POSTER_KINDS = {"poster", "headline_image", "announcement"}
_VIDEO_KINDS = {"video", "motion", "demo", "broll"}

# asset_kind -> the card layout that kind implies (see media/render/layouts.py).
_CARD_LAYOUT = {
    "comparison": "comparison", "table": "comparison",
    "definition": "definition", "glossary": "definition",
    "list": "numbered", "numbered": "numbered", "checklist": "numbered",
    "diagram": "mechanism", "mechanism": "mechanism",
}


def route_for(asset_kind: str) -> Route:
    k = (asset_kind or "").strip().lower()
    if k in _CARD_KINDS:
        return "card"
    if k in _POSTER_KINDS:
        return "poster"
    if k in _IMAGE_KINDS:
        return "image"
    if k in _VIDEO_KINDS:
        return "video"
    return "skip"


def layout_for(asset_kind: str) -> str:
    return _CARD_LAYOUT.get((asset_kind or "").strip().lower(), "statement")


class ComplianceError(RuntimeError):
    """A drafted brief contained a prohibited phrase — fail before spending on generation."""


@dataclass
class BrandVoice:
    """Art direction + guardrails, loaded from the brand's positioning row."""

    style: str = "restrained editorial, conceptual object photography, no people"
    palette: str = "near-black ground with a single accent"
    banned_imagery: str = ""
    prohibited: tuple[str, ...] = ()
    wordmark: str = ""
    # Who the brand talks to, who fronts the video, and what its imagery is OF. Declared per brand
    # in the positioning row's `visual` block — these used to be trading/GE literals in the prompt
    # builders, which silently made every brand a prop-firm brand.
    audience: str = "the people this brand serves"
    presenter: str = "one presenter, visible and speaking to camera throughout"
    subjects: tuple[str, ...] = ()

    @classmethod
    def from_brand(cls, visual: dict | None, guardrails: dict | None) -> "BrandVoice":
        v, g = visual or {}, guardrails or {}
        return cls(
            style=str(v.get("style") or cls.style),
            palette=str(v.get("palette") or cls.palette),
            banned_imagery=str(g.get("banned_imagery") or ""),
            prohibited=tuple(str(x).lower() for x in (g.get("prohibited") or ())),
            wordmark=str(v.get("wordmark") or ""),
            audience=str(v.get("audience") or cls.audience),
            presenter=str(v.get("presenter") or cls.presenter),
            subjects=tuple(str(x) for x in (v.get("subjects") or ()) if str(x).strip()),
        )


@dataclass
class AssetPlan:
    route: Route
    prompt: str = ""                      # image / poster / video routes
    layout: str = ""                      # card route
    fields: dict[str, Any] = field(default_factory=dict)   # card route content
    aspect: str = technique.DEFAULT_ASPECT
    reason: str = ""


def find_prohibited(text: str, avoid: tuple[str, ...]) -> list[str]:
    low = (text or "").lower()
    return sorted({w for w in avoid if w and w in low})


def _strip_json(s: str) -> dict:
    s = re.sub(r"^```(?:json)?|```$", "", (s or "").strip(), flags=re.MULTILINE).strip()
    a, b = s.find("{"), s.rfind("}")
    if a == -1 or b == -1:
        raise ValueError(f"no JSON object in LLM output: {s[:120]!r}")
    return json.loads(s[a:b + 1])


_SYSTEM = (
    "You are a social-media art director. You turn a rough post idea into a precise creative brief. "
    "You never invent facts, figures or claims that were not in the idea, and you never use hype. "
    "Output STRICT JSON only."
)

_ASK = (
    "IDEA\nangle: {angle}\nhook: {hook}\nkey points: {points}\n\n"
    "BRAND POSITIONING (authoritative — voice, prohibitions, visual direction):\n{positioning}\n"
    "{firm_rules}\n"
    "The chosen asset kind is '{kind}', which renders as: {route_desc}\n\n"
    "Return JSON with exactly these keys:\n{schema}\n"
    "Every word must obey the positioning. Invent no numbers. JSON only."
)

_SCHEMAS: dict[str, str] = {
    "image": ('  "subject": one or two full sentences describing a CONCEPTUAL object or scene that '
              'embodies the idea physically. No people. No screens of text. Think of an object whose '
              'behaviour IS the mechanism being explained.\n'),
    "poster": ('  "subject": one or two sentences describing the conceptual object or scene.\n'
               '  "headline": the exact short line to set in the image (<=8 words).\n'),
    "video": ('  "subject": one or two sentences describing the conceptual object or scene in motion.\n'),
    "card": ('  "kicker": short ALL-CAPS content pillar (<=4 words),\n'
             '  "headline": the single punchy line (<=12 words),\n'
             '  "subhead": one clarifying sentence, or "",\n'
             '  "left_label","left_body","right_label","right_body": for a comparison, else "",\n'
             '  "term": the term being defined, else "",\n'
             '  "items": up to 3 short strings for a list, else [].\n'),
}

_ROUTE_DESC = {
    "image": "a text-free generated still; the copy lives in the caption",
    "poster": "a generated still where the model sets a short headline you supply",
    "video": "a short generated clip",
    "card": "a deterministically rendered typographic card with exact brand type",
}


async def plan_asset(idea: Any, *, asset_kind: str, platform: str, voice: BrandVoice,
                     positioning: str = "", firm_rules_block: str = "",
                     complete: Callable[..., Any] | None = None) -> AssetPlan:
    """Route the idea and author the refined brief the chosen renderer needs.

    Degrades rather than fails: if the authoring call is unavailable or returns junk, fall back to a
    deterministic brief built straight from the idea. A creative pipeline that hard-fails on an LLM
    blip is worse than one that occasionally ships a plainer post.
    """
    route = route_for(asset_kind)
    aspect = technique.aspect_for(platform)
    if route == "skip":
        return AssetPlan(route="skip", reason=f"no renderable route for asset_kind={asset_kind!r}")

    # Any firm threshold in the copy must come from the verified table, never from the model. Left
    # to itself it will invent a confident, plausible number about a THIRD PARTY's product — and the
    # conscience critic cannot catch that: its prohibitions cover our own invented figures, and a
    # competitor's rule reads to it as an ordinary fact.
    firm_rules = firm_rules_block or ""

    data: dict = {}
    if complete is not None:
        try:
            raw = await complete(
                _ASK.format(angle=idea.angle, hook=idea.hook,
                            points="; ".join(getattr(idea, "key_points", []) or []),
                            positioning=positioning[:6000], kind=asset_kind,
                            firm_rules=firm_rules, route_desc=_ROUTE_DESC[route],
                            schema=_SCHEMAS[route]),
                system=_SYSTEM, tier="complex", timeout_s=60)
            data = _strip_json(raw)
        except Exception as exc:  # noqa: BLE001 — authoring is a refinement, not a gate
            log.warning("social.plan_author_failed", route=route, error=str(exc)[:200])

    if route == "card":
        fields = {
            "kicker": str(data.get("kicker") or idea.angle.split(":")[0]),
            "headline": str(data.get("headline") or idea.hook or idea.angle),
            "subhead": str(data.get("subhead") or ""),
            "left_label": str(data.get("left_label") or ""), "left_body": str(data.get("left_body") or ""),
            "right_label": str(data.get("right_label") or ""), "right_body": str(data.get("right_body") or ""),
            "term": str(data.get("term") or ""),
            "items": [str(i) for i in (data.get("items") or [])][:3]
                     or [str(p) for p in (getattr(idea, "key_points", []) or [])][:3],
            "wordmark": voice.wordmark,
        }
        _guard(" ".join(str(v) for v in fields.values()), voice)
        return AssetPlan(route=route, layout=layout_for(asset_kind), fields=fields, aspect=aspect)

    subject = str(data.get("subject") or f"{idea.angle}. {idea.hook}")
    if route == "poster":
        headline = str(data.get("headline") or idea.hook or idea.angle)
        _guard(f"{subject} {headline}", voice)
        prompt = technique.poster_prompt(subject, headline, style=voice.style,
                                         palette=voice.palette, banned=voice.banned_imagery)
    elif route == "video":
        _guard(subject, voice)
        prompt = technique.video_prompt(subject, style=voice.style, palette=voice.palette,
                                        banned=voice.banned_imagery)
    else:
        _guard(subject, voice)
        prompt = technique.illustrative_prompt(subject, style=voice.style, palette=voice.palette,
                                               banned=voice.banned_imagery)
    return AssetPlan(route=route, prompt=prompt, aspect=aspect)


def _guard(blob: str, voice: BrandVoice) -> None:
    hits = find_prohibited(blob, voice.prohibited)
    if hits:
        raise ComplianceError(f"authored brief contains prohibited phrases: {hits}")
