"""Zernio client — the OAuth-connected social surface (TARGET-3).

Zernio (`zernio.com/api/v1`) is a social-management platform holding an **OAuth-authorised**
connection to the brand's Reddit account — the same model as our Buffer publisher, and the reason
writing to Reddit needs no credential sharing and no Reddit Data API client of our own.

Used here for the piece that must happen *before* any participation: reading a room's **rules**.
Also exposes flairs, voting, posting and threaded replies, which TARGET-4 will use.

⚠️ Deliberately **not** used for discovery: its `/v1/reddit/search` returned nothing useful for our
queries, while redditapis.com returns live threads and communities with subscriber counts. Each
vendor is used for what it demonstrably does well.

Account ids are per-brand (`<PREFIX>_ZERNIO_REDDIT_ACCOUNT_ID`), so a second tenant points at its own
connected account with no code change.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

_BASE = "https://zernio.com/api/v1"
_TIMEOUT_S = 30


def _key() -> str:
    key = (os.environ.get("ZERNIO_API_KEY") or "").strip()
    if not key:
        try:
            from glitch_signal.config import settings

            key = (getattr(settings(), "zernio_api_key", "") or "").strip()
        except Exception:  # noqa: BLE001 — don't mask the clearer "not set" error
            key = ""
    if not key:
        raise RuntimeError("ZERNIO_API_KEY not set — required for Zernio")
    return key


def reddit_account_id(brand_id: str) -> str:
    """The brand's own connected Reddit account. Per-brand: no shared default."""
    from glitch_signal.config import brand_env

    acc = (brand_env("ZERNIO_REDDIT_ACCOUNT_ID", brand_id) or "").strip()
    if not acc:
        raise RuntimeError(
            f"<PREFIX>_ZERNIO_REDDIT_ACCOUNT_ID not set for brand {brand_id!r} — "
            "required to read subreddit rules or post"
        )
    return acc


async def _get(path: str, params: dict[str, Any] | None = None) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as c:
        r = await c.get(f"{_BASE}{path}", params=params or {},
                        headers={"Authorization": f"Bearer {_key()}"})
        if r.status_code >= 400:
            raise RuntimeError(f"zernio {path} -> {r.status_code}: {r.text[:200]}")
        return r.json() or {}


async def accounts() -> list[dict]:
    """Connected social accounts on this Zernio tenant."""
    data = await _get("/accounts")
    return [a for a in (data.get("accounts") or []) if isinstance(a, dict)]


async def subreddit_rules(brand_id: str, subreddit: str) -> dict:
    """A room's own stated rules — captured BEFORE we ever act in it.

    Returns `{"rules": [...], "siteRules": [...]}`. Each rule carries `kind`, `shortName`,
    `description`, `violationReason`. An empty `rules` list is normal and means the subreddit sets
    no rules of its own beyond Reddit's sitewide ones — it does **not** mean anything is permitted.
    """
    acc = reddit_account_id(brand_id)
    return await _get(f"/accounts/{acc}/reddit-subreddits/{subreddit.lstrip('r/').strip()}/rules")
