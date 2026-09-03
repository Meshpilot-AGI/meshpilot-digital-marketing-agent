"""The scheduled SEO loop: pick a topic → author → publish → later, settle (SEO-4).

SEO-1..3 built the pieces; this is what runs them unattended. Two capabilities, deliberately
separate because they happen at different times and have different failure modes:

- **`seo_publish`** authors one post and opens (or, once earned, merges) its PR.
- **`seo_settle`** asks GitHub what happened to PRs opened earlier and records it. Without it
  `human_edits` stays NULL forever, the streak never advances, and the ladder in `track.py` is
  decorative.

**This capability refuses far more often than it runs, and that is the design.** Publishing is a
code change in someone else's repo: it needs a git checkout, the site's npm toolchain, and a `gh`
that can open a PR. ⚠️ **The API's own runtime (FastAPI Cloud) has none of those** — no checkout, no
npm, no `gh` credential — so scheduling `seo_publish` there will refuse with `no_repo` rather than
fail halfway through a git operation. It runs where a checkout exists. Every precondition is checked
and named before anything is written, so a refusal says which one was missing.

Nothing here is brand-specific. The repo path, blog file, sitemap and author come from the brand's
own `<PREFIX>_SEO_*` env, and the site's real URL vocabulary is read from its **committed sitemap**
rather than guessed — the first live generation invented `/tools/drawdown-calculator` when the real
page is `/tools/firm-drawdown-calculator`, and an invented link is the same class of error as an
invented figure.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# The site's own committed sitemap is the source of truth for what pages exist. Default is the
# conventional location; a brand whose site differs sets `<PREFIX>_SEO_SITEMAP`.
_DEFAULT_SITEMAP = "public/sitemap-en.xml"
_DEFAULT_BLOG_FILE = "src/data/blog.ts"

_LOC = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.I)
# Anchored on the SLUG, then the title that follows it. `title:` also appears on nested blocks and
# on the type declaration itself, so matching it alone picks up strings that are not post titles;
# and the file mixes hand-written single-quoted TS with our own JSON-shaped output, so indentation
# is not a reliable discriminator either. Pairing is.
_SLUG = re.compile(r"""["']?slug["']?\s*:\s*['"]([a-z0-9-]+)['"]""")
_TITLE_AFTER = re.compile(r"""["']?title["']?\s*:\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")""")


def _cfg(brand_id: str, name: str, default: str = "") -> str:
    from glitch_signal.config import brand_env

    return brand_env(f"SEO_{name}", brand_id, default) or default


def _csv(brand_id: str, name: str) -> list[str]:
    """A brand's declared list, e.g. the capabilities a post is allowed to claim.

    Empty means the product-claim check cannot run — stated here rather than hidden, because a brand
    that declares nothing gets no protection from the check that would have caught the weekend-cutoff
    claim.
    """
    return [x.strip() for x in _cfg(brand_id, name).split(",") if x.strip()]


def _enabled() -> bool:
    """Global kill-switch. Ships OFF — autonomous publishing is opt-in per deployment."""
    from glitch_signal.config import settings

    return bool(getattr(settings(), "agent_seo_enabled", False))


def site_links(repo: str, sitemap: str = _DEFAULT_SITEMAP) -> list[str]:
    """Site-relative paths the site actually serves, read from its committed sitemap.

    Returns `[]` when the sitemap is missing — and the caller REFUSES on that rather than authoring
    without it. Generating with no link vocabulary is exactly the condition that produced invented
    internal links the first time.
    """
    path = pathlib.Path(repo) / sitemap
    if not path.exists():
        return []
    out: list[str] = []
    for loc in _LOC.findall(path.read_text(errors="replace")):
        p = re.sub(r"^https?://[^/]+", "", loc.strip()) or "/"
        if p.startswith("/") and p not in out:
            out.append(p)
    return out


def existing_posts(repo: str, blog_file: str = _DEFAULT_BLOG_FILE) -> tuple[list[str], list[str]]:
    """`(slugs, titles)` already published, so a topic pick does not repeat one."""
    path = pathlib.Path(repo) / blog_file
    if not path.exists():
        return [], []
    src = path.read_text(errors="replace")
    slugs, titles = [], []
    for m in _SLUG.finditer(src):
        slugs.append(m.group(1))
        t = _TITLE_AFTER.search(src, m.end(), m.end() + 400)
        if t:
            titles.append((t.group(1) or t.group(2)).replace("\\'", "'"))
    return sorted(set(slugs)), titles[:60]


# The answer is one line, but the `moderate` tier's model is a REASONING model: it spends tokens
# thinking before it writes, and a budget sized for the answer is consumed entirely by the reasoning,
# returning `content: null` with `finish_reason: "length"`. Measured — at 50 tokens it returns
# nothing; at 400 it answers after 267 reasoning tokens. The budget has to cover the thinking, not
# just the output.
_TOPIC_MAX_TOKENS = 1200

_TOPIC_PROMPT = """You are choosing ONE topic for the next blog post on this site.

AUDIENCE: {audience}

{positioning}

ALREADY PUBLISHED (do not repeat, and do not write a near-duplicate):
{titles}

PAGES THIS SITE ALREADY HAS (a good topic deepens or connects these, it does not restate them):
{links}

Choose a topic this audience would actually search for and that this site can answer with
authority. Reply with ONE line: the topic as a specific question or noun phrase. No preamble.
"""


async def pick_topic(brand_id: str, *, audience: str, positioning: str, titles: list[str],
                     links: list[str], complete: Any = None) -> str:
    """One topic, chosen against what is already published rather than in a vacuum."""
    if complete is None:
        from glitch_signal.agent.loop import llm as agent_llm

        async def complete(prompt: str, *, tier: str = "moderate") -> str:
            return await agent_llm.complete_messages(
                [{"role": "user", "content": prompt}], tier=tier,
                max_tokens=_TOPIC_MAX_TOKENS, timeout_s=90)

    raw = await complete(_TOPIC_PROMPT.format(
        audience=audience or "the site's readers",
        positioning=positioning[:2000],
        titles="\n".join(f"- {t}" for t in titles[:40]) or "- (none yet)",
        links="\n".join(f"- {p}" for p in links[:60]) or "- (none)",
    ))
    return (raw or "").strip().splitlines()[0].strip().strip('"').strip() if raw else ""


async def run_publish(brand_id: str, args: dict | None = None) -> dict:
    """Author and publish one post. Refuses, with a named reason, unless every precondition holds."""
    from glitch_signal.agent import positioning as _positioning
    from glitch_signal.agent.seo import generate
    from glitch_signal.agent.seo import publish as _publish

    args = args or {}
    if not _enabled():
        return {"skipped": "seo_disabled"}

    repo = args.get("repo") or _cfg(brand_id, "REPO_PATH")
    if not repo or not pathlib.Path(repo, ".git").exists():
        # The expected outcome anywhere without a checkout — the API's own runtime included.
        log.info("seo.run_no_repo", brand_id=brand_id, repo=repo or "")
        return {"skipped": "no_repo", "detail": "no git checkout at the configured SEO_REPO_PATH"}

    blog_file = _cfg(brand_id, "BLOG_FILE", _DEFAULT_BLOG_FILE)
    links = site_links(repo, _cfg(brand_id, "SITEMAP", _DEFAULT_SITEMAP))
    if not links:
        # Refusing beats authoring blind: with no vocabulary the model invents plausible paths.
        return {"skipped": "no_sitemap",
                "detail": "cannot read the site's URL vocabulary — would invent internal links"}

    # ⚠️ ONE POST IN FLIGHT. Every post is inserted at the same anchor — the top of the array — so
    # two open PRs always conflict with each other: #558 and #559 both landed on it, and #559 could
    # not be rebased at all. Serialising removes the conflict class rather than teaching the
    # publisher to resolve it, and it costs nothing real: a post waiting on review is the normal
    # state at S0, and the cadence is one post a day against a review loop measured in days.
    from glitch_signal.agent.seo import track

    open_prs = await track.unsettled(brand_id) if brand_id else []
    if open_prs:
        return {"skipped": "post_in_flight",
                "detail": f"{len(open_prs)} post(s) awaiting review; a second insert at the same "
                          f"anchor would conflict",
                "waiting_on": [r.get("pr_url") or r.get("slug") for r in open_prs][:5]}

    slugs, titles = existing_posts(repo, blog_file)
    audience = _cfg(brand_id, "AUDIENCE") or args.get("audience", "")
    positioning = await _positioning.get(brand_id)

    topic = args.get("topic") or await pick_topic(
        brand_id, audience=audience, positioning=positioning, titles=titles, links=links)
    if not topic:
        return {"skipped": "no_topic", "detail": "topic selection returned nothing"}

    facts = await generate.facts_for(topic)
    post, problems = await generate.author(
        topic, audience=audience, author_slug=_cfg(brand_id, "AUTHOR", "ryan"),
        facts_block=facts, site_links=links, positioning=positioning,
        today=dt.date.today().isoformat(),
        brand_terms=_csv(brand_id, "BRAND_TERMS"),
        capabilities=_csv(brand_id, "CAPABILITIES"),
        check_sources=True)
    if post is None:
        log.warning("seo.run_author_failed", brand_id=brand_id, topic=topic[:80],
                    problems=problems[:4])
        return {"ran": "seo_publish", "topic": topic, "authored": False, "problems": problems[:6]}
    if post.slug in slugs:
        # `insert_post` would refuse anyway; saying so here names the real reason.
        return {"ran": "seo_publish", "topic": topic, "authored": True, "published": False,
                "reason": f"slug {post.slug!r} already published"}

    if args.get("dry_run"):
        return {"ran": "seo_publish", "topic": topic, "authored": True, "published": False,
                "reason": "dry_run", "slug": post.slug, "title": post.title}

    res = await _publish.publish(post, repo=repo, brand_id=brand_id, blog_file=blog_file)
    return {"ran": "seo_publish", "topic": topic, "authored": True, "published": res.ok,
            "slug": res.slug, "stage": res.stage, "pr_url": res.pr_url,
            "gates": res.gates, "reason": res.reason}


async def run_settle(brand_id: str, args: dict | None = None) -> dict:
    """Record what happened to previously opened PRs. This is what lets the stage ever move."""
    from glitch_signal.agent.seo import track

    args = args or {}
    repo = args.get("repo") or _cfg(brand_id, "REPO_PATH")
    if not repo or not pathlib.Path(repo, ".git").exists():
        return {"skipped": "no_repo"}
    logins = tuple(x for x in _cfg(brand_id, "AGENT_LOGINS").split(",") if x.strip())
    out = await track.settle_open(brand_id, repo=repo, agent_logins=logins)
    standing = await track.standing(brand_id)
    return {"ran": "seo_settle", **out,
            "stage": standing.stage, "clean_streak": standing.clean_streak,
            "reason": standing.reason}
