"""Encrypted store for values the agent MINTS at runtime (SEO-11).

Config a human sets belongs in the environment. This is for the other kind: a credential the agent
creates for itself, which cannot be in the env because it does not exist until the agent makes it.
The first is a Discord webhook URL the agent provisions for its own alerts.

⚠️ Reads return the plaintext to the caller and NOTHING logs it. A webhook URL is a credential — the
holder can post as that channel.
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)

_PUT = text(
    "INSERT INTO agent_secret (brand_id, name, value_enc) VALUES (:b, :n, :v) "
    "ON CONFLICT (brand_id, name) DO UPDATE SET value_enc = EXCLUDED.value_enc, updated_at = now()"
)
_GET = text("SELECT value_enc FROM agent_secret WHERE brand_id = :b AND name = :n")


def _engine_or(engine: Any):
    from glitch_signal.db.session import _engine

    return engine or _engine()


async def put(brand_id: str, name: str, value: str, *, engine: Any = None) -> bool:
    from glitch_signal.crypto import encrypt

    try:
        async with _engine_or(engine).begin() as conn:
            await conn.execute(_PUT, {"b": brand_id, "n": name, "v": encrypt(value)})
        log.info("agent_secret.stored", brand_id=brand_id, name=name)   # never the value
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("agent_secret.put_failed", name=name, error=str(exc)[:200])
        return False


async def get(brand_id: str, name: str, *, engine: Any = None) -> str:
    """The stored value, or "" — absent and unreadable are the same to a caller, on purpose."""
    from glitch_signal.crypto import decrypt

    try:
        async with _engine_or(engine).connect() as conn:
            row = (await conn.execute(_GET, {"b": brand_id, "n": name})).first()
        return decrypt(row[0]) if row and row[0] else ""
    except Exception as exc:  # noqa: BLE001
        log.warning("agent_secret.get_failed", name=name, error=str(exc)[:200])
        return ""
