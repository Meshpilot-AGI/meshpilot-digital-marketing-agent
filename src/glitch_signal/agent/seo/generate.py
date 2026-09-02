"""Authoring a post that satisfies the contract (SEO-2b).

The model writes; `contract.py` decides whether what it wrote is publishable. When it isn't, the
violations go back to the model as **specific, addressable instructions** — "3 H2 sections, need 4"
is a far better repair signal than "try again", and it is available for free because the contract is
structural rather than a matter of taste.

**Grounding is not negotiable.** Every firm-rule figure comes from the `firm_rule` table and is
handed to the model as fact; the model is told, explicitly, that it may not supply figures of its
own. The vertical is YMYL-adjacent and the program forbids "guaranteed pass" claims — a hallucinated
drawdown percentage published under the brand's name is the failure mode that matters most here, and
the same guard already protects the social copy.

Nothing in this module names a brand or an industry: topic, audience and grounded facts are all
passed in.
"""
from __future__ import annotations

import json
import re
from typing import Any

import structlog

from glitch_signal.agent.seo.contract import check, is_publishable
from glitch_signal.agent.seo.post import Post

log = structlog.get_logger(__name__)

# Two repairs. If precise structural feedback has not produced a valid post by the third attempt, the
# problem is the brief or the model, and more attempts just spend tokens making the same mistake.
MAX_REPAIRS = 2

_SYSTEM = (
    "You write technical explainers for a specialist audience. You write like a practitioner "
    "explaining something to a peer: specific, concrete, and willing to say what a thing does NOT "
    "do. You never pad, never write a summary paragraph that repeats what was already said, and "
    "never use marketing register."
)

_PROMPT = """Write one blog post as JSON. Return ONLY the JSON object, no prose around it.

TOPIC: {topic}
AUDIENCE: {audience}
AUTHOR: {author}

{facts}

{positioning}

HARD RULES
- Every quantitative claim about a named firm MUST come from VERIFIED FACTS above, quoted exactly.
  If a figure you want is not there, write around it or omit the claim. Do NOT supply your own.
- No "guaranteed pass", no promised outcomes, no invented testimonials or funded numbers.
- The lede is at most 60 words and contains the direct answer. It is also the meta description.
- `tldr` is the direct answer in 2-3 sentences — the passage an AI search engine will quote.

REQUIRED STRUCTURE (all of it, or the post is rejected automatically)
- at least 4 blocks of type "h2"
- exactly one block of type "stat", whose sourceUrl is an EXTERNAL primary source (https://…)
- at least one "table" block, or a "list" block with ordered=true
- exactly one "antiPattern" block — what this post does NOT solve
- one "cite" block whose sources include at least 3 INTERNAL links (paths starting with "/"),
  spanning at least two different sections, e.g. /tools/… and /prop-firms/… and /brokers/…
- at least 5 FAQ pairs

JSON SHAPE
{{
  "slug": "lowercase-hyphenated",
  "title": "...",
  "lede": "...",
  "tldr": "...",
  "publishedAt": "{today}",
  "readingMinutes": 8,
  "tags": ["..."],
  "blocks": [
    {{"type": "p", "text": "..."}},
    {{"type": "h2", "text": "...", "id": "kebab-id"}},
    {{"type": "stat", "stat": "...", "context": "...", "sourceUrl": "https://...",
      "sourceLabel": "..."}},
    {{"type": "table", "headers": ["..."], "rows": [["..."]]}},
    {{"type": "list", "ordered": true, "items": ["..."]}},
    {{"type": "antiPattern", "title": "...", "text": "..."}},
    {{"type": "cite", "sources": [{{"label": "...", "url": "/tools/..."}}]}}
  ],
  "faq": [{{"q": "...", "a": "..."}}]
}}
"""

_REPAIR = """Your previous post was rejected by the automated editorial checks.

Fix EXACTLY these problems and return the complete corrected JSON object. Change nothing else:

{violations}

Previous attempt:
{previous}
"""


def _parse(raw: str) -> dict:
    """Extract the JSON object from a model response. Same tolerance as the rest of the codebase."""
    m = re.search(r"\{.*\}", raw or "", re.DOTALL)
    for cand in ([m.group(0)] if m else []) + [raw or ""]:
        try:
            v = json.loads(cand)
            if isinstance(v, dict):
                return v
        except Exception:  # noqa: BLE001
            continue
    return {}


def to_post(data: dict, *, author_slug: str) -> Post | None:
    """Map the model's JSON onto `Post`. Returns None if the object is unusable."""
    if not data.get("slug") or not data.get("title"):
        return None
    try:
        return Post(
            slug=str(data["slug"]).strip().lower(),
            title=str(data["title"]),
            lede=str(data.get("lede") or ""),
            tldr=str(data.get("tldr") or ""),
            author_slug=author_slug,
            published_at=str(data.get("publishedAt") or ""),
            reading_minutes=int(data.get("readingMinutes") or 8),
            tags=[str(t) for t in (data.get("tags") or [])],
            blocks=[b for b in (data.get("blocks") or []) if isinstance(b, dict)],
            faq=[{"q": str(f.get("q", "")), "a": str(f.get("a", ""))}
                 for f in (data.get("faq") or []) if isinstance(f, dict)],
        )
    except (TypeError, ValueError):
        return None


def unsupported_figures(post: Post, facts_block: str) -> list[str]:
    """Figures in the post that do not appear in the grounded facts.

    The contract checks that claims are *sourced*; this checks they are *ours to make*. A model that
    invents "8% trailing" for a real firm produces a post that looks perfectly cited and is false —
    the exact failure the `firm_rule` table exists to prevent.

    Only checked when facts were supplied: with no grounded facts there is nothing to contradict, and
    flagging every number would make the check meaningless.
    """
    if not facts_block.strip():
        return []
    prose = " ".join(str(b.get("text") or b.get("stat") or "") for b in post.blocks)
    prose += " " + " ".join(f"{q.get('a', '')}" for q in post.faq)
    found = set(re.findall(r"\d+(?:\.\d+)?\s?%", prose))
    allowed = set(re.findall(r"\d+(?:\.\d+)?\s?%", facts_block))
    norm = {f.replace(" ", "") for f in allowed}
    return sorted(f for f in found if f.replace(" ", "") not in norm)


async def author(
    topic: str,
    *,
    audience: str,
    author_slug: str = "ryan",
    facts_block: str = "",
    positioning: str = "",
    today: str = "",
    complete: Any = None,
    tier: str = "complex",
    max_repairs: int = MAX_REPAIRS,
) -> tuple[Post | None, list[str]]:
    """Author a post, repairing against the contract. Returns `(post_or_None, problems)`.

    Never returns a post that fails the contract — a caller receiving a `Post` can rely on it being
    structurally publishable, which is what lets `publish.py` treat its own contract check as a
    belt-and-braces assertion rather than a filter.
    """
    from glitch_signal.agent.loop import llm as agent_llm

    complete = complete or agent_llm.complete
    prompt = _PROMPT.format(topic=topic, audience=audience, author=author_slug, today=today,
                            facts=f"VERIFIED FACTS (the only figures you may cite):\n{facts_block}"
                                  if facts_block.strip() else
                                  "VERIFIED FACTS: none supplied — do not cite firm-specific figures.",
                            positioning=positioning)
    previous = ""
    problems: list[str] = []

    for attempt in range(max_repairs + 1):
        raw = await complete(prompt if attempt == 0 else
                             _REPAIR.format(violations="\n".join(f"- {p}" for p in problems),
                                            previous=previous),
                             tier=tier, system=_SYSTEM, max_tokens=4000, timeout_s=120)
        data = _parse(raw)
        post = to_post(data, author_slug=author_slug)
        if post is None:
            problems = ["response was not a usable JSON post object"]
            previous = (raw or "")[:2000]
            continue

        ok, violations = is_publishable(post)
        problems = [str(v) for v in violations]
        invented = unsupported_figures(post, facts_block)
        if invented:
            problems.append(
                f"these figures appear nowhere in the verified facts and must be removed or "
                f"replaced with a verified one: {', '.join(invented)}")

        if ok and not invented:
            log.info("seo.authored", slug=post.slug, attempt=attempt + 1,
                     blocks=len(post.blocks), faq=len(post.faq))
            return post, []

        previous = json.dumps(data)[:6000]
        log.info("seo.author_repair", attempt=attempt + 1, problems=problems[:5])

    log.warning("seo.author_failed", topic=topic[:80], problems=problems[:6])
    return None, problems


async def facts_for(topic: str, *, engine: Any = None) -> str:
    """Verified firm figures for whichever firms the topic names. Empty when none are named.

    Reuses the same `firm_rule` grounding the social copy uses, so a figure cannot be right in one
    channel and invented in another.
    """
    from glitch_signal.agent import firms

    named = firms.mentioned(topic)
    if not named:
        return ""
    return firms.rules_block(await firms.rules_for_names(named, engine=engine))


def check_only(post: Post) -> list[str]:
    """Contract violations as strings, for callers that already have a post."""
    return [str(v) for v in check(post)]
