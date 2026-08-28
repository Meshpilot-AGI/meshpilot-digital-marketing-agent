#!/usr/bin/env python3
"""Connect a persona's Instagram for publishing — full token flow.

Reads a SHORT-LIVED user token from STDIN (the one you generate in the
Meta app / Graph API Explorer for your FB id), then:
  1. debug_token -> reports type + scopes (safe; token never printed)
  2. exchanges short-lived user token -> long-lived user token
  3. derives the PAGE access token for --page (long-lived; this is what
     publishes to the linked IG account)
  4. verifies the page token can read the IG account
  5. Fernet-encrypts the PAGE token and upserts core.platform_accounts
     (brand,'meta',page_id) purpose='influencer:<persona>'

Env: META_APP_ID, META_APP_SECRET, META_GRAPH_API_VERSION,
     POSTGRES_BRAIN_URL, MESH_PILOT_SECRETS_KEY.

  printf '%s' "$SHORTLIVED" | python influencer_connect_meta.py \
     --brand ayurpet --persona drharry \
     --page 1088860404318554 --ig 17841426921325882 --by you@x.com
"""
from __future__ import annotations

import argparse, asyncio, json, os, sys
import asyncpg, httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))
from meshpilot_dashboard import secrets as mp_secrets  # noqa: E402

V = os.environ.get("META_GRAPH_API_VERSION", "v21.0")
G = "https://graph.facebook.com"
APP_ID = os.environ.get("META_APP_ID", "")
APP_SECRET = os.environ.get("META_APP_SECRET", "")
NEED = {"instagram_basic", "instagram_content_publish", "pages_show_list", "pages_read_engagement"}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True); ap.add_argument("--persona", required=True)
    ap.add_argument("--page", required=True); ap.add_argument("--ig", required=True)
    ap.add_argument("--by", default="operator")
    a = ap.parse_args()
    short = sys.stdin.read().strip()
    if not short or not APP_ID or not APP_SECRET:
        raise SystemExit("need token on stdin + META_APP_ID/SECRET in env")

    async with httpx.AsyncClient(timeout=30) as c:
        # 1) scopes
        dbg = (await c.get(f"{G}/{V}/debug_token", params={
            "input_token": short, "access_token": f"{APP_ID}|{APP_SECRET}"})).json().get("data", {})
        scopes = set(dbg.get("scopes", []))
        print("token type:", dbg.get("type"), "| valid:", dbg.get("is_valid"))
        print("scopes:", sorted(scopes))
        missing = NEED - scopes
        if missing:
            print("!! MISSING publish scopes:", sorted(missing),
                  "\n   -> regenerate the token granting these (after app review approves content_publish).")
            # still try to derive page token so read works; publish will 403 until granted.

        # 2) short -> long-lived user token
        ex = (await c.get(f"{G}/{V}/oauth/access_token", params={
            "grant_type": "fb_exchange_token", "client_id": APP_ID,
            "client_secret": APP_SECRET, "fb_exchange_token": short})).json()
        if "error" in ex:
            raise SystemExit(f"exchange failed: {ex['error'].get('message')}")
        long_user = ex["access_token"]

        # 3) derive PAGE token
        pg = (await c.get(f"{G}/{V}/{a.page}", params={
            "fields": "name,access_token", "access_token": long_user})).json()
        if "error" in pg or not pg.get("access_token"):
            raise SystemExit(f"page token derive failed: {pg.get('error', pg)}")
        page_token = pg["access_token"]

        # 4) verify IG reachable with page token
        ig = (await c.get(f"{G}/{V}/{a.ig}", params={
            "fields": "username,followers_count", "access_token": page_token})).json()
        if "error" in ig:
            print("!! IG not reachable with page token:", ig["error"].get("message"))
            ig = {}

    # 5) encrypt + store the PAGE token
    enc = mp_secrets.encrypt(page_token)
    dsn = os.environ.get("POSTGRES_BRAIN_URL") or os.environ.get("HUB_DB_URL")
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            """INSERT INTO core.platform_accounts
                 (brand_id,platform,account_id,display_name,encrypted_token,scopes,
                  account_metadata,connected_by_email,connected_at,needs_reconnect,purpose)
               VALUES ($1,'meta',$2,$3,$4,$5,$6::jsonb,$7,NOW(),false,$8)
               ON CONFLICT (brand_id,platform,account_id) DO UPDATE SET
                 encrypted_token=EXCLUDED.encrypted_token, scopes=EXCLUDED.scopes,
                 account_metadata=EXCLUDED.account_metadata, connected_by_email=EXCLUDED.connected_by_email,
                 connected_at=NOW(), needs_reconnect=false, purpose=EXCLUDED.purpose""",
            a.brand, a.page, f"{pg.get('name')} (IG @{ig.get('username','')})", enc,
            sorted(scopes), json.dumps({
                "persona": a.persona, "fb_page_id": a.page, "ig_user_id": a.ig,
                "ig_username": ig.get("username", ""), "token_type": "page_long_lived",
                "purpose": "influencer_publishing"}),
            a.by, "social")
    finally:
        await conn.close()
    print(f"stored PAGE token: brand={a.brand} persona={a.persona} page='{pg.get('name')}' "
          f"ig=@{ig.get('username','?')} followers={ig.get('followers_count','?')} "
          f"publish_ready={not missing} (encrypted)")


if __name__ == "__main__":
    asyncio.run(main())
