"""Posting an operational alert to a Discord channel.

Sibling of `comms/email.py`, and the better channel for ops: a webhook needs no bot, no gateway and
no inbound plumbing — the API posts straight to a channel URL. The gateway in `gateway/` is the
INBOUND direction (chat → agent) and is deliberately not involved here; an alert must not depend on
the thing it might be alerting about.

⚠️ **The webhook URL is a credential.** Anyone holding it can post as that channel, so it is never
logged, never echoed into a result dict, and never included in an error message.
"""
from __future__ import annotations

from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)

# Discord rejects a message body over 2000 characters outright.
_MAX_CONTENT = 1900
_TIMEOUT_S = 20.0


async def post_alert(text: str, *, webhook_url: str, username: str = "MeshPilot",
                     client: httpx.AsyncClient | None = None) -> bool:
    """Post one alert. Returns True on delivery; never raises into a caller.

    An alerting path that can throw takes down the monitor that calls it, which is the one component
    that must survive whatever it is reporting on.
    """
    if not webhook_url:
        return False
    body = {"username": username, "content": (text or "")[:_MAX_CONTENT]}
    owns = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT_S)
    try:
        resp = await client.post(webhook_url, json=body)
        if resp.status_code >= 400:
            # The URL is a credential — report the status, never the target.
            log.warning("discord.alert_failed", status=resp.status_code, body=resp.text[:160])
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("discord.alert_error", error=str(exc)[:200])
        return False
    finally:
        if owns:
            await client.aclose()


def is_configured(webhook_url: str | Any) -> bool:
    """A Discord webhook URL, rather than something that merely looks like a string."""
    url = str(webhook_url or "")
    return url.startswith("https://discord.com/api/webhooks/") or \
        url.startswith("https://discordapp.com/api/webhooks/")


# ── provisioning an alerts channel (SEO-11) ─────────────────────────────────────────────────────
#
# The bot token lives in the CLOUD env as a write-only secret, so this cannot be run from a laptop —
# which is the point: the credential never has to leave the environment that already holds it. The
# agent creates its own alert channel, mints its own webhook, and stores the URL encrypted.

_API = "https://discord.com/api/v10"
ALERT_WEBHOOK_SECRET = "discord_alert_webhook"


async def _api(method: str, path: str, token: str, *, json_body: dict | None = None) -> Any:
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        resp = await client.request(method, f"{_API}{path}",
                                    headers={"Authorization": f"Bot {token}"}, json=json_body)
    if resp.status_code >= 400:
        raise RuntimeError(f"discord {method} {path} -> {resp.status_code}: {resp.text[:200]}")
    return resp.json() if resp.content else {}


async def provision_alert_channel(*, token: str, guild_id: str = "",
                                  channel_name: str = "alerts",
                                  webhook_name: str = "MeshPilot") -> dict:
    """Ensure an alerts channel and a webhook for it exist. Returns the URL — never logs it.

    Idempotent at both steps: an existing channel of that name is reused, and an existing webhook of
    that name on it is reused. Re-running must not litter a server with duplicate channels, and a
    second webhook would silently double every alert.
    """
    if not guild_id:
        guilds = await _api("GET", "/users/@me/guilds", token)
        if len(guilds) != 1:
            raise RuntimeError(
                f"bot is in {len(guilds)} guilds — pass guild_id explicitly "
                f"({', '.join(g.get('name', '?') for g in guilds[:5])})")
        guild_id = str(guilds[0]["id"])

    channels = await _api("GET", f"/guilds/{guild_id}/channels", token)
    existing = next((c for c in channels
                     if c.get("name") == channel_name and c.get("type") == 0), None)
    if existing:
        channel_id, created_channel = str(existing["id"]), False
    else:
        made = await _api("POST", f"/guilds/{guild_id}/channels", token,
                          json_body={"name": channel_name, "type": 0,
                                     "topic": "Automated alerts from the MeshPilot agent."})
        channel_id, created_channel = str(made["id"]), True

    hooks = await _api("GET", f"/channels/{channel_id}/webhooks", token)
    hook = next((h for h in hooks if h.get("name") == webhook_name), None)
    if hook is None:
        hook = await _api("POST", f"/channels/{channel_id}/webhooks", token,
                          json_body={"name": webhook_name})
    url = hook.get("url") or (f"{_API}/webhooks/{hook['id']}/{hook['token']}"
                              if hook.get("token") else "")
    if not url:
        raise RuntimeError("discord returned a webhook without a usable url")
    log.info("discord.alert_channel_ready", guild_id=guild_id, channel_id=channel_id,
             created_channel=created_channel, created_webhook=hook is not None)
    return {"guild_id": guild_id, "channel_id": channel_id,
            "created_channel": created_channel, "url": url}
