"""Gmail (Google) OAuth2 — READ-ONLY, per brand. Same rails as `oauth/youtube.py`.

Flow: GET /oauth/gmail/start?brand=<id>
         → signed state → Google's consent screen
      GET /oauth/gmail/callback?code=…&state=…
         → verify state → exchange code → encrypted tokens in PlatformAuth

The agent needs to READ the operator's mail — application confirmations, recruiter replies, and
LinkedIn's job-alert emails — so the scope is `gmail.readonly` and nothing else. It is the minimum
that answers "did this application arrive", and a token that cannot send cannot send something
embarrassing on the operator's behalf if anything goes wrong downstream.

⚠️ `gmail.readonly` is a Google RESTRICTED scope. On a project whose consent screen is already
verified for other scopes, adding this one is a NEW verification item — Google reviews per scope, not
per project. Until it is approved the flow still works for accounts listed as test users on the
consent screen, with the caveat that an EXTERNAL app in Testing expires refresh tokens after 7 days.
That is a Google policy, not something this code can route around: if the consent screen shows an
"unverified app" warning, the scope has not been approved yet.

Client credentials resolve per brand first, then fall back to an APP-LEVEL client:
    <PREFIX>_GMAIL_CLIENT_ID → <PREFIX>_GOOGLE_CLIENT_ID → <PREFIX>_YOUTUBE_CLIENT_ID
                             → settings().google_oauth_client_id

⚠️ That app-level fallback is deliberate and is not a hole in "never a global credential". That rule
protects DATA access — a brand's tokens must never be reachable by another brand, and they are not:
the grant lives per-brand in `platform_auth`. A client id/secret identifies MESHPILOT to Google and
grants access to nothing on its own; a user still has to consent. One GCP project with one OAuth
client serving every brand is how OAuth apps are meant to work, and demanding a GCP project per
brand would mean a separate Google app, consent screen and verification for each.
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

PLATFORM = "gmail"
_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Read only. Deliberately NOT gmail.modify or gmail.send.
SCOPES = "https://www.googleapis.com/auth/gmail.readonly"


def _first_env(brand_id: str, *names: str) -> str | None:
    for n in names:
        if v := brand_env(n, brand_id):
            return v
    return None


def _client_creds(brand_id: str) -> tuple[str, str]:
    s = settings()
    cid = (_first_env(brand_id, "GMAIL_CLIENT_ID", "GOOGLE_CLIENT_ID", "YOUTUBE_CLIENT_ID")
           or s.google_oauth_client_id)
    csec = (_first_env(brand_id, "GMAIL_CLIENT_SECRET", "GOOGLE_CLIENT_SECRET",
                       "YOUTUBE_CLIENT_SECRET") or s.google_oauth_client_secret)
    if not cid or not csec:
        raise RuntimeError(
            f"Gmail OAuth client not configured for brand={brand_id}. Set GOOGLE_OAUTH_CLIENT_ID "
            "and GOOGLE_OAUTH_CLIENT_SECRET (one GCP OAuth client serves every brand), or a "
            "brand-specific <PREFIX>_GMAIL_CLIENT_ID/_SECRET to override it."
        )
    return cid, csec


def redirect_uri() -> str:
    """Must match an Authorized redirect URI on the GCP OAuth client, exactly, or Google refuses
    the flow with `redirect_uri_mismatch` before the consent screen is even shown."""
    return settings().gmail_redirect_uri


def build_authorize_url(brand_id: str) -> str:
    cid, _ = _client_creds(brand_id)
    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",   # we need a refresh token: the agent runs unattended
        "prompt": "consent",        # force a refresh token on every consent
        # NOT include_granted_scopes: this grant should carry gmail.readonly and nothing it
        # inherited from another flow. A token's powers should be legible from the row that stores it.
        "state": make_state_token({"b": brand_id, "p": PLATFORM}),
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


def parse_state(state: str) -> str:
    payload = verify_state_token(state)
    if payload.get("p") != PLATFORM:
        raise ValueError("state token platform mismatch")
    brand_id = payload.get("b")
    if not brand_id:
        raise ValueError("state token missing brand")
    return brand_id


def _safe_json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except Exception:  # noqa: BLE001 — a non-JSON body is itself the diagnostic
        return {"_raw": resp.text[:400]}


async def exchange_code_for_tokens(code: str, brand_id: str) -> dict:
    cid, csec = _client_creds(brand_id)
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(_TOKEN_URL, data={
            "client_id": cid, "client_secret": csec, "code": code,
            "grant_type": "authorization_code", "redirect_uri": redirect_uri()})
    payload = _safe_json(resp)
    if resp.status_code >= 400 or "access_token" not in payload:
        log.error("gmail.token_exchange_failed", status=resp.status_code, body=payload)
        raise RuntimeError(f"Gmail token exchange failed: {payload}")
    return payload


async def refresh_access_token(refresh_token: str, brand_id: str) -> dict:
    cid, csec = _client_creds(brand_id)
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(_TOKEN_URL, data={
            "client_id": cid, "client_secret": csec,
            "grant_type": "refresh_token", "refresh_token": refresh_token})
    payload = _safe_json(resp)
    if resp.status_code >= 400 or "access_token" not in payload:
        log.error("gmail.token_refresh_failed", status=resp.status_code, body=payload)
        raise RuntimeError(f"Gmail token refresh failed: {payload}")
    return payload


async def persist_tokens(brand_id: str, tokens: dict) -> str:
    expires_in = int(tokens.get("expires_in") or 0)
    expires_at = (datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=expires_in)
                  if expires_in else None)
    # Raw tokens never touch the plaintext column — only the Fernet-encrypted ones.
    safe_raw = {k: v for k, v in tokens.items()
                if k not in ("access_token", "refresh_token", "id_token")}
    return await storage.upsert(
        brand_id=brand_id, platform=PLATFORM, account_identifier=None,
        access_token=tokens["access_token"], refresh_token=tokens.get("refresh_token"),
        access_token_expires_at=expires_at,
        scopes=[s for s in str(tokens.get("scope") or "").split() if s],
        raw_provider_response=safe_raw,
    )
