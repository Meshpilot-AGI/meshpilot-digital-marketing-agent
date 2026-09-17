"""Read the operator's Gmail through the stored OAuth grant. Read-only, by construction.

The token this uses carries `gmail.readonly` and nothing else (see `oauth/gmail.py`), so there is no
code path here that could send, label, archive or delete. That is deliberate: the agent's reason to
read mail is to find out what happened — an application confirmation, a recruiter reply — and none of
those answers require write access to the mailbox.
"""
from __future__ import annotations

import base64
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)

_API = "https://gmail.googleapis.com/gmail/v1/users/me"
_TIMEOUT = 30


async def _token(brand_id: str) -> str:
    from glitch_signal.oauth import gmail as gmail_oauth
    from glitch_signal.oauth.refresh import RefreshedTokens, get_with_auto_refresh

    async def _refresh(refresh_token: str) -> RefreshedTokens:
        t = await gmail_oauth.refresh_access_token(refresh_token, brand_id)
        return RefreshedTokens(
            access_token=t["access_token"],
            refresh_token=t.get("refresh_token"),
            expires_in=int(t.get("expires_in") or 0),
            scopes=[s for s in str(t.get("scope") or "").split() if s] or None,
        )

    auth = await get_with_auto_refresh(brand_id=brand_id, platform=gmail_oauth.PLATFORM,
                                       refresh_callback=_refresh)
    return auth.access_token


async def search(brand_id: str, query: str, *, limit: int = 10,
                 client: httpx.AsyncClient | None = None) -> list[dict]:
    """Gmail search (the same query syntax as the Gmail box) → message summaries.

    Returns [] when the mailbox has not been connected, rather than raising: an unconnected mailbox
    is a configuration state the operator resolves by visiting /oauth/gmail/start, not an outage the
    caller should crash on.
    """
    try:
        token = await _token(brand_id)
    except RuntimeError as exc:
        log.warning("gmail.not_connected", brand=brand_id, detail=str(exc)[:160])
        return []

    own = client is None
    c = client or httpx.AsyncClient(timeout=_TIMEOUT)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = await c.get(f"{_API}/messages", headers=headers,
                        params={"q": query, "maxResults": max(1, min(limit, 50))})
        r.raise_for_status()
        ids = [m["id"] for m in (r.json().get("messages") or [])]
        out = []
        for mid in ids:
            d = await c.get(f"{_API}/messages/{mid}", headers=headers,
                            params={"format": "metadata",
                                    "metadataHeaders": ["From", "Subject", "Date"]})
            d.raise_for_status()
            body = d.json()
            hdrs = {h["name"].lower(): h["value"]
                    for h in (body.get("payload", {}).get("headers") or [])}
            out.append({"id": mid, "from": hdrs.get("from"), "subject": hdrs.get("subject"),
                        "date": hdrs.get("date"), "snippet": body.get("snippet")})
    finally:
        if own:
            await c.aclose()
    log.info("gmail.search", brand=brand_id, query=query[:80], found=len(out))
    return out


async def message_text(brand_id: str, message_id: str,
                       client: httpx.AsyncClient | None = None) -> str:
    """The plain-text body of one message, for when the snippet is not enough."""
    token = await _token(brand_id)
    own = client is None
    c = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        r = await c.get(f"{_API}/messages/{message_id}", headers={"Authorization": f"Bearer {token}"},
                        params={"format": "full"})
        r.raise_for_status()
        payload = r.json().get("payload") or {}
    finally:
        if own:
            await c.aclose()

    def _walk(part: dict[str, Any]) -> str:
        if part.get("mimeType") == "text/plain" and (data := part.get("body", {}).get("data")):
            return base64.urlsafe_b64decode(data + "===").decode("utf-8", "replace")
        for sub in part.get("parts") or []:
            if text := _walk(sub):
                return text
        return ""

    return _walk(payload)
