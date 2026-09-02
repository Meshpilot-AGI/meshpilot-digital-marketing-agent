"""The blog post as data, and as TypeScript (SEO-1).

The publishing target is not markdown. `glitch-trade-app/src/data/blog.ts` holds posts as **typed
structured blocks** — a `BlogBlock` union rendered by `BlogPost.tsx`, which emits FAQPage and
Quotation JSON-LD from the structure rather than parsing prose at render time. That is unusually
good news for an autonomous writer: the shape is machine-checkable, so "is this publishable" stops
being a matter of taste (see `contract.py`).

This module mirrors that TypeScript union in Python and emits it back out. Nothing here is
brand-specific — the target file path, author ids and cluster prefixes are configuration.

Mirrors, verbatim, the union in `src/data/blog.ts`:

    { type: 'p'; text }
    { type: 'h2'|'h3'; text; id? }
    { type: 'stat'; stat; context; sourceUrl; sourceLabel }
    { type: 'list'; ordered; items }
    { type: 'table'; headers; rows }
    { type: 'antiPattern'; title; text }
    { type: 'cite'; sources: { label; url }[] }
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# The block `type` values the renderer knows. Anything else fails typecheck in the target repo, so
# it is rejected here rather than at the far end of a PR.
BLOCK_TYPES = ("p", "h2", "h3", "stat", "list", "table", "antiPattern", "cite")


@dataclass
class Post:
    """One blog post, in the exact shape `blog.ts` expects."""

    slug: str
    title: str
    lede: str                       # ≤60 words, shown under the H1 and used as <meta description>
    tldr: str                       # the direct answer — the LLM/AI-search extraction zone
    author_slug: str
    published_at: str               # YYYY-MM-DD
    reading_minutes: int
    tags: list[str] = field(default_factory=list)
    blocks: list[dict[str, Any]] = field(default_factory=list)
    faq: list[dict[str, str]] = field(default_factory=list)

    # ── convenience readers, used by the contract and by callers ──
    def blocks_of(self, kind: str) -> list[dict]:
        return [b for b in self.blocks if b.get("type") == kind]

    def stat_sources(self) -> list[str]:
        return [str(b.get("sourceUrl") or "") for b in self.blocks_of("stat")]

    def cite_urls(self) -> list[str]:
        out: list[str] = []
        for b in self.blocks_of("cite"):
            out += [str(s.get("url") or "") for s in (b.get("sources") or [])]
        return out

    def internal_links(self) -> list[str]:
        """Site-relative links. Internal links live in `cite` sources as bare paths (`/tools/…`)."""
        return [u for u in self.cite_urls() if u.startswith("/")]

    def to_dict(self) -> dict:
        d = {
            "slug": self.slug, "title": self.title, "lede": self.lede, "tldr": self.tldr,
            "authorSlug": self.author_slug, "publishedAt": self.published_at,
            "readingMinutes": self.reading_minutes, "tags": self.tags,
            "blocks": self.blocks, "faq": self.faq,
        }
        return d


def _ts(value: Any, indent: int = 0) -> str:
    """Render a Python value as a TypeScript literal.

    Deliberately emits JSON-compatible syntax — double-quoted keys and strings — which is valid
    TypeScript and sidesteps the escaping bugs that single-quoted output invites (the existing file
    is full of `\\'` because it uses single quotes; generated code should not have to get that
    right).
    """
    return json.dumps(value, ensure_ascii=False, indent=2)[0:] if indent == 0 else json.dumps(value)


def to_typescript(post: Post) -> str:
    """The post as a TypeScript object literal, ready to append to `blog.ts`'s array.

    Emitted as JSON-shaped TS: valid, `prettier`-formattable, and free of hand-escaping. The target
    repo's typecheck is the real gate — this only has to produce something it accepts.
    """
    body = json.dumps(post.to_dict(), ensure_ascii=False, indent=2)
    indented = "\n".join(("  " + line) if line else line for line in body.splitlines())
    return indented.rstrip() + ","


def validate_shape(post: Post) -> list[str]:
    """Structural problems that would fail the target repo's typecheck. Cheap, before any contract.

    Separate from the editorial contract on purpose: this is "will it compile", that is "is it good
    enough to publish". Conflating them makes a malformed block look like an editorial failure.
    """
    errs: list[str] = []
    if not post.slug or " " in post.slug or post.slug != post.slug.lower():
        errs.append(f"slug must be lowercase and hyphenated, got {post.slug!r}")
    if post.author_slug not in ("ryan", "lena"):
        errs.append(f"authorSlug must be a known author, got {post.author_slug!r}")
    if not (isinstance(post.reading_minutes, int) and post.reading_minutes > 0):
        errs.append("readingMinutes must be a positive integer")
    for i, b in enumerate(post.blocks):
        t = b.get("type")
        if t not in BLOCK_TYPES:
            errs.append(f"block {i}: unknown type {t!r} — renderer would drop it")
            continue
        if t in ("p", "h2", "h3", "antiPattern") and not str(b.get("text") or "").strip():
            errs.append(f"block {i} ({t}): empty text")
        if t == "stat":
            for k in ("stat", "context", "sourceUrl", "sourceLabel"):
                if not str(b.get(k) or "").strip():
                    errs.append(f"block {i} (stat): missing {k}")
        if t == "table":
            headers, rows = b.get("headers") or [], b.get("rows") or []
            if not headers or not rows:
                errs.append(f"block {i} (table): needs headers and rows")
            for r_i, row in enumerate(rows):
                if len(row) != len(headers):
                    errs.append(f"block {i} (table): row {r_i} has {len(row)} cells, "
                                f"expected {len(headers)}")
        if t == "list" and not (b.get("items") or []):
            errs.append(f"block {i} (list): no items")
        if t == "cite" and not (b.get("sources") or []):
            errs.append(f"block {i} (cite): no sources")
    for i, qa in enumerate(post.faq):
        if not str(qa.get("q") or "").strip() or not str(qa.get("a") or "").strip():
            errs.append(f"faq {i}: needs both q and a")
    return errs
