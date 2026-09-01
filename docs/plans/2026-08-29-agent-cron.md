# Design Spec — AGENT-CRON (the agent schedules its own work)

**Date:** 2026-08-29 · **Status:** SPEC (approved; not built) · **Method:** research → brainstorming → spec
**Lane:** AGENT-CRON — a new AGENT-BRAIN increment (self-scheduling autonomy)

## Goal

Give the agent a **self-cron**: a durable scheduler where the agent (and the operator) can schedule
its **own future work** — run the loop on a goal tomorrow, curate nightly, reconcile spend daily,
re-check a campaign in 6h. This is **not** the social-post scheduler (`scheduler/queue.py`'s
sheet-posting ticks) and not the vendor-recipe library. It is the agent operating on itself on a
clock.

Prior art studied: **OpenClaw's "Automations"** (`openclaw automations` / `cron` tool). Its model —
persisted jobs, a self-scoped agent-facing tool, `agentTurn` vs `command` payloads, isolated
sessions, `next_check` self-pacing, auto-disable on repeated failure — is what we adopt. OpenClaw
runs this inside an always-on Gateway process; we are on FastAPI Cloud (multi-worker,
request/response), so we adopt the *pattern* on our durable-Postgres + in-process-tick stack, not
the runtime.

## Decisions (locked in brainstorming)

1. **Firing across workers: atomic claim (`FOR UPDATE SKIP LOCKED`).** Every worker's tick sweeps;
   each due job is claimed so it fires exactly once. No leader election. Mirrors the `agent_runs`
   DB-backed pattern from AGENT-LOOP.
2. **Payloads: `agentTurn` + `capability`.** (`stream`/`on-exit`/`systemEvent`/webhook deferred.)
3. **Who schedules: operator + self-scoped agent.** Operator via jobs-auth endpoints; the agent
   mid-run via a self-scoped `schedule` tool (sees/cancels only its own jobs; creator-cap;
   kill-switch).

## Architecture

Reuse the runtime we already have. The in-process scheduler loop (`scheduler/queue.py`, started per
worker at startup, ticks every `scheduler_tick_ms`) gains one tick — `_scheduled_jobs_tick()` —
rate-limited to a ~20s sweep interval. Payload execution reuses AGENT-LOOP (`agent/loop/runner.run`)
and the policy gate. New dependency: **`croniter`** (+ `zoneinfo`) for cron-expression next-time.

```
scheduler tick (per worker) ──> _scheduled_jobs_tick() ──> claim-and-advance (SKIP LOCKED)
                                                          └─> dispatch payload (background task)
                                                                ├─ agentTurn  → runner.run() → agent_runs
                                                                └─ capability → registry[name]()
```

## Data model — Supabase migration (`supabase/migrations/*_scheduled_jobs.sql`), RLS on

**`scheduled_jobs`**

| column | type | notes |
|---|---|---|
| `id` | uuid pk | |
| `brand_id` | text not null | |
| `name` | text not null | stable label; unique per `(brand_id, owner, name)` |
| `owner` | text not null | `operator` \| `agent:<brand>` — drives self-scoping |
| `enabled` | boolean default true | |
| `schedule_kind` | text | `at` \| `every` \| `cron` |
| `schedule` | jsonb | `{at?, every_ms?, cron_expr?, tz?}` |
| `payload_kind` | text | `agentTurn` \| `capability` |
| `payload` | jsonb | agentTurn `{goal, max_steps}`; capability `{name, args}` |
| `next_run_at` | timestamptz | the claim key (null once a one-shot is spent) |
| `last_run_at` | timestamptz | |
| `pacing` | jsonb default '{}' | `{min_ms?, max_ms?}` — bounds for `next_check` |
| `delete_after_run` | boolean default false | one-shot `at` cleanup |
| `created_scope` | text, nullable | scope of the run that created this job (#196 finding 9); re-checked at fire time against the live-resolved pipeline scope so it can't widen between create and fire. `NULL` on pre-migration rows → treated as the default `chat` scope (fail closed), not unlimited trust |
| `fail_count` | int default 0 | consecutive failures → auto-disable |
| `disabled_reason` | text | |
| `created_at`/`updated_at` | timestamptz default now() | |

Indexes: `(enabled, next_run_at)` (the sweep), `(brand_id, owner)` (self-scoping/list).

**`scheduled_runs`** — run history / background-task record

| column | type | notes |
|---|---|---|
| `id` | uuid pk | |
| `job_id` | uuid | fk → scheduled_jobs |
| `brand_id` | text | |
| `started_at`/`finished_at` | timestamptz | |
| `status` | text | `running` \| `done` \| `error` \| `skipped` |
| `result` | jsonb | agentTurn → `{run_id}` (links to `agent_runs`); capability → summary |
| `error` | text | |

Index: `(job_id, started_at desc)`.

## Firing — cross-worker exactly-once

One transaction per sweep:

```sql
SELECT * FROM scheduled_jobs
 WHERE enabled AND next_run_at IS NOT NULL AND next_run_at <= now()
 ORDER BY next_run_at
 FOR UPDATE SKIP LOCKED
 LIMIT :n;
```

For each claimed row, **in the same txn**: compute and set `next_run_at` to the next occurrence
(`every` → anchor + k·interval; `cron` → croniter next in `tz`; `at` → `NULL` + disable, and delete
if `delete_after_run`); set `last_run_at = now()`; insert a `scheduled_runs(status='running')`.
**Commit** (releases the row locks), then dispatch each payload in the background via
`asyncio.create_task`.

Advancing `next_run_at` *before* dispatch is what guarantees exactly-once: another worker's
concurrent sweep skips locked rows during the txn, and after commit the row's `next_run_at` no
longer matches `<= now()`. We never hold a row lock across a long agent turn.

## Payload execution

- **agentTurn** → `agent/loop/runner.run(brand_id, goal, max_steps)`. Already sets the COST-METER
  brand contextvar, passes the policy gate, and persists to `agent_runs`. `scheduled_runs.result =
  {run_id}`. The current `scheduled_jobs.id` is put on a contextvar so the loop's `schedule` tool
  can self-pace this job via `next_check`.
- **capability** → an **allowlisted registry** `{name: coroutine}` in `agent/cron/capabilities.py`.
  INC-1 registers: `curate` (`agent.learn.curate`), `drive_scout` (existing graph entry). `reconcile`
  is registered as a hook whose body is delivered by COST-METER INC-2. The allowlist means a job can
  never invoke arbitrary code. Each capability run is wrapped in `asyncio.wait_for`.

Failure handling: a payload error increments `fail_count`; after N consecutive failures (config,
default 3) the job is disabled with `disabled_reason`. A success resets `fail_count`.

## Agent self-scheduling tool — `schedule`

A new loop capability-tool (registered like `recall`/`remember`), actions:

- `create {name, schedule, payload, pacing?}` — `owner` stamped `agent:<brand>`.
- `list` — **self-scoped**: returns only jobs where `owner = agent:<brand>` for the active brand.
- `cancel {id}` — self-scoped; refuses a job it does not own.
- `next_check {in:"30m"}` — valid only while executing an `agentTurn` job (job id from the
  contextvar). Re-paces **this** job's `next_run_at`, clamped to `pacing.min_ms/max_ms`.

Guards: **creator-cap** (max active agent-owned jobs per brand, config, default e.g. 20 → reject
beyond); the global **`agent_cron_enabled`** kill-switch and per-brand deny via the existing
`Policy`. Publishing inside a scheduled `agentTurn` still hits the existing publish kill-switch, so
self-cron cannot become a backdoor to posting.

## Operator endpoints (jobs-auth, `x-jobs-token`)

| method | path | purpose |
|---|---|---|
| POST | `/internal/cron/jobs` | create `{brand, name, schedule, payload, enabled?, pacing?}` |
| GET | `/internal/cron/jobs?brand=` | list all jobs for a brand |
| GET | `/internal/cron/jobs/{id}` | job + recent `scheduled_runs` |
| PATCH | `/internal/cron/jobs/{id}` | enable/disable, reschedule, edit payload |
| DELETE | `/internal/cron/jobs/{id}` | remove |
| POST | `/internal/cron/jobs/{id}/run` | force a run now (out-of-band; preserves the natural next slot) |
| GET | `/internal/cron/runs?job_id=` | run history |

## Safety summary

Self-scoping (agent sees only its own jobs) · creator-cap · global kill-switch + per-brand deny ·
auto-disable after repeated failure · one-shot `delete_after_run` · claim advances `next_run_at`
before dispatch (no double-fire) · lock never held during payload · capability allowlist ·
`asyncio.wait_for` timeouts · publish kill-switch still governs any posting inside a scheduled turn.

## Out of scope for INC-1

- `stream` / `on-exit` event triggers, webhook delivery, condition-gate scripts.
- The **skill-workshop / self-authoring skill corpus** (OpenClaw's *other* gap) — separate lane.
- The `reconcile` capability's body (balance-delta) — COST-METER INC-2; INC-1 only registers the hook.

## Testing

Unit (fake engine, no DB — mirrors `test_agent_loop.py` run-store tests):
- next-run computation for `every` / `cron` (tz) / `at`.
- claim-and-advance logic (advances `next_run_at`, inserts `scheduled_runs`, handles one-shot).
- capability registry dispatch + unknown-name rejection.
- `schedule` tool self-scoping (agent sees/cancels only its own jobs) + creator-cap + kill-switch.
- `next_check` clamps to pacing bounds.
Integration note: `FOR UPDATE SKIP LOCKED` exactly-once is a DB-level guarantee — asserted against
Postgres in the live check, not the unit fakes.

## Verify live (acceptance)

1. `every 2m` `capability=curate` job for GE → `scheduled_runs` rows accrue, `curate` effects visible.
2. `at` one-shot `agentTurn` → an `agent_runs` row appears (linked via `scheduled_runs.result.run_id`)
   and the job auto-deletes.
3. Confirm a **single** fire per due time despite multiple workers (no duplicate `scheduled_runs`).
4. Flip `agent_cron_enabled=false` → sweep stops firing; agent `schedule create` is denied.

## Dependencies / migration

- Add `croniter` to `pyproject.toml`.
- `supabase/migrations/<ts>_scheduled_jobs.sql` — both tables + indexes + RLS; idempotent.

## Follow-ons

- INC-2 (this subsystem): `stream`/`on-exit` triggers + webhook delivery.
- COST-METER INC-2 supplies the `reconcile` capability body → schedule it daily here.
- Separate lane: agent **self-skills** corpus + loader + skill-workshop (the other OpenClaw gap).
