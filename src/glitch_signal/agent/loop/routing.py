"""Model routing (ROUTER) — pick an OpenRouter model list per task tier, with native fallback.

This is deliberately NOT a semantic cache and NOT a sub-5ms latency layer: our brain is a stateful,
24/7 *background* ReAct loop where each call depends on the full messages + tool_results + per-brand
memory, and the LLM round-trip (seconds) dominates. Caching "similar" prompts would return wrong
actions across brands/contexts; shaving classification to microseconds optimizes nothing. So this
layer does the one thing that actually helps: route the RIGHT model per task and fail over reliably.

Each tier resolves to an ordered list `[primary, fallback, …]`; `llm._chat` sends it as OpenRouter's
`models` array so OpenRouter itself fails over across providers when the primary errors or rate-limits
— simpler and more reliable than a hand-rolled try/except chain. Per-tier env override:
`AGENT_ROUTER_<TIER>` = comma-separated OpenRouter slugs.

⚠️ The `models` array fails over on an ERROR and NEVER on a weak or empty answer. So a cheap primary
is only safe where the CALLER detects a bad answer and escalates itself (agent/jobs/score.py does),
or where an empty completion raises (llm.py does). Ordering a tier cheapest-first without one of
those is how a dead primary stays invisible.
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
    # `critical` stays quality-first: an irreversible decision is the wrong place to save $0.008.
    # `complex` is COST-FIRST — z-ai/glm-5.3 ahead of claude-sonnet-5, measured, see the note below.
    # Third entry is deliberately NOT Anthropic where possible: every Anthropic slug here is served
    # by amazon-bedrock, so an all-Anthropic tier fails as one unit.
    "critical": ["anthropic/claude-opus-5", "anthropic/claude-opus-4.8", "openai/gpt-5.6-sol"],
    "complex":  ["z-ai/glm-5.3", "anthropic/claude-sonnet-5", "anthropic/claude-sonnet-4.6"],
    "moderate": ["z-ai/glm-5.2", "openai/gpt-5.6-luna", "deepseek/deepseek-v4-pro"],
    "simple":   ["anthropic/claude-haiku-4.5", "z-ai/glm-5.3-flash", "google/gemini-2.5-flash"],
}

# COST-FIRST ON `complex` — 2026-09-15. The operator asked for cheapest-first; a first attempt was
# reverted the same day on a measurement that turned out to be measuring OUR BUG, not the model.
#
# What the failed run actually showed: re-scoring 18 real job postings on z-ai/glm-5.3 produced 0
# successes, 14 of them an empty completion with stop_reason=max_tokens. That was read as "glm-5.3
# cannot do this task". It was not. Two defects in our own code produced it:
#   1. `llm._EMPTY_RETRY_CEILING` was 8000 and gated the retry as `max_tokens < CEILING`, so a caller
#      asking for EXACTLY 8000 — which the job scorer does — got no retry at all. The empty-completion
#      retry this module advertised had never once run for the scorer.
#   2. Nothing capped `reasoning.effort`, so a reasoning model spent the whole budget thinking.
#      Raising the budget makes this WORSE, not better — more allowance buys more reasoning.
#
# The fair comparison, same prompt, one scoring call (2026-09-15):
#   z-ai/glm-5.3        @8000                  content 2048ch   reasoning 1548 tok   $0.0089
#   z-ai/glm-5.3        @20000                 content 1736ch   reasoning 3340 tok   $0.0145
#   z-ai/glm-5.3        @20000 effort=low      content 1433ch   reasoning    0 tok   $0.0027
#   anthropic/sonnet-5  @8000                  content 1992ch   reasoning    0 tok   $0.0105
# glm-5.3 completes the task, and with effort capped it is **74% cheaper than sonnet-5**.
#
# Two things make cheapest-first safe on this tier specifically, and both must stay:
#   - `agent/jobs/score.py` escalates on a DETECTED bad answer (no requirements / unparseable JSON),
#     which is the check OpenRouter's `models` array does not perform.
#   - `llm._chat` retries an empty completion with `reasoning.effort=low`, and raises if it is still
#     empty. A silent `""` never reaches a caller.
# Ordering another tier cheapest-first without an equivalent check would reproduce the original bug.
#
# ⚠️ **glm-5.3 SCORES HIGHER THAN SONNET ON THE SAME RUBRIC — this is not free.** Re-scoring the
# same 18-posting pool with the same CV (2026-09-15): 17/18 scored, Spearman 0.914 against the
# sonnet run (the ranking holds, which is what the operator actually acts on), but every single
# paired role moved UP: mean **+0.37**, max +0.8, none down. Against a FIXED 4.0 floor that is a
# loosened gate, not a better one — roles at the floor went 1 → 2 on an unchanged pool and CV.
# Whoever tunes the floor next must know it was calibrated on sonnet, not on glm. The one
# regression: a posting sonnet scored 1.8 became unscorable (pass 2 unparseable even after the
# escalation to `critical`), so 17/18 vs 18/18 — a skipped role, not a wrong one.
#
# `moderate` and `simple` were NOT flipped: they are unmeasured on this workload, and shipping an
# unmeasured cost change alongside a measured one is how the first attempt went wrong.
#
# The quality-first ordering, kept so any tier can be restored without archaeology:
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
