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
