"""Model routing (ROUTER) — pick a COST-FIRST OpenRouter model list per task tier, with native
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

⚠️ **Ordering changed to CHEAPEST-FIRST for the working tiers (2026-09-15, operator request).
`critical` is exempt and stays quality-first — see the note on that tier. The semantics are worth
being precise about.** OpenRouter's `models` array fails over on an ERROR — a provider outage, a rate
limit, a 4xx — and NEVER on a weak answer. So cheapest-first does not mean "try cheap, escalate if
the output is poor": it means the cheapest model answers essentially everything, and the costlier
entries are an availability backstop. That is a real cost reduction and a real quality trade, not a
free lunch. Where a caller can DETECT a bad answer (the job scorer can: pass 2 must parse as JSON),
it should escalate explicitly — see `agent/jobs/score.py`, which retries on a stronger tier.

Ordering below is from live OpenRouter pricing (2026-09-15), blended 3:1 input:output because these
calls are input-heavy, NOT from guesswork about which model "feels" cheaper.
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
# ⚠️ **The account's privacy settings decide this roster, and they are not in this repo.** Two
# separate OpenRouter settings gate every slug here, and a change to either can kill a tier without a
# line of code changing:
#   1. *Allowed Providers* — Google Vertex, Cloudflare, Amazon Bedrock, Google AI Studio, Azure.
#   2. *Data Training* — all four toggles OFF as of 2026-09-02, so no endpoint that trains on, retains
#      or publishes request data is eligible. Tightening this NARROWS the endpoint pool.
# Re-probe after touching either. `scripts/probe_router_models.py` is the check, and it takes about a
# minute — cheaper than discovering it from an empty completion in production.
#
# Every slug below returned real text on three consecutive live calls, 2026-09-02, WITH those
# settings in force. Re-probe rather than trusting this comment.
TIERS: dict[str, list[str]] = {
    # Cheapest first. $/1M blended (3:1 input:output), measured live 2026-09-15.
    # Third entry is deliberately NOT Anthropic where possible: every Anthropic slug here is served
    # by amazon-bedrock, so an all-Anthropic tier fails as one unit.
    # ⚠️ `critical` is DELIBERATELY EXEMPT from cheapest-first and stays quality-first. It is the
    # tier for the conscience critic — "the last thing between the agent and the public" — and for
    # irreversible work. A previous lane moved that critic OFF the cheapest model on purpose
    # (tests/test_router_in_play.py::test_the_safety_gate_runs_on_the_strongest_tier); reordering
    # this tier would silently revert that fix. Cost-first belongs where a bad answer is cheap to
    # notice and redo, not where it is the safety gate.
    "critical": ["anthropic/claude-opus-5",    # $10.00
                 "anthropic/claude-opus-4.8",  # $10.00
                 "openai/gpt-5.6-sol"],        # $4.00
    "complex":  ["z-ai/glm-5.3",              # $2.15
                 "anthropic/claude-sonnet-5",  # $4.00
                 "anthropic/claude-sonnet-4.6"],  # $6.00
    "moderate": ["openai/gpt-5.6-luna",       # $0.45
                 "deepseek/deepseek-v4-pro",   # $2.00
                 "z-ai/glm-5.2"],              # $2.15
    "simple":   ["z-ai/glm-5.3-flash",        # $0.12
                 "google/gemini-2.5-flash",    # $0.85
                 "anthropic/claude-haiku-4.5"],  # $2.00
}

# The quality-first ordering this replaced, kept so it can be restored per-tier without archaeology:
#   critical  opus-5, opus-4.8, gpt-5.6-sol
#   complex   sonnet-5, glm-5.3, sonnet-4.6
#   moderate  glm-5.2, gpt-5.6-luna, deepseek-v4-pro
#   simple    haiku-4.5, glm-5.3-flash, gemini-2.5-flash
# Restore one with e.g. AGENT_ROUTER_COMPLEX="anthropic/claude-sonnet-5,z-ai/glm-5.3".


# Still unreachable for this account, kept by name so a future session sees they were dropped
# deliberately rather than re-adding them from memory.
#
# The two blocks are DIFFERENT settings and need different fixes:
#   - `kimi-k3` is served by nobody on the Allowed Providers list (Google Vertex, Cloudflare, Amazon
#     Bedrock, Google AI Studio, Azure) — an allowlist problem.
#   - `claude-fable-5` fails with "0 endpoints … matching your guardrails": the Zero Data Retention
#     toggle for Anthropic disables first-party Anthropic endpoints, and Bedrock/Vertex do not serve
#     it. Adding a provider would not help; only relaxing ZDR would, which is a privacy decision.
UNREACHABLE_2026_09_02 = ("anthropic/claude-fable-5", "anthropic/claude-fable-5-1",
                          "moonshotai/kimi-k3")
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
