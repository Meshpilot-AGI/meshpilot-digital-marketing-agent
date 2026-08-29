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

# ── Anthropic (USD per 1M tokens). Verify against current pricing; edit via env. ──
_ANTHROPIC_DEFAULT = {
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0, "cache_read": 0.10, "cache_write": 1.25},
    "claude-sonnet-5": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-opus-5": {"input": 15.0, "output": 75.0, "cache_read": 1.50, "cache_write": 18.75},
}


def _anthropic_prices() -> dict:
    raw = os.environ.get("COST_ANTHROPIC_PRICES")
    if raw:
        try:
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            pass
    return _ANTHROPIC_DEFAULT


def anthropic_cost(model: str, usage: dict) -> float:
    """usage = Anthropic response `usage` (input_tokens, output_tokens, cache_read/creation_input_tokens)."""
    prices = _anthropic_prices()
    p = prices.get(model) or next(iter(prices.values()), {"input": 1.0, "output": 5.0})
    it = float(usage.get("input_tokens", 0) or 0)
    ot = float(usage.get("output_tokens", 0) or 0)
    cr = float(usage.get("cache_read_input_tokens", 0) or 0)
    cw = float(usage.get("cache_creation_input_tokens", 0) or 0)
    per_m = 1_000_000.0
    return round(
        it * p.get("input", 0) / per_m
        + ot * p.get("output", 0) / per_m
        + cr * p.get("cache_read", p.get("input", 0)) / per_m
        + cw * p.get("cache_write", p.get("input", 0)) / per_m,
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
