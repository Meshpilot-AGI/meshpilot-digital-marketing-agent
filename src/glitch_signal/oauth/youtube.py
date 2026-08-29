"""YouTube (Google) OAuth2 flow + token refresh — per brand.

Flow: GET /oauth/youtube/start?brand=<id>
         → signed state → redirect to Google's consent screen
      GET /oauth/youtube/callback?code=...&state=...
         → verify state → exchange code → store encrypted tokens (PlatformAuth)

Per-brand client credentials resolve via brand_env (<PREFIX>_YOUTUBE_CLIENT_ID /
_SECRET). YouTube needs OAuth2 user consent — a service account cannot act on a
channel. `access_type=offline` + `prompt=consent` guarantee a refresh token.

Docs: https://developers.google.com/identity/protocols/oauth2/web-server
      https://developers.google.com/youtube/v3/guides/uploading_a_video
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
import structlog

from glitch_signal.config import brand_env, settings
from glitch_signal.crypto import make_state_token, verify_state_token
from glitch_signal.oauth import storage

log = structlog.get_logger(__name__)

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"


def _client_creds(brand_id: str) -> tuple[str, str]:
    cid = brand_env("YOUTUBE_CLIENT_ID", brand_id)
    csec = brand_env("YOUTUBE_CLIENT_SECRET", brand_id)
    if not cid or not csec:
        raise RuntimeError(
            f"YouTube OAuth client not configured for brand={brand_id} "
            "(<PREFIX>_YOUTUBE_CLIENT_ID / _SECRET)."
        )
    return cid, csec


def build_authorize_url(brand_id: str) -> str:
    cid, _ = _client_creds(brand_id)
    state = make_state_token({"b": brand_id, "p": "youtube"})
    params = {
        "client_id": cid,
        "redirect_uri": settings().youtube_redirect_uri,
        "response_type": "code",
        "scope": settings().youtube_oauth_scopes,
        "access_type": "offline",  # get a refresh token
        "prompt": "consent",       # force a refresh token on every consent
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


def parse_state(state: str) -> str:
    """brand_id from a verified state token. Raises ValueError on bad state."""
    payload = verify_state_token(state)
    if payload.get("p") != "youtube":
        raise ValueError("state token platform mismatch")
    brand_id = payload.get("b")
    if not brand_id:
        raise ValueError("state token missing brand")
    return brand_id


async def exchange_code_for_tokens(code: str, brand_id: str) -> dict:
    cid, csec = _client_creds(brand_id)
    data = {
        "client_id": cid,
        "client_secret": csec,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": settings().youtube_redirect_uri,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(_TOKEN_URL, data=data)
    payload = _safe_json(resp)
    if resp.status_code >= 400 or "access_token" not in payload:
        log.error("youtube.token_exchange_failed", status=resp.status_code, body=payload)
        raise RuntimeError(f"YouTube token exchange failed: {payload}")
    return payload


async def refresh_access_token(refresh_token: str, brand_id: str) -> dict:
    cid, csec = _client_creds(brand_id)
    data = {
        "client_id": cid,
        "client_secret": csec,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(_TOKEN_URL, data=data)
    payload = _safe_json(resp)
    if resp.status_code >= 400 or "access_token" not in payload:
        log.error("youtube.token_refresh_failed", status=resp.status_code, body=payload)
        raise RuntimeError(f"YouTube token refresh failed: {payload}")
    return payload


async def persist_tokens(brand_id: str, tokens: dict) -> str:
    expires_in = int(tokens.get("expires_in") or 0)
    expires_at = (
        datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=expires_in)
        if expires_in
        else None
    )
    scopes = [s for s in str(tokens.get("scope") or "").split() if s]
    return await storage.upsert(
        brand_id=brand_id,
        platform="youtube",
        account_identifier=None,
        access_token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token"),
        access_token_expires_at=expires_at,
        scopes=scopes,
        raw_provider_response=tokens,
    )


async def get_fresh_access_token(brand_id: str) -> str:
    """A currently-valid access token, refreshing if needed. Raises if no auth."""
    auth = await storage.get(brand_id, "youtube")
    if not auth:
        raise RuntimeError(
            f"No YouTube auth for brand={brand_id}. Run the consent flow at "
            f"/oauth/youtube/start?brand={brand_id}"
        )
    now = datetime.now(UTC).replace(tzinfo=None)
    if auth.access_token_expires_at and auth.access_token_expires_at - timedelta(minutes=10) <= now:
        if not auth.refresh_token:
            await storage.mark_needs_reauth(brand_id, "youtube")
            raise RuntimeError("YouTube access token expired and no refresh token available")
        refreshed = await refresh_access_token(auth.refresh_token, brand_id)
        # Google does not return a new refresh_token on refresh — keep the stored one.
        refreshed.setdefault("refresh_token", auth.refresh_token)
        await persist_tokens(brand_id, refreshed)
        return refreshed["access_token"]
    return auth.access_token


def _safe_json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except Exception:
        return {"error": "non_json_response", "body": resp.text[:500]}
