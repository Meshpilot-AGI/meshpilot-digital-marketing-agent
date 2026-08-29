"""Durable OAuth tokens for MCP providers, with rotation-safe refresh.

HeyGen (and similar) issue short-lived access tokens (~1h) with a ROTATING refresh token — each
refresh returns a new refresh token and invalidates the old one. A static env secret can't survive
that, so tokens live in the `oauth_tokens` table. `get_bearer(provider)` returns a valid access
token, refreshing under a row lock (`FOR UPDATE`, so only one worker refreshes at a time) and
persisting the new access + rotated refresh atomically.

The SQLAlchemy `engine` and the HTTP refresh call are injectable for tests.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import httpx
import structlog
from sqlalchemy import text

from glitch_signal.crypto import decrypt, encrypt
from glitch_signal.db.session import _engine

log = structlog.get_logger(__name__)

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")  # some token endpoints sit behind Cloudflare
_SKEW_S = 120  # refresh when fewer than this many seconds remain

# Tokens are Fernet-encrypted at rest (#91): *_enc columns hold ciphertext; the legacy plaintext
# columns are read-only fallback for un-migrated rows and are nulled on the next write.
_SELECT = text(
    "SELECT access_token_enc, refresh_token_enc, access_token, refresh_token, expires_at, "
    "client_id, token_endpoint, resource FROM oauth_tokens WHERE provider = :p FOR UPDATE"
)
_UPDATE = text(
    "UPDATE oauth_tokens SET access_token_enc=:a_enc, refresh_token_enc=:r_enc, "
    "access_token=NULL, refresh_token=NULL, expires_at=:e, updated_at=now() WHERE provider=:p"
)
_UPSERT = text(
    "INSERT INTO oauth_tokens (provider, access_token_enc, refresh_token_enc, expires_at, "
    "client_id, token_endpoint, resource) VALUES (:p,:a_enc,:r_enc,:e,:c,:t,:res) "
    "ON CONFLICT (provider) DO UPDATE SET access_token_enc=excluded.access_token_enc, "
    "refresh_token_enc=excluded.refresh_token_enc, access_token=NULL, refresh_token=NULL, "
    "expires_at=excluded.expires_at, client_id=excluded.client_id, "
    "token_endpoint=excluded.token_endpoint, resource=excluded.resource, updated_at=now()"
)


def _effective(enc: str | None, plaintext: str | None) -> str | None:
    """Decrypt the *_enc value, or fall back to a legacy plaintext value (un-migrated row)."""
    if enc:
        return decrypt(enc)
    return plaintext

RefreshFn = Callable[[dict], Awaitable[dict]]


async def _refresh_http(row: dict) -> dict:
    """Exchange the stored refresh token for a new access (+ rotated refresh) token."""
    data = {"grant_type": "refresh_token", "refresh_token": row["refresh_token"],
            "client_id": row["client_id"]}
    if row.get("resource"):
        data["resource"] = row["resource"]
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": _UA}) as client:
        r = await client.post(row["token_endpoint"], data=data,
                              headers={"Content-Type": "application/x-www-form-urlencoded"})
    if r.status_code >= 400:
        raise RuntimeError(f"oauth refresh -> {r.status_code}: {r.text[:200]}")
    return r.json()


def _needs_refresh(expires_at: datetime | None, now: datetime, min_remaining_s: int = _SKEW_S) -> bool:
    if expires_at is None:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return (expires_at - now).total_seconds() <= min_remaining_s


async def get_bearer(provider: str, *, min_remaining_s: int = _SKEW_S, engine: Any = None,
                     refresh: RefreshFn | None = None) -> str:
    """Return a valid access token for `provider`, refreshing (rotation-safe) if fewer than
    `min_remaining_s` seconds remain. Connect-time callers use the default; the keepalive uses a
    larger window so the rotating refresh token never sits unused long enough to go stale."""
    eng = engine or _engine()
    refresh = refresh or _refresh_http

    # Txn 1 (short): read under lock, decide. The lock is released before the HTTP call so a slow
    # vendor endpoint can't hold a pooled connection + row lock for the whole round trip (#96).
    async with eng.begin() as conn:
        row = (await conn.execute(_SELECT, {"p": provider})).mappings().first()
        if row is None:
            raise RuntimeError(f"no oauth token stored for provider {provider!r}")
        now = datetime.now(timezone.utc)
        access = _effective(row["access_token_enc"], row["access_token"])
        if not _needs_refresh(row["expires_at"], now, min_remaining_s):
            return access
        refresh_req = {"refresh_token": _effective(row["refresh_token_enc"], row["refresh_token"]),
                       "client_id": row["client_id"], "token_endpoint": row["token_endpoint"],
                       "resource": row["resource"]}

    # HTTP refresh OUTSIDE any transaction — no connection or row lock held.
    tok = await refresh(refresh_req)

    # Txn 2 (short): re-lock and persist, unless a concurrent worker already refreshed.
    async with eng.begin() as conn:
        row2 = (await conn.execute(_SELECT, {"p": provider})).mappings().first()
        now2 = datetime.now(timezone.utc)
        if row2 is not None and not _needs_refresh(row2["expires_at"], now2, min_remaining_s):
            return _effective(row2["access_token_enc"], row2["access_token"])  # someone beat us to it
        access = tok["access_token"]
        new_refresh = tok.get("refresh_token") or refresh_req["refresh_token"]  # keep old if not rotated
        expires_in = int(tok.get("expires_in", 3600))
        await conn.execute(_UPDATE, {"a_enc": encrypt(access),
                                     "r_enc": encrypt(new_refresh) if new_refresh else None,
                                     "e": now2 + timedelta(seconds=expires_in), "p": provider})
        log.info("oauth.refreshed", provider=provider, expires_in=expires_in)
        return access


async def upsert(provider: str, *, access_token: str, refresh_token: str | None, expires_at: datetime,
                 client_id: str, token_endpoint: str, resource: str | None = None,
                 engine: Any = None) -> None:
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(_UPSERT, {"p": provider, "a_enc": encrypt(access_token),
                                     "r_enc": encrypt(refresh_token) if refresh_token else None,
                                     "e": expires_at, "c": client_id, "t": token_endpoint,
                                     "res": resource})
