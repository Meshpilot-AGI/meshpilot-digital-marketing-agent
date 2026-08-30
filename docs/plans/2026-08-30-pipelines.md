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

- **Manual (operator, live now):** `POST /internal/agent/pipeline/{name}` (jobs-auth), body `{brand?}`
  → resolve → check `requires` (409 if a switch is off) → `_run_agent_bg(run_id, brand, goal,
  max_steps, scope)`. Returns `{run_id, pipeline, scope}`; poll `GET /internal/agent/run/{id}`.
- **Scheduled (inert):** `POST /internal/agent/pipeline/{name}/schedule` (jobs-auth) seeds a
  `payload_kind=agentTurn` cron job (owner `pipeline:<brand>`, carrying goal+scope) at the pipeline's
  cadence. The scheduler fires it **only when `agent_cron_enabled`** is on (409 while off).

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
