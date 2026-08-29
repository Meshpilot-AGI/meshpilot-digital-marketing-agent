# Cost metering — per-brand spend across every vendor (COST-METER)

The agent spends real money on every brand it runs: Anthropic tokens (the brain),
Higgsfield/MUapi/HeyGen credits (media), NVIDIA embeddings. Most of these vendors bill at the
**account** level and give us **no per-tenant tagging** — their dashboard shows one aggregate
number, not "how much did the agent spend on Glitch Executor this week". So we cannot ask the
vendors that question; we have to answer it ourselves.

## The approach (industry consensus for multi-tenant AI cost)

**Self-meter at our own choke points.** Every model / media call already funnels through a
handful of our functions. We record one usage event there, attribute it to the **active brand**,
and cost it from a maintained **price book**. The vendor's own bill becomes the *reconciliation*
target (INC-2), not the source of truth.

Three pieces:

1. **Ambient brand attribution** (`analytics/cost/context.py`) — a `contextvar` set once at each
   run/job boundary (`agent/loop/runner.run`, `media/generation/runner.generate`,
   `agent/learn/curator.curate`). Deep vendor calls read it via `get_brand()`; nobody has to
   thread a `brand_id` parameter down to the HTTP layer. contextvars propagate across `await` and
   into `asyncio.create_task`, so the backgrounded agent run keeps its brand.

2. **Price book** (`analytics/cost/pricing.py`) — config-driven, env-overridable defaults:
   - Anthropic: USD per 1M tokens per model, incl. cache-read / cache-write rates
     (`COST_ANTHROPIC_PRICES`).
   - Higgsfield: `base_credits` per model × `COST_HIGGSFIELD_CREDIT_USD`
     (`COST_HIGGSFIELD_MODEL_CREDITS`).
   Prices are **estimates**; INC-2 reconciles them against each vendor's real balance.

3. **Meter + rollup** (`analytics/cost/meter.py`) — `record_usage(...)` inserts one row into
   `usage_events`; it is **fail-soft** (a DB/Logfire error is logged, never raised — metering must
   never break the generation it measures) and also emits a Logfire span (gen_ai.* + brand + cost)
   when `LOGFIRE_TOKEN` is set. `spend_summary(brand, from, to)` rolls events up per vendor.

## Data model — `usage_events`

`supabase/migrations/20260829110000_usage_events.sql`. One row per billable vendor call:

| column | meaning |
|---|---|
| `brand_id` | the brand the call is billed to (`unattributed` if the contextvar was unset) |
| `vendor` | `anthropic` \| `higgsfield` \| `muapi` \| `heygen` \| `nvidia` |
| `operation` | `chat` \| `embed` \| `image.generate` \| `video.generate` \| … |
| `model` | vendor model / application slug |
| `units` | jsonb — `{input_tokens, output_tokens, cache_*, credits, …}` |
| `cost_usd` | estimated USD from the price book |
| `estimated` | `true` until reconciled against the vendor bill (INC-2) |
| `request_id` | vendor request id, for reconciliation / dedup |

Indexed on `(brand_id, created_at desc)` and `(vendor, created_at desc)`. RLS on (service-role only).

## Reading spend

`GET /internal/analytics/spend?brand=<id>&days=<n>` (x-jobs-token). Returns the per-vendor
breakdown + totals for the window. `estimated: true` flags that costs are price-book estimates.

```bash
curl -sS "$BASE/internal/analytics/spend?brand=glitch_executor&days=30" -H "x-jobs-token: $TOK"
```

## Scope

- **INC-1 (this lane):** the metering core — table, context, price book, meter, spend endpoint,
  Logfire emit. Capture wired for **Anthropic** (loop LLM `_post`) and **Higgsfield** (engine
  `generate`). These are the two vendors whose per-call usage we can read at our layer today.
- **INC-2 (done 2026-08-29):** MUapi + HeyGen capture (coarse per-call estimate from the price book,
  reconciled by balance-delta) + a **balance-delta reconciliation** job. Capture: `MuapiEngine.generate`
  (covers both media and the content-text path, which share the engine) and `HeyGenEngine.generate`.
  Reconciliation (`analytics/cost/reconcile.py`, run via the `reconcile` cron capability or
  `POST /internal/analytics/reconcile`): snapshots each credit vendor's queryable balance
  (`balance_snapshots`), diffs it against the previous snapshot (= true account-wide spend for the
  window), and compares that to our summed `usage_events`; drift > 5% logs a warning. Robust to any
  vendor's balance being unavailable (per-vendor `unavailable` status, never raises). Reconciliation
  is an aggregate accuracy check + drift alarm — per-brand attribution stays from self-metering, so
  `estimated` remains true (an aggregate delta can't set per-event true cost). Anthropic is not
  reconciled here: its per-call token cost is already accurate (the "easy" vendor). Vendor balance
  endpoints: HeyGen `/v2/user/remaining_quota` (legacy, sunset 2026-10-31 → migrate to `/v3/users/me`);
  MUapi `/account/balance`; Higgsfield `/v1/account` — the latter two are best-effort and verified
  against the live account.
- **INC-3 (done 2026-08-29):** per-brand daily budget gate + a hard `max_steps` ceiling + an
  ops/anomaly view. `analytics/cost/budget.py`: `clamp_steps` (caps any caller/payload `max_steps` to
  `agent_max_steps_ceiling`, default 12 — closes the unbounded-steps cost hole), `budget_status` /
  `check` (today's metered spend vs the brand's daily cap; 0 = unlimited, per-brand override via
  `brand_env("DAILY_BUDGET_USD")`). Enforced at the agent-run choke point (`runner.run` halts before
  spending when over) and on the paid-media tool. **Fail-open** — a broken meter never blocks work.
  Ops view: `GET /internal/analytics/budget?brand=` returns cap/spent/remaining/pct + a spend-spike
  anomaly flag (today-so-far vs yesterday-to-now).
