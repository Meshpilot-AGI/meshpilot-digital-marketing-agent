"""Balance-delta reconciliation (COST-METER INC-2).

Credit vendors (MUapi, HeyGen, Higgsfield) bill at the account level with no per-tenant tagging, so
we can't ask them "how much for brand X". Instead we true up our self-metered *estimate* against the
vendor's *real* spend: the drop in a vendor's queryable balance between two snapshots is the true
account-wide spend for that window, which we compare to the sum of our `usage_events`. A large drift
flags a stale price book. Per-brand attribution still comes from our self-metering; reconciliation is
an aggregate accuracy check + drift alarm.

Robust to any vendor's balance being unavailable — each vendor is handled independently and a fetch
failure is recorded as `unavailable`, never raised. Balances are fetched with the app's own vendor
keys (env), so this runs in the deployed app (e.g. the nightly `reconcile` cron capability).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import text

from glitch_signal.analytics.cost import pricing
from glitch_signal.db.session import _engine

log = structlog.get_logger("glitch_signal.cost.reconcile")

DRIFT_ALERT_THRESHOLD = 0.05  # |drift| over this → warn

VENDORS = ("muapi", "heygen", "higgsfield")

_INSERT_SNAPSHOT = text(
    "INSERT INTO balance_snapshots (vendor, balance, balance_unit, raw) "
    "VALUES (:vendor, :balance, :unit, cast(:raw as jsonb)) RETURNING id, created_at"
)
_PREV_SNAPSHOT = text(
    "SELECT balance, created_at FROM balance_snapshots WHERE vendor=:vendor "
    "ORDER BY created_at DESC LIMIT 1"
)
_SUM_EVENTS = text(
    "SELECT coalesce(sum(cost_usd), 0) AS usd, count(*) AS n FROM usage_events "
    "WHERE vendor=:vendor AND created_at >= :from_ts AND created_at < :to_ts"
)

# What a vendor's reported balance is actually denominated in. MUapi reports DOLLARS; the others
# report credits. Recording this per vendor stops the snapshot table asserting "credits" for a
# balance that is nothing of the sort — which is what hid the unit error until a real spend appeared.
BALANCE_UNIT = {"muapi": "usd", "heygen": "credits", "higgsfield": "credits"}

_CREDIT_USD = {
    "muapi": pricing.muapi_credit_usd,
    "heygen": pricing.heygen_credit_usd,
    "higgsfield": lambda: pricing._higgsfield_credit_usd(),
}


# ── balance fetchers (native credits; None if unavailable) ──
async def _fetch_heygen(client: httpx.AsyncClient) -> tuple[float | None, dict]:
    key = os.environ.get("HEYGEN_API_KEY", "").strip()
    if not key:
        return None, {"error": "HEYGEN_API_KEY unset"}
    # v2 remaining_quota is Legacy (sunset 2026-10-31) but stable; migrate to GET /v3/users/me later.
    r = await client.get("https://api.heygen.com/v2/user/remaining_quota", headers={"X-Api-Key": key})
    data = (r.json() or {}).get("data") or {}
    q = data.get("remaining_quota")
    return (float(q) if q is not None else None), {"remaining_quota": q}


async def _fetch_muapi(client: httpx.AsyncClient) -> tuple[float | None, dict]:
    key = os.environ.get("MUAPI_API_KEY", "").strip()
    if not key:
        return None, {"error": "MUAPI_API_KEY unset"}
    base = (os.environ.get("MUAPI_API_BASE") or "https://api.muapi.ai/api/v1").rstrip("/")
    r = await client.get(f"{base}/account/balance", headers={"x-api-key": key})
    if r.status_code >= 400:
        return None, {"error": f"{r.status_code}: {r.text[:120]}"}
    j = r.json() or {}
    # Accept a few likely shapes: {balance}, {credits}, {data:{balance|credits}}.
    val = j.get("balance", j.get("credits"))
    if val is None and isinstance(j.get("data"), dict):
        val = j["data"].get("balance", j["data"].get("credits"))
    return (float(val) if val is not None else None), j


async def _fetch_higgsfield(client: httpx.AsyncClient) -> tuple[float | None, dict]:
    key = os.environ.get("HIGGSFIELD_API_KEY", "").strip()
    secret = os.environ.get("HIGGSFIELD_API_SECRET", "").strip()
    if not key or not secret:
        return None, {"error": "HIGGSFIELD creds unset"}
    r = await client.get("https://platform.higgsfield.ai/v1/account",
                         headers={"Authorization": f"Key {key}:{secret}"})
    if r.status_code >= 400:
        return None, {"error": f"{r.status_code}: {r.text[:120]}"}
    j = r.json() or {}
    val = j.get("credits", j.get("balance"))
    return (float(val) if val is not None else None), j


_FETCHERS = {"muapi": _fetch_muapi, "heygen": _fetch_heygen, "higgsfield": _fetch_higgsfield}


async def _reconcile_vendor(vendor: str, client: httpx.AsyncClient, now: datetime, engine: Any) -> dict:
    fetcher = _FETCHERS[vendor]
    try:
        balance, raw = await fetcher(client)
    except Exception as exc:  # noqa: BLE001
        balance, raw = None, {"error": str(exc)[:160]}

    eng = engine or _engine()
    async with eng.begin() as conn:
        prev = (await conn.execute(_PREV_SNAPSHOT, {"vendor": vendor})).mappings().first()
        await conn.execute(_INSERT_SNAPSHOT, {
            "vendor": vendor, "balance": balance,
            "unit": BALANCE_UNIT.get(vendor, "credits"), "raw": json.dumps(raw),
        })

    result: dict[str, Any] = {"vendor": vendor, "balance": balance}
    if balance is None:
        result["status"] = "unavailable"
        result["detail"] = raw.get("error")
        return result
    if prev is None or prev["balance"] is None:
        result["status"] = "baseline"  # first snapshot — nothing to diff yet
        return result

    delta_native = float(prev["balance"]) - float(balance)  # spend since last snapshot, native units
    vendor_actual = round(max(delta_native, 0.0) * _CREDIT_USD[vendor](), 6)
    async with (engine or _engine()).connect() as conn:
        row = (await conn.execute(_SUM_EVENTS, {
            "vendor": vendor, "from_ts": prev["created_at"], "to_ts": now,
        })).mappings().first()
    our_estimate = round(float(row["usd"]), 6)
    drift = (our_estimate - vendor_actual) / vendor_actual if vendor_actual > 0 else None
    unit = BALANCE_UNIT.get(vendor, "credits")
    result.update({
        "status": "reconciled",
        "window_from": prev["created_at"].isoformat() if hasattr(prev["created_at"], "isoformat") else str(prev["created_at"]),
        "balance_unit": unit,
        # MUapi's balance (and therefore its delta) is already USD, not credits — labelling it
        # `delta_credits` would expose a false unit to every consumer of this result. Vendors that
        # genuinely bill in credits (HeyGen, Higgsfield) keep `delta_credits` for compatibility.
        **({"delta_usd": round(delta_native, 4)} if unit == "usd"
           else {"delta_credits": round(delta_native, 4)}),
        "vendor_actual_usd": vendor_actual,
        "our_estimate_usd": our_estimate,
        "our_events": int(row["n"]),
        "drift": round(drift, 4) if drift is not None else None,
    })
    if drift is not None and abs(drift) > DRIFT_ALERT_THRESHOLD:
        log.warning("cost.reconcile.drift", vendor=vendor, drift=result["drift"],
                    vendor_actual_usd=vendor_actual, our_estimate_usd=our_estimate)
    return result


async def run(vendors: list[str] | None = None, *, now: datetime | None = None, engine: Any = None) -> dict:
    """Snapshot each vendor's balance, diff vs the previous snapshot, compare to our metered spend."""
    now = now or datetime.now(timezone.utc)
    targets = [v for v in (vendors or VENDORS) if v in _FETCHERS]
    async with httpx.AsyncClient(timeout=30) as client:
        results = [await _reconcile_vendor(v, client, now, engine) for v in targets]
    return {"reconciled_at": now.isoformat(), "vendors": results}
