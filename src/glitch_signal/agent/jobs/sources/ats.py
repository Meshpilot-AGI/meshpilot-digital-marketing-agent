"""Public ATS board readers — Greenhouse, Lever, Ashby.

These are the boards employers publish themselves, read through their own public JSON endpoints.
No key, no scraping, no ToS grey area: this is the data the employer put up to be read.

Each function takes a board slug and returns the common listing shape.
"""
from __future__ import annotations

from typing import Any

from glitch_signal.agent.jobs.canonical import canonical_url

_TIMEOUT = 20


async def _get_json(url: str) -> Any:
    import httpx

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, trust_env=False) as c:
        r = await c.get(url, headers={"user-agent": "meshpilot-jobs/1.0"})
        if r.status_code != 200:
            return None
        try:
            return r.json()
        except Exception:  # noqa: BLE001 — a board that answers HTML is simply not a board
            return None


def _loc(*candidates: Any) -> str | None:
    for c in candidates:
        if isinstance(c, str) and c.strip():
            return c.strip()
        if isinstance(c, dict):
            for k in ("name", "location", "locationName", "city"):
                v = c.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
    return None


def _html_to_text(raw: str | None) -> str | None:
    """Greenhouse returns the JD as DOUBLY-escaped HTML. Unescape twice, strip tags, collapse space."""
    if not raw:
        return None
    import html as _h
    import re as _re

    t = _h.unescape(_h.unescape(raw))
    t = _re.sub(r"<(br|/p|/div|/li|/h[1-6])[^>]*>", "\n", t, flags=_re.I)
    t = _re.sub(r"<[^>]+>", " ", t)
    return _re.sub(r"[ \t]+", " ", _re.sub(r"\n{3,}", "\n\n", t)).strip() or None


async def fetch_greenhouse(slug: str, **_: Any) -> list[dict]:
    # `content=true` returns the full JD inline. Without it every Greenhouse listing scored as
    # "no jd_text archived" — two thirds of the pipeline was unscorable for want of a query param.
    data = await _get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    out = []
    for j in (data or {}).get("jobs", []) or []:
        url = canonical_url(j.get("absolute_url") or "")
        if not url:
            continue
        out.append({"source": "greenhouse", "canonical_url": url, "company": slug,
                    "title": j.get("title"), "location": _loc(j.get("location")),
                    "posted_at": j.get("updated_at"),
                    "jd_text": _html_to_text(j.get("content"))})
    return out


async def fetch_lever(slug: str, **_: Any) -> list[dict]:
    data = await _get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    out = []
    for j in data or []:
        url = canonical_url(j.get("hostedUrl") or j.get("applyUrl") or "")
        if not url:
            continue
        cat = j.get("categories") or {}
        out.append({"source": "lever", "canonical_url": url, "company": slug,
                    "title": j.get("text"), "location": _loc(cat.get("location")),
                    "posted_at": None,
                    # Lever ships the JD inline — take it, so fetch_jd never has to re-request.
                    "jd_text": (j.get("descriptionPlain") or j.get("description") or None)})
    return out


async def fetch_ashby(slug: str, **_: Any) -> list[dict]:
    data = await _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    out = []
    for j in (data or {}).get("jobs", []) or []:
        url = canonical_url(j.get("jobUrl") or j.get("applyUrl") or "")
        if not url:
            continue
        out.append({"source": "ashby", "canonical_url": url, "company": slug,
                    "title": j.get("title"), "location": _loc(j.get("location")),
                    "posted_at": j.get("publishedAt"),
                    "jd_text": j.get("descriptionPlain") or None})
    return out
