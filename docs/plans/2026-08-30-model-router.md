# Model Router (ROUTER) — quality-first tiering + native fallback on OpenRouter

**Status:** shipped 2026-08-30. Follows the OpenRouter migration (#176).

## What this is (and deliberately isn't)

A **lean model router**: pick the right-quality OpenRouter model per task tier, and fail over
reliably. It is `agent/loop/routing.py` + a few lines in `agent/loop/llm.py` — not a new subsystem.

It was scoped down from a much larger "4-layer zero-latency router" proposal after an honest review,
because most of that design is wrong for **this** agent:

- **No semantic cache of the brain.** The loop is a *stateful* ReAct tool-use loop — each call depends
  on the full messages + tool_results + per-brand memory + system. Returning a cached response for a
  "similar" prompt would hand the agent an action computed for a *different brand/context* → wrong
  action. Caching is for stateless Q&A, not an agent loop. (The proposed Redis approach was also
  broken: it scored entries by vector magnitude, not query similarity, so it returned arbitrary
  entries.)
- **No sub-5ms local classifier / SentenceTransformer / Phi-3.** This is a 24/7 *background* agent
  (pipelines + cron), not user-facing chat; the LLM round-trip (seconds) dominates, so microsecond
  routing optimizes nothing — and local ML models add ~500MB of deps + cold-start/memory cost for no
  benefit. A rule-based `classify()` (keywords + token count) needs no model.
- **No Redis, no "auto-tune after a week."** Premature infra + speculation before any usage data.

What *does* help — and is what we built:

## The router

`agent/loop/routing.py`

- **Tiers** (`TIERS`) — task tier → ordered OpenRouter slugs, **best first** (all verified live):
  | tier | primary → fallbacks |
  |---|---|
  | critical | `anthropic/claude-opus-5` → `anthropic/claude-fable-5` → `openai/gpt-5.6-sol` |
  | complex | `anthropic/claude-sonnet-5` → `z-ai/glm-5.3` → `moonshotai/kimi-k3` |
  | moderate | `z-ai/glm-5.2` → `openai/gpt-5.6-luna` → `deepseek/deepseek-v4-pro` |
  | simple | `anthropic/claude-haiku-4.5` → `z-ai/glm-5.3-flash` → `google/gemini-2.5-flash` |
- **`resolve(tier)`** → the ordered list. `llm._chat` sends it as OpenRouter's **`models` array**, so
  **OpenRouter itself fails over** across providers when the primary errors or rate-limits (native,
  not a hand-rolled try/except). Note: an *invalid* slug 400s upfront — fallback triggers on
  *runtime* failures, not typos.
- **`classify(text)`** — rule-based tier (no model), for callers that don't pass a tier.

## Wiring

- The main ReAct loop (`complete_tools`) defaults to **tier `complex`** (Sonnet 5 → glm-5.3 → kimi-k3).
- `complete` / `complete_messages` accept an optional `tier`; an explicit `model` always overrides
  (e.g. deliberation stays on its `AGENT_DELIBERATION_MODEL`).
- **Prompt caching re-added:** `complete_tools` marks the stable system prompt with a `cache_control`
  breakpoint (`cache_system=True`). OpenRouter forwards it to Anthropic/Gemini → a large discount on
  the repeated prefix (verified accepted; real savings show on the loop's big system+tools prefix).

## How to …

- **Override a tier without a deploy:** set `AGENT_ROUTER_<TIER>` to comma-separated slugs, e.g.
  `AGENT_ROUTER_COMPLEX="anthropic/claude-sonnet-5,z-ai/glm-5.3"`.
- **Change the loop / deliberation model:** `AGENT_LLM_MODEL` (loop default) /
  `AGENT_DELIBERATION_MODEL` (reckoning + conscience). Internal Claude names are normalized to
  OpenRouter slugs.
- **Add a model to a tier:** edit `TIERS` in `routing.py` (best first) — or use the env override.
  Verify the slug exists first: `GET https://openrouter.ai/api/v1/models`.
- **Route a specific call by task:** pass `tier="critical"|"complex"|"moderate"|"simple"` to
  `complete`/`complete_tools`, or `routing.classify(text)` to pick one.

## Monitoring

`GET /internal/agent/routing/metrics` (jobs-auth) → per-model `{calls, errors, error_rate,
latency_ms_ewma}` + the tier table. **In-process, per-worker** (FastAPI Cloud is multi-worker), so
treat it as a sample — the durable, cross-worker per-model spend lives in `usage_events` (COST-METER),
queryable via `GET /internal/analytics/spend`. For dashboards, scrape the cost table (Grafana over
Postgres) rather than this endpoint.

## Content pipeline routing (added)

`agent/llm.py::chat(tier="cheap"|"smart")` now routes through the model router by default: `cheap`
→ router `simple`, `smart` → router `complex` (quality-first list + native fallback). An explicit
`AGENT_CONTENT_[TEXT_]MODEL_<TIER>` env override still pins a single model and skips the router. So
every content node (text_writer / script_writer / scout / storyboard / media captions / influencer)
gets failover for free.

## Self-optimization — data-grounded, not speculative (added)

`agent/loop/audit.py::routing_audit()` reads `usage_events` (durable, cross-worker) and flags real
anomalies:
- **primary_idle** (`severity: "info"`) — a tier whose PRIMARY had 0 calls in the window while another
  tier model served. This is **informational, not a verdict**: `usage_events` records only the served
  model, not the requested tier, so the fallback may have served because the primary was
  degraded/rate-limited **or** because a caller pinned it directly (e.g. a content env override). The
  finding carries `{type, severity, tier, primary, active_models_in_tier, note}` and the tier list is
  the **effective (override-aware)** one from `routing.resolve()`, not the static table.
- **cost_per_call_drift** — a model whose recent cost/call is > 1.5× its own baseline
  (`{type, model, recent_cost_per_call, baseline_cost_per_call, ratio}`).

No ML, no auto-tuned thresholds — anomalies for a human, grounded in actual usage. Run it:
- **On demand:** `GET /internal/agent/routing/audit?days=1&baseline_days=7` (jobs-auth). `days` must be
  an integer in **1–30** and `baseline_days` an integer in **1–90**; a non-integer or out-of-range value
  returns **HTTP 400**. Omitted params default to `days=1`, `baseline_days=7`.
- **Nightly:** the `routing_audit` cron capability — seed a `capability` job
  `{name: "routing_audit"}` on a nightly `cron` schedule (fires when `agent_cron_enabled`).

## Verified

Live against real OpenRouter: `tier=simple`→Haiku, `tier=complex`→Sonnet 5, multi-model fallback array
+ system `cache_control` accepted, per-model metrics + audit findings correct. Suite **545 pass**.
