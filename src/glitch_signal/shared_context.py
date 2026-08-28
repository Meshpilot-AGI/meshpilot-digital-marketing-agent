"""Mesh Pilot shared-state resolver for Signal.

Queries hub-owned tables (brands, core.platform_accounts) before falling
back to local brand config. This is the first shared resolver boundary
introduced in R1.
"""
from __future__ import annotations

import os
from typing import Any, Iterable

import asyncpg
import structlog

log = structlog.get_logger(__name__)

_pool: asyncpg.Pool | None = None

# Sync lookup cache for the canonical brand id. Populated by
# `audit_brand_registry_against_hub` at startup. Lets sync callers
# (e.g. `config.brand_config()`) read the canonical id without doing
# their own DB round-trip on every call.
_canonical_id_cache: dict[str, str | None] = {}


async def _ensure_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        url = os.environ.get("POSTGRES_BRAIN_URL") or os.environ.get("HUB_DB_URL")
        if not url:
            raise RuntimeError("POSTGRES_BRAIN_URL not configured — cannot resolve hub context")
        _pool = await asyncpg.create_pool(url, min_size=1, max_size=3)
    return _pool


async def resolve_brand_display_name(brand_id: str) -> str | None:
    """Return display_name from hub `brands` table, or None if absent."""
    try:
        pool = await _ensure_pool()
    except RuntimeError:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT display_name FROM brands WHERE brand_id = $1", brand_id
        )
    return row["display_name"] if row else None


async def resolve_connected_platforms(brand_id: str) -> set[str]:
    """Return platforms with live OAuth tokens for this brand.

    Queries `core.platform_accounts` for rows where the brand has a
    connected account (encrypted_token present and needs_reconnect false).
    """
    try:
        pool = await _ensure_pool()
    except RuntimeError:
        return set()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT platform
              FROM core.platform_accounts
             WHERE brand_id = $1
               AND encrypted_token IS NOT NULL
               AND needs_reconnect = false
            """,
            brand_id,
        )
    return {r["platform"] for r in rows}


async def resolve_brand_exists_in_hub(brand_id: str) -> bool:
    """Return True if the brand is registered in the hub."""
    try:
        pool = await _ensure_pool()
    except RuntimeError:
        return False
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM brands WHERE brand_id = $1", brand_id
        )
    return row is not None


# Alias namespace used to register Signal's snake_case brand_ids against
# the hub's canonical kebab-case brand_ids. Lives in `core.brand_aliases`
# with `system = 'signal_brand_id'`. See
# `migrations/2026-05-20-core-brands.sql` for the table definition and
# the supervisor log entry for Signal-PHASE-2b (2026-05-26) for the
# initial seed (`glitch_executor → glitch-executor`).
SIGNAL_BRAND_ALIAS_SYSTEM = "signal_brand_id"


async def resolve_canonical_brand_id(local_brand_id: str) -> str | None:
    """Return the canonical hub `core.brands.brand_id` for a Signal-local id.

    Resolution order:
      1. Look up `(system='signal_brand_id', alias=local_brand_id)` in
         `core.brand_aliases` — this maps Signal's snake_case ids onto
         the hub's canonical kebab-case ids without forcing either
         contract to bend.
      2. If no alias, check if `local_brand_id` is itself already a
         canonical id in `core.brands`. This covers brands that
         happen to share naming conventions with the hub.
      3. If neither, return None (caller should treat as drift).

    Returns None on hub-unreachable so callers do not silently mistake
    a DB outage for a missing brand. Callers must handle None
    defensively.
    """
    try:
        pool = await _ensure_pool()
    except RuntimeError:
        return None

    async with pool.acquire() as conn:
        # Alias lookup first — this is the canonical resolution path
        # for any agent that maintains its own brand-id convention.
        row = await conn.fetchrow(
            """
            SELECT brand_id
              FROM core.brand_aliases
             WHERE system = $1
               AND alias  = $2
            """,
            SIGNAL_BRAND_ALIAS_SYSTEM,
            local_brand_id,
        )
        if row:
            return row["brand_id"]

        # Identity fallback — the local id might already be canonical.
        row = await conn.fetchrow(
            "SELECT brand_id FROM core.brands WHERE brand_id = $1",
            local_brand_id,
        )
        if row:
            return row["brand_id"]

    return None


async def audit_brand_registry_against_hub(
    local_brand_ids: Iterable[str], *, source: str = "config.brand_registry"
) -> dict[str, dict[str, str | None]]:
    """Compare locally-registered brand_ids against the hub source-of-truth.

    Resolution uses `resolve_canonical_brand_id`, so a local id that
    matches the hub via `core.brand_aliases` (e.g. snake_case →
    kebab-case) is reported as `present_in_hub_via_alias`, not as
    drift.

    Status values:
      - `present_in_hub`           — local id matches `core.brands`
                                     directly
      - `present_in_hub_via_alias` — local id matches the hub through
                                     `core.brand_aliases.system='signal_brand_id'`
      - `missing_in_hub`           — neither match; real drift
      - `hub_unreachable`          — `POSTGRES_BRAIN_URL` not
                                     configured or pool init failed

    Returns `{local_brand_id: {"status": <status>, "canonical": <hub_id|None>}}`.

    Emits one `signal.brand_drift` log line per local brand. Never
    raises — Signal must still boot when the hub DB is detached.
    """
    locals_list = sorted(set(local_brand_ids))
    results: dict[str, dict[str, str | None]] = {}

    try:
        pool = await _ensure_pool()
    except RuntimeError as exc:
        log.warning(
            "signal.brand_drift",
            status="hub_unreachable",
            source=source,
            reason=str(exc),
            brands=locals_list,
        )
        for brand_id in locals_list:
            results[brand_id] = {"status": "hub_unreachable", "canonical": None}
        return results

    async with pool.acquire() as conn:
        alias_rows = await conn.fetch(
            """
            SELECT alias, brand_id
              FROM core.brand_aliases
             WHERE system = $1
               AND alias  = ANY($2::text[])
            """,
            SIGNAL_BRAND_ALIAS_SYSTEM,
            locals_list,
        )
        direct_rows = await conn.fetch(
            "SELECT brand_id FROM core.brands WHERE brand_id = ANY($1::text[])",
            locals_list,
        )
    alias_map = {r["alias"]: r["brand_id"] for r in alias_rows}
    direct_ids = {r["brand_id"] for r in direct_rows}

    for brand_id in locals_list:
        if brand_id in direct_ids:
            results[brand_id] = {"status": "present_in_hub", "canonical": brand_id}
            _canonical_id_cache[brand_id] = brand_id
            log.info(
                "signal.brand_drift",
                status="present_in_hub",
                source=source,
                brand_id=brand_id,
                canonical=brand_id,
            )
        elif brand_id in alias_map:
            canonical = alias_map[brand_id]
            results[brand_id] = {
                "status": "present_in_hub_via_alias",
                "canonical": canonical,
            }
            _canonical_id_cache[brand_id] = canonical
            log.info(
                "signal.brand_drift",
                status="present_in_hub_via_alias",
                source=source,
                brand_id=brand_id,
                canonical=canonical,
                system=SIGNAL_BRAND_ALIAS_SYSTEM,
            )
        else:
            results[brand_id] = {"status": "missing_in_hub", "canonical": None}
            _canonical_id_cache[brand_id] = None
            log.warning(
                "signal.brand_drift",
                status="missing_in_hub",
                source=source,
                brand_id=brand_id,
                hint=f"add_to_core.brands_or_core.brand_aliases_system={SIGNAL_BRAND_ALIAS_SYSTEM}",
            )
    return results


def canonical_brand_id(local_brand_id: str) -> str | None:
    """Sync lookup for the hub-canonical brand_id of a Signal-local id.

    Reads `_canonical_id_cache`, which the startup audit populates. If
    the cache has no entry (e.g. audit hasn't run yet, hub was
    unreachable, brand registered after boot), returns None so callers
    can fall back deliberately rather than silently treating the local
    id as canonical.

    For an explicit hub round-trip on demand, call the async
    `resolve_canonical_brand_id` directly.
    """
    return _canonical_id_cache.get(local_brand_id)


# ---------------------------------------------------------------------------
# Platform key mapping between hub platform names and social-agent vendor keys
# ---------------------------------------------------------------------------
_HUB_TO_SOCIAL_TARGET: dict[str, str] = {
    "tiktok": "tiktok",
    "linkedin": "linkedin",
    "meta": "facebook",  # meta account enables facebook/instagram social
}


async def resolve_publish_platform_hub_first(
    brand_id: str, target: str = "tiktok"
) -> str | None:
    """Return a publisher key if the hub confirms the underlying platform
    account is connected.

    This is intentionally narrow for R1:
      - LinkedIn direct API requires a hub-owned account.
      - TikTok direct API requires a hub-owned account.
      - Meta account implies facebook target.

    Returns None when the hub has no matching connection, signalling the
    caller to fall back to local brand config (which may use vendor
    accounts like Upload-Post that do not need a brand-specific OAuth).
    """
    from glitch_signal.config import _PUBLISH_PRIORITY, brand_config

    connected = await resolve_connected_platforms(brand_id)
    if not connected:
        return None

    # Map target to hub platform name
    hub_platform = None
    if target == "linkedin":
        hub_platform = "linkedin"
    elif target == "tiktok":
        hub_platform = "tiktok"
    elif target in ("facebook", "instagram"):
        hub_platform = "meta"
    else:
        return None

    if hub_platform not in connected:
        return None

    # Hub says the platform is connected — pick the first enabled vendor
    # from local config that matches this target.
    cfg = brand_config(brand_id)
    platforms = cfg.get("platforms", {}) or {}
    priority = _PUBLISH_PRIORITY.get(target, [])
    for key in priority:
        block = platforms.get(key) or {}
        if block.get("enabled"):
            return key
    return None
