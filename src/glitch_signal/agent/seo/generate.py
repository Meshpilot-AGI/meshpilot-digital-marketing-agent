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

# A full structured post is several thousand tokens of JSON. `llm.complete()` hardcodes max_tokens to
# 2048, which truncates one mid-object and yields an unparseable response — so this path uses
# `complete_messages`, which exposes the limit. Found by running it for real: the unit tests used a
# fake accepting **kwargs, which cannot catch a signature or a budget mismatch.
_MAX_OUTPUT_TOKENS = 8000


async def _default_complete(prompt: str, *, tier: str = "complex") -> str:
    from glitch_signal.agent.loop import llm as agent_llm

    return await agent_llm.complete_messages(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
        tier=tier, max_tokens=_MAX_OUTPUT_TOKENS, timeout_s=180)

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

{links}

HARD RULES
- Every quantitative claim about a named firm MUST come from VERIFIED FACTS above, quoted exactly.
  If a figure you want is not there, write around it or omit the claim. Do NOT supply your own.
- Internal links MUST be chosen from SITE PAGES above, copied exactly. A path that looks plausible
  but does not exist is a broken link. Do NOT invent one.
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

# The repair prompt CARRIES THE FULL ORIGINAL BRIEF. An earlier version sent only the violations and
# the previous attempt, and the model repaired blind: told "add a stat callout", it rewrote wholesale,
# dropped the FAQ and internal links it had already got right, then invented block type names
# (`stat_callout`, `anti_pattern`) because the schema was no longer in front of it. Each repair made
# the post worse. Violations are a diff, not a specification — the spec has to stay on the table.
_REPAIR = """{original}

--- YOUR PREVIOUS ATTEMPT WAS REJECTED ---

The automated checks found these problems. Fix exactly these, keep everything else that already
satisfies the brief above, and return the COMPLETE corrected JSON object:

{violations}

Your previous attempt:
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


def unsupported_links(post: Post, site_links: list[str]) -> list[str]:
    """Internal links the site does not have.

    The first generated post cited `/tools/drawdown-calculator`, `/prop-firms/apex-trader-funding`
    and `/brokers/execution-comparison`; only one of its four internal links resolved. The real page
    is `/tools/firm-drawdown-calculator` — plausible-but-wrong, which is worse than obviously wrong,
    because it reads as correct.

    The contract already required internal links to be present and spread across clusters; it never
    required them to EXIST. An invented link is the same class of error as an invented figure, and it
    gets the same treatment: the model is given the real vocabulary and checked against it. The
    site's own `links:audit` gate would eventually catch these, but only after a PR is opened —
    catching them here means the post is fixed by the repair loop instead.
    """
    if not site_links:
        return []
    allowed = {link.rstrip("/") for link in site_links}
    return sorted({u for u in post.internal_links()
                   if u.rstrip("/") not in allowed
                   # A detail page under a real section is legitimate (/prop-firms/<firm>); an
                   # invented SECTION is not.
                   and not any(u.rstrip("/").startswith(a + "/") for a in allowed if a.count("/") == 1)})


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


# Sweeping claims about how the market behaves. Each of these asserts a distribution, and a
# distribution is checkable — we hold one. The post that prompted this wrote "almost every challenge
# structure pairs a profit target with a minimum number of trading days"; the count is 2 of 6.
_GENERALISATIONS = re.compile(
    r"\b(most (?:firms|challenges|prop firms|providers)|almost every|nearly all|virtually all|"
    r"the (?:vast )?majority of (?:firms|challenges)|every (?:firm|challenge)|all (?:firms|challenges)|"
    r"industry[- ]standard|the industry standard|standard across the industry)\b", re.I)

# Negations immediately before a generalisation invert it. Deliberately a short window and a small
# list: this is a heuristic, and a wide one would start swallowing the claims it exists to catch.
_NEGATED = re.compile(r"\b(not|isn'?t|aren'?t|never|rather than|no)\s+(an?\s+|the\s+)?$", re.I)


def unsupported_generalisations(post: Post, facts_block: str) -> list[str]:
    """Claims about how common something is, in a post that was given no distribution to back them.

    Only fires when the facts block carries NO counts — with a distribution in hand the model has
    what it needs, and the counts are stated there for it to quote. This is the qualitative sibling
    of `unsupported_figures`: that one catches an invented number, this catches an invented
    consensus, and until now nothing caught the second.
    """
    if "firms have one." in facts_block or "of the firms" in facts_block:
        return []
    prose = " ".join(str(b.get("text") or "") for b in post.blocks)
    prose += " " + post.lede + " " + post.tldr
    prose += " " + " ".join(str(q.get("a", "")) for q in post.faq)
    found = set()
    for m in _GENERALISATIONS.finditer(prose):
        # A NEGATED generalisation is the claim we want. "It's a firm-by-firm decision, not an
        # industry standard" is the post getting this right, and flagging it would spend a repair
        # round making a correct sentence worse — a check that cries wolf gets ignored.
        if _NEGATED.search(prose[max(0, m.start() - 40):m.start()]):
            continue
        found.add(m.group(0).lower())
    return sorted(found)


def unverified_product_claims(post: Post, *, brand_terms: list[str],
                              capabilities: list[str]) -> list[str]:
    """Sentences claiming OUR product does something, where the capability is not on the allowlist.

    ⚠️ The most dangerous claim in a brand's own post is the one about the brand. A shipped post said
    our engine "treats a weekend cutoff as a pre-trade and pre-close condition" and "can block a new
    order" on that basis. It does not: the pre-trade gate emits six rules and none is time-of-week.
    It was plausible precisely because the parts were real — a per-firm weekend field exists, the
    gate really does block orders pre-broker — and the model invented the connection between them.

    Nothing else can catch this. Figure-grounding checks numbers, the contract checks structure, and
    an external source cannot confirm what our own code does. So capabilities are declared, and a
    verb applied to us that is not declared is flagged for a human rather than published.
    """
    if not brand_terms:
        return []
    prose = " ".join(str(b.get("text") or "") for b in post.blocks)
    prose += " " + " ".join(str(q.get("a", "")) for q in post.faq)
    flagged: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", prose):
        low = sentence.lower()
        if not any(_mentions(t, low) for t in brand_terms):
            continue
        if any(_capability_matches(c, low) for c in capabilities):
            continue
        flagged.append(sentence.strip()[:220])
    return flagged


def _mentions(term: str, sentence: str) -> bool:
    """Does this sentence name the brand?

    ⚠️ Word boundaries, not a substring test. The declared term "our platform" matched inside
    "y-our platform", so a sentence about the READER's trading platform was read as a claim about
    ours and flagged. A check that fires on sentences it has no business reading gets switched off.
    """
    return re.search(rf"(?<![\w-]){re.escape(term.lower())}(?![\w-])", sentence) is not None


# Words that carry no meaning for matching a capability to a sentence.
_FILLER = {"a", "an", "the", "to", "of", "on", "for", "your", "you", "it", "and", "or", "in",
           "with", "each", "every", "before", "after", "when", "that", "this", "is", "are"}


def _capability_matches(capability: str, sentence: str) -> bool:
    """Does this sentence describe the declared capability?

    ⚠️ Substring matching was the first attempt and it was too brittle to be useful: the declared
    "routes orders to your broker" did not match "routes your orders straight through to your
    broker", so a TRUE claim was flagged. Padding the list with phrasings would have hidden the
    defect and grown a list nobody could maintain.

    Content-word overlap instead — every meaningful word of the capability must appear. Deliberately
    ALL of them, not a fraction: this check exists to reject claims, and a partial match is how
    "enforces a weekend cutoff tied to the firm rule" would slip past "records each firm's published
    rules" on the strength of sharing "firm".
    """
    bases = [_base(w) for w in re.findall(r"[a-z]+", capability.lower())
             if w not in _FILLER and len(w) > 2]
    if not bases:
        return False
    tokens = re.findall(r"[a-z]+", sentence)
    return all(any(t.startswith(b) for t in tokens) for b in bases)


def _base(word: str) -> str:
    """The capability word reduced to a prefix its inflections all share.

    ⚠️ Two attempts got this wrong before this one, both by rejecting TRUE claims. Exact matching
    failed on inflection — "places orders" did not match "can place orders". Then symmetric stemming
    failed on its own inconsistency: "places" trimmed to "plac" while "place" stayed "place", so the
    two still did not meet. Reducing only the DECLARED word and prefix-matching the sentence sidesteps
    both, because "place" is a prefix of "place", "places" and "placed" alike.

    Declaring every inflection would have worked too, and would have grown a list nobody could
    maintain — the same trap as declaring every phrasing.
    """
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) - len(suffix) >= 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


async def dead_sources(post: Post, fetch: Any = None) -> list[str]:
    """StatCallout source URLs that do not resolve.

    The contract already requires an external primary source and rejects a bare domain — it never
    checked that the page EXISTS. A shipped post cited a CFTC page that 404s, which is a citation a
    reader cannot follow and an AI search engine cannot verify: worse than no citation, because it
    looks like one.
    """
    urls = [u for u in post.stat_sources() if u.startswith("http")]
    if not urls:
        return []
    if fetch is None:
        import httpx

        async def fetch(url: str) -> int:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                return (await client.get(url)).status_code

    dead = []
    for url in urls:
        try:
            code = await fetch(url)
        except Exception:  # noqa: BLE001 — a network blip is not evidence the page is gone
            continue
        if code >= 400:
            dead.append(f"{url} -> HTTP {code}")
    return dead


async def author(
    topic: str,
    *,
    audience: str,
    author_slug: str = "ryan",
    facts_block: str = "",
    site_links: list[str] | None = None,
    positioning: str = "",
    today: str = "",
    complete: Any = None,
    tier: str = "complex",
    max_repairs: int = MAX_REPAIRS,
    brand_terms: list[str] | None = None,
    capabilities: list[str] | None = None,
    # Off by default: `author()` is a pure-ish function everywhere else, and a default that silently
    # makes network calls turns every unit test into an integration test. `run.py` — the production
    # caller — turns it on.
    check_sources: bool = False,
    fetch: Any = None,
) -> tuple[Post | None, list[str]]:
    """Author a post, repairing against the contract. Returns `(post_or_None, problems)`.

    Never returns a post that fails the contract — a caller receiving a `Post` can rely on it being
    structurally publishable, which is what lets `publish.py` treat its own contract check as a
    belt-and-braces assertion rather than a filter.
    """
    complete = complete or _default_complete
    site_links = site_links or []
    links_block = ("SITE PAGES (the only internal links you may use, copied exactly):\n"
                   + "\n".join(f"- {p}" for p in site_links)) if site_links else \
                  "SITE PAGES: none supplied — use only internal links you are certain exist."
    prompt = _PROMPT.format(topic=topic, audience=audience, author=author_slug, today=today,
                            links=links_block,
                            facts=f"VERIFIED FACTS (the only figures you may cite):\n{facts_block}"
                                  if facts_block.strip() else
                                  "VERIFIED FACTS: none supplied — do not cite firm-specific figures.",
                            positioning=positioning)
    previous = ""
    problems: list[str] = []

    for attempt in range(max_repairs + 1):
        raw = await complete(prompt if attempt == 0 else
                             _REPAIR.format(original=prompt,
                                            violations="\n".join(f"- {p}" for p in problems),
                                            previous=previous),
                             tier=tier)
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
        bad_links = unsupported_links(post, site_links)
        if bad_links:
            problems.append(
                f"these internal links do not exist on the site and must be replaced with ones "
                f"from SITE PAGES: {', '.join(bad_links)}")

        sweeping = unsupported_generalisations(post, facts_block)
        if sweeping:
            problems.append(
                f"these claim how common something is, and nothing in the brief supports a claim "
                f"about the whole market — remove them or narrow them to what you were given: "
                f"{', '.join(sweeping)}")

        claims = unverified_product_claims(post, brand_terms=brand_terms or [],
                                           capabilities=capabilities or [])
        if claims:
            problems.append(
                f"these describe what the product does, and only the declared capabilities may be "
                f"stated. Remove the claim or write only what is on the list. Sentences: "
                f"{' | '.join(claims[:3])}")

        dead = await dead_sources(post, fetch) if check_sources else []
        if dead:
            problems.append(
                f"these cited sources do not resolve — cite a page that exists, or drop the claim: "
                f"{', '.join(dead)}")

        if ok and not invented and not bad_links and not sweeping and not claims and not dead:
            log.info("seo.authored", slug=post.slug, attempt=attempt + 1,
                     blocks=len(post.blocks), faq=len(post.faq))
            return post, []

        previous = json.dumps(data)[:6000]
        log.info("seo.author_repair", attempt=attempt + 1, problems=problems[:5])

    log.warning("seo.author_failed", topic=topic[:80], problems=problems[:6])
    return None, problems


async def facts_for(topic: str, *, engine: Any = None) -> str:
    """Grounded facts for a topic — firm thresholds when it names firms, the DISTRIBUTION when it
    names a rule.

    Reuses the same `firm_rule` grounding the social copy uses, so a figure cannot be right in one
    channel and invented in another.

    ⚠️ This used to return `""` for any topic that named no firm, which is most rule-explainer
    topics — exactly the posts most prone to sweeping claims. One shipped saying *"most challenges
    require a minimum number of trading days"* when our own data says 2 of 6 live firms do. No
    percentage appeared in the sentence, so the figure check never looked at it; no firm was named,
    so no facts were supplied at all. A post about a rule needs the spread, not a threshold.
    """
    from glitch_signal.agent import firms

    named = firms.mentioned(topic)
    if named:
        return firms.rules_block(await firms.rules_for_names(named, engine=engine))
    keys = firms.rule_keys_for_topic(topic)
    if not keys:
        return ""
    return firms.distribution_block(await firms.rules_for_distribution(keys, engine=engine), keys)


def check_only(post: Post) -> list[str]:
    """Contract violations as strings, for callers that already have a post."""
    return [str(v) for v in check(post)]
