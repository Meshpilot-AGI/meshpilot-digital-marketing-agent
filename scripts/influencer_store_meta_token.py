#!/usr/bin/env python3
"""Store a persona's connected Meta Page token — encrypted at rest.

Bootstrap helper until the cockpit "Connect Instagram (publishing)" OAuth
flow exists. Reads the long-lived Page/User token from STDIN (never an
arg/file), verifies it against the Graph API, Fernet-encrypts it with the
dashboard secrets key, and upserts a core.platform_accounts row keyed to
the brand + Page so meta_publish can read it per-tenant.

  printf '%s' "$TOKEN" | python influencer_store_meta_token.py \
      --brand ayurpet --persona drharry \
      --page 1088860404318554 --ig 17841426921325882 --username drharrysandu \
      --by you@example.com

Env: POSTGRES_BRAIN_URL (brain DB), MESH_PILOT_SECRETS_KEY (Fernet).
The token is never printed; only non-secret confirmation is emitted.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

import asyncpg
import httpx

# Import the dashboard's Fernet secrets (same key that encrypts the ads token).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))
from meshpilot_dashboard import secrets as mp_secrets  # noqa: E402

_GRAPH = "https://graph.facebook.com"
_VER = os.environ.get("META_GRAPH_API_VERSION", "v21.0")
_SCOPES = [
    "instagram_basic", "instagram_content_publish",
    "pages_show_list", "pages_read_engagement", "business_management",
]


async def _verify(token: str, ig_user_id: str) -> dict:
    """Confirm the token can act on the persona's IG account."""
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(
            f"{_GRAPH}/{_VER}/{ig_user_id}",
            params={"fields": "username,name,followers_count", "access_token": token},
        )
        j = r.json()
        if "error" in j:
            raise SystemExit(f"token verify failed: {j['error'].get('message')}")
        return j


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--persona", required=True)
    ap.add_argument("--page", required=True, help="FB Page id")
    ap.add_argument("--ig", required=True, help="IG business user id")
    ap.add_argument("--username", default="")
    ap.add_argument("--by", default="operator")
    ap.add_argument("--purpose", default=None)
    args = ap.parse_args()

    token = sys.stdin.read().strip()
    if not token or len(token) < 40:
        raise SystemExit("no token on stdin (pipe it: printf %s \"$TOK\" | ...)")

    ig = await _verify(token, args.ig)
    enc = mp_secrets.encrypt(token)  # bytes
    purpose = args.purpose or f"influencer:{args.persona}"

    dsn = os.environ.get("POSTGRES_BRAIN_URL") or os.environ.get("HUB_DB_URL")
    if not dsn:
        raise SystemExit("POSTGRES_BRAIN_URL not set")
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            """
            INSERT INTO core.platform_accounts
                (brand_id, platform, account_id, display_name, encrypted_token,
                 scopes, account_metadata, connected_by_email, connected_at,
                 needs_reconnect, purpose)
            VALUES ($1,'meta',$2,$3,$4,$5,$6::jsonb,$7,NOW(),false,$8)
            ON CONFLICT (brand_id, platform, account_id) DO UPDATE SET
                encrypted_token = EXCLUDED.encrypted_token,
                scopes = EXCLUDED.scopes,
                account_metadata = EXCLUDED.account_metadata,
                connected_by_email = EXCLUDED.connected_by_email,
                connected_at = NOW(),
                needs_reconnect = false,
                purpose = EXCLUDED.purpose
            """,
            args.brand, args.page, f"{ig.get('name') or args.username} (IG @{ig.get('username', args.username)})",
            enc, _SCOPES,
            __import__("json").dumps({
                "persona": args.persona, "fb_page_id": args.page,
                "ig_user_id": args.ig, "ig_username": ig.get("username", args.username),
                "token_type": "page_long_lived", "purpose": "influencer_publishing",
            }),
            args.by, purpose,
        )
    finally:
        await conn.close()

    print(f"stored: brand={args.brand} persona={args.persona} ig=@{ig.get('username')} "
          f"followers={ig.get('followers_count')} purpose={purpose} (token encrypted)")


if __name__ == "__main__":
    asyncio.run(main())
