# PIPELINE — deliberate, scoped, scheduled agent runs

**Status:** shipped 2026-08-30 (inert until kill-switches are flipped). Follows SCOPE (#162).

## Why

The agent has real capabilities now (memory, knowledge, quality, media, discovery, web, schedule,
publish, MCP). SCOPE made the toolset boundable per run. The open question was *when* a capability
should turn on. Answer: **only inside a defined pipeline** — never for a free-roaming agent that
decides on its own to scrape or generate. A pipeline is the deliberate wrapper that binds a scope +
goal + cadence + the kill-switches it needs.

## Model

`agent/loop/pipelines.py` — a declarative, versioned registry (mirrors `scopes.py`). One immutable
`Pipeline(name, scope, goal, max_steps, schedule_kind, schedule, requires)`. `registry()` builds the
three; `resolve(name)`; `render_goal(brand)` templates `{brand}`; `missing_requirements()` returns
the required config flags currently off.

The pipeline composes existing enforcement — it invents no new gate:

- **SCOPE** bounds the offered *and dispatched* toolset (`scopes`, enforced at both since #163).
- **Policy** bounds effects (publish/email/discovery default-off) and spend (per-run caps).
- **Self-schedule clamp** keeps a follow-up job ⊆ the pipeline's scope (`cron.tool`, unchanged).

## The three pipelines

| Pipeline | Scope | Goal (abridged) | Effect gate → output | Cadence (UTC) |
|---|---|---|---|---|
| **discovery** | `discovery` | recall niche → `discover_trending` → distill *why each works* → `remember` angle notes | needs `agent_discovery_enabled`; no gen/publish → **memory notes** | daily 13:00 |
| **content** | `content_draft`¹ | recall angles+voice → draft caption + one-line media brief | `publish` off → **drafts for review** | daily 14:30 |
| **orm** | `orm` | web-search brand mentions → sentiment → draft replies w/ source links | `publish`/`email` off → **draft replies** | daily 15:00 |

¹ **Caption-first by default.** The `content` pipeline resolves to scope `content_draft`
(memory+knowledge+quality, no paid media) and drafts copy + a media *brief*. Flip
`agent_content_media_enabled` → it resolves to scope `content` and also generates the image/video
(MUapi/Higgsfield, bounded by `agent_max_media_per_run`). Lets the loop be validated before spending
media credits.

## Triggers (both reuse existing plumbing)

Both take **`brand` from the `?brand=` query param** — the brand `_require_jobs_auth` validated the
token against (#95) — never from the body, so one brand's jobs token cannot target another.

- **Manual (operator, live now):** `POST /internal/agent/pipeline/{name}?brand=` (jobs-auth)
  → resolve → check `requires` (409 if a switch is off) → `_run_agent_bg(run_id, brand, goal,
  max_steps, scope)`. Returns `{run_id, pipeline, scope}`; poll `GET /internal/agent/run/{id}`.
- **Scheduled (inert):** `POST /internal/agent/pipeline/{name}/schedule?brand=` (jobs-auth) seeds a
  `payload_kind=pipelineTurn` cron job (owner `pipeline:<brand>`, name `pipeline:<pipeline>`) at the
  pipeline's cadence, carrying **only the pipeline name**. The scheduler fires it **only when
  `agent_cron_enabled`** (409 while off). Idempotent per `(brand, pipeline)`: a re-seed updates the
  existing job rather than colliding on the unique index.

### Fire-time re-resolution (why the payload is name-only)

A scheduled occurrence runs through `cron.service._run_pipeline_turn`, which **re-resolves the
pipeline from the registry every fire** — reading the current scope, goal, and `requires`. So:
- a `discovery` schedule stays inert (run **skipped**, recorded not executed) while
  `agent_discovery_enabled` is off, and starts producing once it's flipped — the schedule need not be
  re-seeded;
- a `content` schedule honors the **current** `agent_content_media_enabled` (paid media on/off) on
  each run, instead of freezing that decision at seed time.

Freezing the resolved goal+scope into the payload (the first cut) silently defeated both switches —
hence name-only + live resolution.

## Ships inert

Nothing runs autonomously on merge. The manual endpoint is operator-initiated; scheduled jobs need
`agent_cron_enabled`; discovery additionally needs `agent_discovery_enabled`. Shipped config defaults
for all three are `False`.

## Enablement order

1. `POST …/pipeline/content` manually for a brand → review the drafts it remembers.
2. Happy → `POST …/pipeline/{name}/schedule` per brand, then flip `agent_cron_enabled`.
3. For discovery, also flip `agent_discovery_enabled`. For real media in content, flip
   `agent_content_media_enabled`. Publishing stays off until a separate, deliberate decision.

## Tests

`tests/test_pipelines.py` (9): registry membership, case-insensitive resolve, every scope resolves
exactly (no silent chat-fallback), goals template + carry a no-effect boundary, schedules validate
against the scheduler, discovery requires its flag, content caption-first vs media opt-in. Full suite
**486 pass**.
