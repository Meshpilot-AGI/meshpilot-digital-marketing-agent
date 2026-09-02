#!/usr/bin/env python3
"""Connect a PLATFORM-OWNER Meta credential — one token, all owned brands.

When the operator's own Meta user (e.g. Tejas) has admin access to every
pilot brand's Page/IG, we store ONE long-lived user token as the platform
owner credential (brand_id='_platform'). meta_publish then derives the
per-Page token from it on demand for any brand the owner controls — no
per-brand reconnect needed. External clients still connect their own
(brand-specific) token via influencer_connect_meta.py, which takes
precedence.

Reads a SHORT-LIVED user token from STDIN, then:
  1. exchange -> long-lived user token
  2. store it encrypted under _platform / meta / owner:<fb_user_id>
  3. enumerate every Page + linked IG the token can manage (so we can
     map brands -> pages). Prints a safe inventory; never the token.

Env: META_APP_ID/SECRET, META_GRAPH_API_VERSION, POSTGRES_BRAIN_URL,
     MESH_PILOT_SECRETS_KEY.
"""
from __future__ import annotations

import asyncio, json, os, sys
import asyncpg, httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))
from meshpilot_dashboard import secrets as mp_secrets  # noqa: E402

V = os.environ.get("META_GRAPH_API_VERSION", "v26.0")
G = "https://graph.facebook.com"
APP_ID = os.environ.get("META_APP_ID", ""); APP_SECRET = os.environ.get("META_APP_SECRET", "")


async def main():
    short = sys.stdin.read().strip()
    if not short or not APP_ID or not APP_SECRET:
        raise SystemExit("need token on stdin + META_APP_ID/SECRET")
    by = sys.argv[1] if len(sys.argv) > 1 else "help.nuraveda@gmail.com"

    async with httpx.AsyncClient(timeout=30) as c:
        me = (await c.get(f"{G}/{V}/me", params={"fields": "id,name", "access_token": short})).json()
        uid = me.get("id")
        if not uid:
            raise SystemExit(f"bad token: {me.get('error')}")
        ex = (await c.get(f"{G}/{V}/oauth/access_token", params={
            "grant_type": "fb_exchange_token", "client_id": APP_ID,
            "client_secret": APP_SECRET, "fb_exchange_token": short})).json()
        if "error" in ex:
            raise SystemExit(f"exchange failed: {ex['error'].get('message')}")
        long_user = ex["access_token"]
        # enumerate owned/managed pages + IG
        pages, url = [], f"{G}/{V}/me/accounts"
        params = {"fields": "id,name,instagram_business_account", "limit": "100", "access_token": long_user}
        while url:
            j = (await c.get(url, params=params)).json()
            if "error" in j:
                print("!! accounts list error:", j["error"].get("message")); break
            for p in j.get("data", []):
                ig = p.get("instagram_business_account") or {}
                igu = ""
                if ig.get("id"):
                    igj = (await c.get(f"{G}/{V}/{ig['id']}", params={"fields": "username", "access_token": long_user})).json()
                    igu = igj.get("username", "")
                pages.append({"page_id": p["id"], "page_name": p.get("name"),
                              "ig_user_id": ig.get("id", ""), "ig_username": igu})
            url = (j.get("paging") or {}).get("next"); params = None

    enc = mp_secrets.encrypt(long_user)
    dsn = os.environ.get("POSTGRES_BRAIN_URL") or os.environ.get("HUB_DB_URL")
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            """INSERT INTO core.platform_accounts
                 (brand_id,platform,account_id,display_name,encrypted_token,scopes,
                  account_metadata,connected_by_email,connected_at,needs_reconnect,purpose)
               VALUES ('ayurpet','meta',$1,$2,$3,$4,$5::jsonb,$6,NOW(),false,'social')
               ON CONFLICT (brand_id,platform,account_id) DO UPDATE SET
                 encrypted_token=EXCLUDED.encrypted_token, account_metadata=EXCLUDED.account_metadata,
                 connected_by_email=EXCLUDED.connected_by_email, connected_at=NOW(), needs_reconnect=false""",
            f"owner:{uid}", f"{me.get('name')} (platform owner)", enc, [],
            json.dumps({"role": "platform_owner", "fb_user_id": uid, "owner_email": by,
                        "token_type": "user_long_lived", "pages": pages}),
            by)
    finally:
        await conn.close()

    print(f"stored PLATFORM-OWNER meta token: owner={me.get('name')} uid={uid} pages={len(pages)} (encrypted)")
    print("inventory (map these to brands):")
    for p in pages:
        print(f"  page {p['page_id']} '{p['page_name']}'  IG @{p['ig_username'] or '-'} ({p['ig_user_id'] or 'no-ig'})")


if __name__ == "__main__":
    asyncio.run(main())
