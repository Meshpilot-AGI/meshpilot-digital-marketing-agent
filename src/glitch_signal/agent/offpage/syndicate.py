"""OFFPAGE-1 SYNDICATE — every merged blog post earns its two days on the brand's own feeds.

The blog ladder produces a post; nothing told anyone. This lever takes each merged
`seo_publication` and writes one short post per platform, from the live page itself, then hands it
to the Buffer publisher: X on day 0, LinkedIn the next day. One syndication per post per platform,
ever — the unique index on `offpage_candidate` is the promise, not the code.

What makes this safe to run unattended:
- The **page is the fact source.** Every figure in the draft must appear on the page it links to;
  the page already passed the blog's own gates, so nothing new can be invented here.
- The brand's hard-stop phrases refuse the draft (not scrub it — a 240-char post with a sentence
  cut out is not a post).
- One action per platform per run, so the backfill of already-merged posts trickles out at the
  daily cadence instead of dumping seven tweets in a minute.
- A draft that fails its checks leaves **no row** — nothing external happened, so tomorrow retries.
  A publish that fails leaves a `skipped` row with the error, because the external side effect is
  unknown and a human must look before it is tried again.

Design: docs/plans/2026-09-12-offpage-seo.md § 4 S1. Nothing here names a brand or a site.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import text

from glitch_signal.agent.offpage import store

log = structlog.get_logger()

LEVER = "syndicate"
PLATFORMS = ("x", "linkedin")
LIMITS = {"x": 240, "linkedin": 700}          # body only; the link is appended outside the limit
_LINKEDIN_AFTER_X_HOURS = 20                  # "the next day" without depending on run time
_PAGE_TEXT_MAX = 12_000                       # the whole article, not the tool-context 4k default

_MERGED = text(
    "SELECT slug, title, merged_at FROM seo_publication "
    "WHERE brand_id = :b AND merged_at IS NOT NULL ORDER BY merged_at, slug"
)


# --------------------------------------------------------------------------- planning

def plan(posts: list[dict], candidates: list[dict], now: datetime) -> list[tuple[str, dict]]:
    """Which (platform, post) to act on this run — at most one per platform.

    `posts` are merged blog posts oldest first; `candidates` are this lever's existing rows.
    X: the oldest post with no X row. LinkedIn: the oldest post whose X row is old enough and that
    has no LinkedIn row. Any row counts — including `skipped` — so a failed publish blocks until a
    human clears it, and a posted one never repeats.
    """
    by_post: dict[str, dict[str, dict]] = {}
    for c in candidates:
        by_post.setdefault(c["source_ref"], {})[c["surface_kind"]] = c
    actions: list[tuple[str, dict]] = []
    for p in posts:
        if "x" not in by_post.get(p["slug"], {}):
            actions.append(("x", p))
            break
    for p in posts:
        rows = by_post.get(p["slug"], {})
        x = rows.get("x")
        if x is None or "linkedin" in rows or x.get("status") == "skipped":
            continue
        created = x["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if now - created >= timedelta(hours=_LINKEDIN_AFTER_X_HOURS):
            actions.append(("linkedin", p))
            break
    return actions


# --------------------------------------------------------------------------- drafting

_PROMPT = """Write ONE social post for {platform} announcing a blog post. Max {limit} characters.
Do NOT include the URL — it is appended after you. No hashtags. No emoji walls (one is fine).

BLOG TITLE: {title}
BLOG TEXT (the only facts you may use — quote a figure only if it appears verbatim here):
---
{page}
---

Rules: lead with the one concrete fact from the text a trader would stop scrolling for, then say
what the post explains. No outcome promises, no superlatives, no "link in bio", no questions to the
audience. Sound like the person who wrote the post, not a marketer. Reply with the post only."""

_FIGURE = re.compile(r"(?<![\w/.])\d[\d,]*(?:\.\d+)?%?")
_WORDS = {str(i): w for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}
_WORDS.update({"30": "thirty", "40": "forty", "50": "fifty", "60": "sixty", "90": "ninety", "100": "hundred"})


def figures(text_: str) -> set[str]:
    """Numbers as written, so `2%` and `5,000` compare exactly; years are figures too."""
    return {m.group(0).rstrip(",.") for m in _FIGURE.finditer(text_)}


def supported(fig: str, known: set[str]) -> bool:
    """`47.7%` is backed by a page that says `47.7 %` or `47.7 percent`; the unit is not the fact."""
    bare = fig.rstrip("%")
    return fig in known or bare in known or any(k.rstrip("%") == bare for k in known)


def _spelled(fig: str, page_low: str) -> bool:
    """`7` is supported by a page that says "seven" — editors spell small counts out."""
    word = _WORDS.get(fig)
    return bool(word) and re.search(rf"\b{word}\b", page_low) is not None


def check(draft: str, *, platform: str, page_text: str, hard_stops: list[str]) -> list[str]:
    """Why this draft must not go out. Empty means it may."""
    problems: list[str] = []
    body = draft.strip()
    if not body:
        problems.append("empty")
        return problems
    if len(body) > LIMITS[platform]:
        problems.append(f"too_long:{len(body)}>{LIMITS[platform]}")
    if "http://" in body or "https://" in body:
        problems.append("contains_url")           # the link is ours to append, once
    if "#" in body:
        problems.append("hashtag")
    page_figs = figures(page_text)
    page_low = page_text.lower()
    invented = sorted(f for f in figures(body) if not supported(f, page_figs) and not _spelled(f, page_low))
    if invented:
        problems.append("unsupported_figures:" + ",".join(invented))
    low = body.lower()
    hit = [p for p in hard_stops if p and p in low]
    if hit:
        problems.append("hard_stop:" + ",".join(hit))
    return problems


_SHORTEN = """Shorten this social post to at most {limit} characters. Keep every figure and firm name
exactly as written, drop the least important sentence first, no new facts, no hashtags, no URL.
Reply with the shortened post only.

{body}"""


async def draft(platform: str, *, title: str, page_text: str, complete: Any) -> str:
    raw = await complete(_PROMPT.format(platform=platform, limit=LIMITS[platform], title=title,
                                        page=page_text[:_PAGE_TEXT_MAX]))
    body = (raw or "").strip().strip('"')
    # Small models write well and count badly: one compression pass before the checks refuse it.
    if len(body) > LIMITS[platform]:
        shorter = await complete(_SHORTEN.format(limit=LIMITS[platform], body=body))
        body = (shorter or "").strip().strip('"') or body
    return body


def with_link(body: str, url: str) -> str:
    return f"{body.rstrip()}\n\n{url}"


# --------------------------------------------------------------------------- running

def _on() -> bool:
    from glitch_signal.config import settings

    s = settings()
    return bool(getattr(s, "agent_social_enabled", False) and getattr(s, "agent_publish_enabled", False))


def _hard_stops(brand_id: str) -> list[str]:
    """Phrases a syndication post may never carry: promises. NOT the ORM hard stops — GE's ORM list
    contains "loss", which a post about daily-loss resets must say; using it here would refuse that
    post forever, silently, one retry a day."""
    from glitch_signal.config import brand_config

    op = brand_config(brand_id).get("offpage") or {}
    base = ["guaranteed", "guarantee", "risk-free", "risk free", "cannot lose", "can't lose", "100% pass"]
    return [p.lower() for p in base + list(op.get("forbidden_phrases") or [])]


def post_url(brand_id: str, slug: str) -> str | None:
    from glitch_signal.config import brand_config

    cfg = brand_config(brand_id)
    site = (cfg.get("site_url") or "").rstrip("/")
    if not site:
        return None
    path = ((cfg.get("seo") or {}).get("blog_path") or "/blog/").strip("/")
    return f"{site}/{path}/{slug}/"


async def merged_posts(brand_id: str, *, engine: Any = None) -> list[dict]:
    async with store._engine_or(engine).connect() as conn:
        rows = (await conn.execute(_MERGED, {"b": brand_id})).mappings().all()
    return [dict(r) for r in rows]


async def _default_fetch(url: str, brand_id: str) -> str:
    """The hardened web fetch the agent's tools use — same egress checks, same size caps."""
    from glitch_signal.agent.loop.tools import _t_web_fetch

    out = await _t_web_fetch({"url": url, "max_chars": _PAGE_TEXT_MAX}, brand_id)
    if out.startswith("ERROR:"):
        raise RuntimeError(out)
    return out


async def _default_complete(prompt: str) -> str:
    """A 240-char post is `simple`-tier work; the `moderate` roster's lead model spent its whole
    budget reasoning and returned nothing on four of five cloud dry runs. Try the simple tier, then
    the complex one, and let the caller's "no row → retry tomorrow" path handle both failing."""
    from glitch_signal.agent.loop import llm as agent_llm

    last: Exception | None = None
    for tier in ("simple", "complex"):
        try:
            out = await agent_llm.complete_messages([{"role": "user", "content": prompt}],
                                                    tier=tier, max_tokens=1200, timeout_s=90)
            if out and out.strip():
                return out
        except Exception as exc:  # noqa: BLE001 — try the next tier
            last = exc
            log.warning("offpage.syndicate.tier_failed", tier=tier, error=str(exc)[:160])
    raise RuntimeError(f"no tier produced a draft: {str(last)[:160] if last else 'empty'}")


async def _default_create_post(brand_id: str, platform: str, **kw: Any):
    from glitch_signal.platforms.buffer import create_post

    return await create_post(brand_id, platform, **kw)


async def run(brand_id: str, args: dict | None = None, *, engine: Any = None,
              deps: dict | None = None) -> dict:
    """One run: at most one X post and one LinkedIn post, each for the oldest post that needs it."""
    args = args or {}
    d = deps or {}
    dry = bool(args.get("dry_run"))
    if not dry and not _on():
        return {"skipped": "social_or_publish_disabled"}
    if post_url(brand_id, "x") is None:
        return {"skipped": "no_site_url", "detail": "brand config needs site_url"}

    posts = await (d.get("merged_posts") or merged_posts)(brand_id, engine=engine)
    if not posts:
        return {"skipped": "nothing_merged"}
    cands = await (d.get("candidates") or store.candidates_by_source)(brand_id, LEVER, engine=engine)
    now = d.get("now") or datetime.now(UTC)
    actions = plan(posts, cands, now)
    if not actions:
        return {"skipped": "all_syndicated", "posts": len(posts)}

    fetch = d.get("fetch") or _default_fetch
    complete = d.get("complete") or _default_complete
    create_post = d.get("create_post") or _default_create_post
    stops = _hard_stops(brand_id)
    out: dict[str, Any] = {"ran": "offpage_syndicate", "dry_run": dry, "actions": []}

    for platform, p in actions:
        url = post_url(brand_id, p["slug"])
        item: dict[str, Any] = {"platform": platform, "slug": p["slug"], "url": url}
        out["actions"].append(item)
        try:
            page = await fetch(url, brand_id)
            body = await draft(platform, title=p["title"], page_text=page, complete=complete)
        except Exception as exc:  # noqa: BLE001 — nothing external happened; tomorrow retries
            item["error"] = f"draft_failed: {str(exc)[:200]}"
            log.warning("offpage.syndicate.draft_failed", platform=platform, slug=p["slug"],
                        error=item["error"])
            continue
        problems = check(body, platform=platform, page_text=page, hard_stops=stops)
        item["draft"] = body
        if problems:
            item["refused"] = problems
            log.warning("offpage.syndicate.refused", platform=platform, slug=p["slug"],
                        problems=problems)
            continue
        if dry:
            continue
        full = with_link(body, url)
        try:
            pid, status = await create_post(brand_id, platform, text=full,
                                            idem_key=f"offpage:{LEVER}:{brand_id}:{p['slug']}:{platform}")
        except Exception as exc:  # noqa: BLE001 — side effect unknown: block this pair for a human
            err = str(exc)[:300]
            cid = await store.add_candidate(brand_id, lever=LEVER, surface_kind=platform,
                                            surface="buffer", draft=full, source_ref=p["slug"],
                                            meta={"error": err}, status="skipped", engine=engine)
            await store.record_outcome(cid, brand_id, LEVER, posted_url=None, error=err, engine=engine)
            item["error"] = f"publish_failed: {err}"
            log.warning("offpage.syndicate.publish_failed", platform=platform, slug=p["slug"], error=err)
            continue
        cid = await store.add_candidate(brand_id, lever=LEVER, surface_kind=platform, surface="buffer",
                                        draft=full, source_ref=p["slug"],
                                        meta={"buffer_id": pid, "buffer_status": status},
                                        status="posted_by_agent", engine=engine)
        await store.record_outcome(cid, brand_id, LEVER, posted_url=None,
                                   metrics={"buffer_id": pid, "buffer_status": status}, engine=engine)
        item["posted"] = f"{pid} ({status})"
        log.info("offpage.syndicate.posted", platform=platform, slug=p["slug"], buffer_id=pid)
    return out
