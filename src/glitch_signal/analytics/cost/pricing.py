"""Price book — converts vendor usage into an estimated USD cost.

Prices change, so everything here is a CONFIG-DRIVEN DEFAULT, overridable via env. These are
estimates; INC-2's balance-delta reconciliation validates them against each vendor's real bill.

    COST_ANTHROPIC_PRICES   JSON {model: {input, output, cache_read, cache_write}} per **1M tokens**
    COST_HIGGSFIELD_CREDIT_USD   USD per Higgsfield credit
    COST_HIGGSFIELD_MODEL_CREDITS  JSON {slug: base_credits} (from GET /models)
"""
from __future__ import annotations

import json
import os

# ── Anthropic (USD per 1M tokens). Verified vs platform.claude.com/pricing 2026-08-30.
#    cache_read = 0.1× input; cache_write = 1.25× input (5-minute TTL). Edit via env. ──
_ANTHROPIC_DEFAULT = {
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0, "cache_read": 0.10, "cache_write": 1.25},
    "claude-sonnet-5": {"input": 2.0, "output": 10.0, "cache_read": 0.20, "cache_write": 2.50},
    "claude-opus-5": {"input": 5.0, "output": 25.0, "cache_read": 0.50, "cache_write": 6.25},
    "claude-fable-5": {"input": 10.0, "output": 50.0, "cache_read": 1.0, "cache_write": 12.50},
}


def _anthropic_prices() -> dict:
    raw = os.environ.get("COST_ANTHROPIC_PRICES")
    if raw:
        try:
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            pass
    return _ANTHROPIC_DEFAULT


def _web_search_usd() -> float:
    """USD per web_search request ($10 / 1,000 = 0.01). web_fetch is free."""
    try:
        return float(os.environ.get("COST_ANTHROPIC_WEB_SEARCH_USD", "0.01"))
    except ValueError:
        return 0.01


def anthropic_cost(model: str, usage: dict) -> float | None:
    """usage = Anthropic response `usage` (input/output tokens, cache tokens, server_tool_use).

    Returns None when `model` has no entry in the price book — the book only holds Claude models
    (#194), so a router-selected non-Anthropic fallback (glm/kimi/deepseek/gpt/…) must not be
    silently priced at an arbitrary Claude tier. Callers should treat None as "unknown", not $0.
    """
    prices = _anthropic_prices()
    p = prices.get(model)
    if p is None:
        return None
    it = float(usage.get("input_tokens", 0) or 0)
    ot = float(usage.get("output_tokens", 0) or 0)
    cr = float(usage.get("cache_read_input_tokens", 0) or 0)
    cw = float(usage.get("cache_creation_input_tokens", 0) or 0)
    ws = float((usage.get("server_tool_use") or {}).get("web_search_requests", 0) or 0)
    per_m = 1_000_000.0
    return round(
        it * p.get("input", 0) / per_m
        + ot * p.get("output", 0) / per_m
        + cr * p.get("cache_read", p.get("input", 0)) / per_m
        + cw * p.get("cache_write", p.get("input", 0)) / per_m
        + ws * _web_search_usd(),   # server-side web_search ($10/1k); web_fetch is free
        6,
    )


# ── Higgsfield (credit-based). base_credits per model × USD/credit. ──
_HIGGSFIELD_CREDITS_DEFAULT = {
    "higgsfield-ai/soul/v2/standard": 0.0,
    "higgsfield-ai/soul/cinema": 0.0,
    "higgsfield-ai/popcorn/auto": 0.0,
    "higgsfield-ai/dop/lite/first-last-frame": 2.0,
    "higgsfield-ai/dop/standard": 9.0,
    "higgsfield-ai/dop/standard/first-last-frame": 9.0,
    "higgsfield-ai/dop/turbo": 6.5,
    "higgsfield-ai/dop/turbo/first-last-frame": 6.5,
}


def _higgsfield_credit_usd() -> float:
    try:
        return float(os.environ.get("COST_HIGGSFIELD_CREDIT_USD", "0.01"))
    except ValueError:
        return 0.01


def _higgsfield_model_credits() -> dict:
    raw = os.environ.get("COST_HIGGSFIELD_MODEL_CREDITS")
    if raw:
        try:
            return {**_HIGGSFIELD_CREDITS_DEFAULT, **json.loads(raw)}
        except Exception:  # noqa: BLE001
            pass
    return _HIGGSFIELD_CREDITS_DEFAULT


def higgsfield_cost(model: str, *, base_credits: float | None = None) -> tuple[float, float]:
    """Return (credits, cost_usd). Prefer a vendor-reported base_credits, else the price book."""
    credits = base_credits if base_credits is not None else _higgsfield_model_credits().get(model, 0.0)
    return round(float(credits), 4), round(float(credits) * _higgsfield_credit_usd(), 6)


# ── MUapi (655 models, credit-based, no per-call cost in the response) ──
# A per-model price book for 655 slugs is infeasible; per-call cost here is a COARSE estimate and
# the MUapi balance-delta reconciliation (INC-2) is the source of truth. Overridable per env.
def _muapi_default_usd() -> float:
    try:
        return float(os.environ.get("COST_MUAPI_DEFAULT_USD", "0.02"))
    except ValueError:
        return 0.02


def muapi_cost(model: str) -> float:
    """Coarse per-call estimate for a MUapi generation (trued up by balance-delta reconciliation).

    Optional per-model overrides via COST_MUAPI_MODEL_USD (JSON {slug: usd})."""
    raw = os.environ.get("COST_MUAPI_MODEL_USD")
    if raw:
        try:
            book = json.loads(raw)
            if model in book:
                return round(float(book[model]), 6)
        except Exception:  # noqa: BLE001
            pass
    return round(_muapi_default_usd(), 6)


# ── HeyGen (credit-based; ~1 credit per API video by default) ──
def heygen_credit_usd() -> float:
    try:
        return float(os.environ.get("COST_HEYGEN_CREDIT_USD", "0.30"))
    except ValueError:
        return 0.30


def heygen_cost(model: str, *, credits: float | None = None) -> tuple[float, float]:
    """Return (credits, cost_usd). Defaults to 1 credit/video; trued up by balance-delta reconcile."""
    c = credits if credits is not None else float(os.environ.get("COST_HEYGEN_DEFAULT_CREDITS", "1") or 1)
    return round(float(c), 4), round(float(c) * heygen_credit_usd(), 6)


def muapi_credit_usd() -> float:
    try:
        return float(os.environ.get("COST_MUAPI_CREDIT_USD", "0.01"))
    except ValueError:
        return 0.01
