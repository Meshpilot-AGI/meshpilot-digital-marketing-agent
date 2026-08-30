# SCOPE — per-run / per-pipeline tool scoping for the agent loop

**Status:** SHIPPED 2026-08-30 (verified live — chat scope offered 6/15 tools)  ·  **Owner:** Claude

## Why

The ReAct loop offers **every** tool on **every** run (`tools.tool_defs() + server_tool_defs() +
mcp.tool_defs()`). So a global kill-switch (`agent_discovery_enabled`, …) makes a capability usable
*everywhere* the moment it's on — and our agent is a 24/7 autonomous operator, so "on" means "it may
use this unprompted, in any run." We want a capability to be usable **only within the pipeline/job
that calls for it**, not by free-roaming autonomy. This adds a **scope** to each run that bounds the
agent's toolset to the active job — turning "remember not to flip the flag" into "the agent
structurally can't use a tool outside its pipeline."

Two independent layers (defense in depth): **scope = which tools are OFFERED for this job**;
**policy = whether a tool is ALLOWED to run at all** (kill-switches, per-run caps, MCP allowlist).
A tool runs only if it is **in-scope AND policy-allowed**.

## Design

### 1. Scope registry — `agent/loop/scopes.py`
**Capabilities** (named groups of tool names / MCP prefixes):
| capability | tools |
|---|---|
| `memory` | recall, remember |
| `knowledge` | list_playbooks, read_playbook, read_brand_doc |
| `quality` | polish_copy |
| `media` | list_recipes, generate_media, edit_image |
| `discovery` | discover_trending |
| `web` | web_search, web_fetch (server tools) |
| `schedule` | schedule |
| `publish` | publish, send_email |
| `mcp:heygen` | `mcp__heygen__*` |
| `mcp:higgsfield` | `mcp__higgsfield__*` |

**Named scopes** (a scope = a set of capabilities):
| scope | capabilities | for |
|---|---|---|
| **`chat`** (default) | memory, knowledge, quality | Discord free-form / bare runs — safe read+plan, **no external effects, no paid tools** |
| `discovery` | memory, knowledge, discovery, web | a scheduled discovery run (trending → ideate → stop) |
| `content` | memory, knowledge, quality, media, mcp:higgsfield | content-creation pipeline |
| `orm` | memory, knowledge, quality, web | reputation/monitoring |
| `full` | all capabilities | trusted operator-triggered run |

Resolver: `tools_for_scope(name) -> Scope` with `allows(tool_name) -> bool` (exact names + `mcp__*`
prefix match). Unknown scope → falls back to `chat` (fail-safe, logged).

### 2. Runner filtering — `runner.run(..., scope: str = "chat")`
```python
scope = scopes.resolve(scope_name)                 # unknown → chat
all_defs = tools.tool_defs() + tools.server_tool_defs() + (mcp.tool_defs() if mcp else [])
tool_defs = [d for d in all_defs if scope.allows(d["name"])]   # <-- the scope filter
```
The agent only ever SEES the scoped tools. The **policy gate is unchanged** and still runs on every
`tool_use` (kill-switches + caps). Seed `recall` / episode `remember` are internal loop calls
(not agent-chosen), so they keep working regardless of scope.

### 3. Plumbing scope into a run
- `runner.run(brand, goal, *, scope="chat", …)`.
- `/internal/agent/run` body gains **`scope`** (default `config.agent_default_scope`, default `chat`);
  `_run_agent_bg` threads it through.
- Self-cron `agentTurn` payload gains **`scope`**; `cron/service.py::_run_agent_turn` reads it.
- The Discord gateway keeps the default (`chat`) unless a channel is mapped to a scope (future).

### 4. Anti-escalation (important)
The agent can create its OWN cron jobs via the `schedule` tool. Left open, it could self-schedule a
`full`/`publish` job and escalate. **Rule:** a self-scheduled `agentTurn`'s scope is **clamped to a
subset of the current run's scope** (or an env allowlist `AGENT_SELF_SCHEDULE_SCOPES`). Operator-created
cron jobs (via `/internal/cron/*`) may set any scope. So agent-chosen scope ⊆ current scope; operator
scope = unrestricted.

### 5. Config
- `agent_default_scope` (default `chat`) — scope for un-specified runs.
- Optional later: env override of the registry (`AGENT_SCOPES` JSON) + per-brand `<BRAND>_SCOPES`.

## How this changes the enablement story
A new capability now rolls out as: **build tool (policy-gated off) → build/define the pipeline (a
scheduled job or an operator run) with the right `scope` → keep the kill-switch off until that
pipeline is ready → enable.** The scope ensures the tool is only reachable from its pipeline; the
kill-switch remains the final safety gate.

## Verification
- Unit: `scopes.resolve` + `allows` (names + mcp prefix; unknown → chat); runner filters `tool_defs`
  to the scope (a `chat` run offers no discovery/media/publish/mcp; a `content` run offers media +
  mcp:higgsfield); default scope = chat; self-schedule scope clamped to ⊆ current.
- **Live**: a real `run(scope="chat")` — the model is offered only memory/knowledge/quality tools
  (inspect the payload `tools`); a `run(scope="discovery")` offers discover_trending (still policy-
  denied while disabled → proves both layers).

## Risks / mitigations
- **Over-restriction breaks a flow** — `full` scope + operator override cover trusted runs; scopes are
  data, easy to adjust.
- **Scope vs policy confusion** — documented as two layers; both must pass; policy stays the safety net.
- **Back-compat** — default `chat` could hide tools a current caller expected. The only live agent
  path today is Discord chat (which *should* be `chat`); operator/cron callers pass an explicit scope.

## Out of scope (later)
Per-channel Discord scope mapping; env/per-brand scope registry override; a UI to define pipelines.

## Write-back
`docs/vendors/anthropic.md` note (loop tool scoping), `control-plane/ACTIVE_LANE_BOARD.md`,
`control-plane/ENGINEERING_SUPERVISOR.md`.
