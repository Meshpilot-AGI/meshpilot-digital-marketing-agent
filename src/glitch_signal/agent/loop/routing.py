"""Model routing (ROUTER) — pick a quality-FIRST OpenRouter model list per task tier, with native
fallback.

This is deliberately NOT a semantic cache and NOT a sub-5ms latency layer: our brain is a stateful,
24/7 *background* ReAct loop where each call depends on the full messages + tool_results + per-brand
memory, and the LLM round-trip (seconds) dominates. Caching "similar" prompts would return wrong
actions across brands/contexts; shaving classification to microseconds optimizes nothing. So this
layer does the one thing that actually helps: route the RIGHT model per task and fail over reliably.

Each tier resolves to an ordered list `[primary, fallback, …]`; `llm._chat` sends it as OpenRouter's
`models` array so OpenRouter itself fails over across providers when the primary errors or rate-limits
— simpler and more reliable than a hand-rolled try/except chain. Per-tier env override:
`AGENT_ROUTER_<TIER>` = comma-separated OpenRouter slugs.
"""
from __future__ import annotations

import os

# task tier -> ordered OpenRouter model slugs (best first).
#
# ⚠️ **"Verified" means a real completion came back, not that the slug exists.** The previous roster
# was annotated "verified live 2026-08-30" and four of its twelve entries could not be called at all:
# this account's OpenRouter *allowed-providers* setting permits only `google-vertex, cloudflare,
# amazon-bedrock, google-ai-studio`, and those models are served by nobody on that list. A model that
# 404s on every call is not a fallback, so `critical` and `moderate` were each running on a single
# model with nothing behind them while this module advertised native failover.
#
# Also: probe TWICE before calling a model dead. `z-ai/glm-5.3` failed one probe with "Provider
# returned error" — transient, and it answers fine — which is a different thing from an access
# denial and must not be treated as one.
#
# Every slug below returned real text on a live call, 2026-09-02. Re-probe with
# `scripts/probe_router_models.py` rather than trusting this comment.
TIERS: dict[str, list[str]] = {
    # Third entry is deliberately NOT Anthropic: every Anthropic slug here is served by
    # amazon-bedrock, so an all-Anthropic tier fails as one unit. `gemini-2.5-pro` comes from
    # google-ai-studio — a genuinely independent path, which is what a fallback is for.
    "critical": ["anthropic/claude-opus-5", "anthropic/claude-opus-4.8", "google/gemini-2.5-pro"],
    "complex":  ["anthropic/claude-sonnet-5", "z-ai/glm-5.3", "anthropic/claude-sonnet-4.6"],
    "moderate": ["z-ai/glm-5.2", "google/gemini-2.5-flash", "z-ai/glm-5.3-flash"],
    "simple":   ["anthropic/claude-haiku-4.5", "z-ai/glm-5.3-flash", "google/gemini-2.5-flash"],
}

# Removed 2026-09-02 because no allowed provider serves them for this account. Kept by name so a
# future session sees they were dropped deliberately rather than re-adding them from memory.
UNREACHABLE_2026_09_02 = ("anthropic/claude-fable-5", "anthropic/claude-fable-5-1",
                          "openai/gpt-5.6-sol", "openai/gpt-5.6-luna", "moonshotai/kimi-k3",
                          "deepseek/deepseek-v4-pro")
DEFAULT_TIER = "complex"          # the main reasoning loop's default

_CRITICAL_KW = ("final review", "architecture", "launch decision", "legal", "compliance", "crisis",
                "irreversible")
_COMPLEX_KW = ("strategy", "plan", "analyze", "analysis", "campaign", "review", "draft", "write",
               "design", "reason")


def resolve(tier: str | None) -> list[str]:
    """Ordered model list for a tier. Unknown/blank → the default tier. Env override wins."""
    key = (tier or DEFAULT_TIER).strip().lower()
    override = os.environ.get(f"AGENT_ROUTER_{key.upper()}")
    if override:
        models = [m.strip() for m in override.split(",") if m.strip()]
        if models:
            return models
    return TIERS.get(key, TIERS[DEFAULT_TIER])


def classify(text: str) -> str:
    """Rule-based tier from prompt text — no model, no latency. For callers that don't pass a tier."""
    t = (text or "").lower()
    tokens = len(t.split())
    if any(k in t for k in _CRITICAL_KW):
        return "critical"
    if any(k in t for k in _COMPLEX_KW) or tokens > 400:
        return "complex"
    if tokens > 120:
        return "moderate"
    return "simple"


# ── lightweight in-process routing metrics (per worker; FastAPI Cloud is multi-worker, so treat as
#    a sample, not a global total — the durable per-model spend lives in usage_events / COST-METER) ──
_METRICS: dict[str, dict[str, float]] = {}


def record(model: str, *, latency_ms: float, ok: bool) -> None:
    m = _METRICS.setdefault(model, {"calls": 0, "errors": 0, "latency_ms_ewma": 0.0})
    m["calls"] += 1
    if not ok:
        m["errors"] += 1
    # EWMA so P50-ish latency tracks recent behavior without storing a history
    m["latency_ms_ewma"] = m["latency_ms_ewma"] * 0.8 + latency_ms * 0.2 if m["calls"] > 1 else latency_ms


def metrics() -> dict:
    """Per-model {calls, errors, error_rate, latency_ms_ewma} for this worker + the tier table."""
    out = {}
    for model, m in _METRICS.items():
        calls = m["calls"] or 1
        out[model] = {"calls": int(m["calls"]), "errors": int(m["errors"]),
                      "error_rate": round(m["errors"] / calls, 4),
                      "latency_ms_ewma": round(m["latency_ms_ewma"], 1)}
    # report the EFFECTIVE tier lists (override-aware), not the static table
    return {"models": out, "tiers": {k: resolve(k) for k in TIERS}}
