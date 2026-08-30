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

## Verified

Live against real OpenRouter: `tier=simple`→Haiku, `tier=complex`→Sonnet 5, multi-model fallback array
+ system `cache_control` accepted, per-model metrics recorded. Suite **540 pass**.
