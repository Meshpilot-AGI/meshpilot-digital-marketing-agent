# Doc System

> The master map. This file tells every agent which docs exist, what each one
> governs, and which wins when they disagree. Read it first.

A repo running the Method has a small, ordered set of docs. The point isn't
"more documentation" — it's a **known set of contracts** with explicit
precedence, so an agent never guesses where the truth lives.

## Precedence (highest wins)

1. **Direct operator instruction** (this session's chat)
2. **This file** (`DOC-SYSTEM.md`) — the map
3. **Spoke docs** — the architecture / product / contract docs named below
4. **Live control-plane** — `control-plane/ACTIVE_LANE_BOARD.md`, `SESSION_COORDINATION.md`
5. **Historical evidence** — `control-plane/ENGINEERING_SUPERVISOR.md`
6. **Generated/meta** — `docs/_meta/*` (retrieval aids, not law)
7. **Codebase**
8. **Prior chat claims**

## The doc set

| Doc | Governs | Updated when |
|---|---|---|
| `docs/THE-METHOD.md` | the core loop | the workflow itself changes |
| `docs/AGENT-SYNC-PROTOCOL.md` | the multi-agent contract | coordination rules change |
| `docs/ROLES.md` | agent division of labor | the roster or split changes |
| `docs/LANE-LIFECYCLE.md` | how lanes move | the lane process changes |
| `docs/DOC-SYSTEM.md` | this map + precedence | a doc is added/retired or precedence shifts |
| `control-plane/ACTIVE_LANE_BOARD.md` | the live work queue | every lane state change |
| `control-plane/SESSION_COORDINATION.md` | who's active now | sessions start/stop |
| `control-plane/ENGINEERING_SUPERVISOR.md` | evidence log | every lane close |
| `ARCHITECTURE.md` | the agent's internal design — pipeline, publishers, scheduler, DB, brand/env conventions | a component, integration, or the `GE_`-prefixed per-brand env contract changes |
| `docs/plans/2026-08-28-phase1-source-to-publish.md` | the Phase-1 scope: source→publish, no ORM; what's kept vs removed; lane order | the phase scope changes (retire when the phase closes) |

### Add your repo's spoke docs here

As your project grows, register each contract doc in the table above with what
it governs and its update trigger. Typical spokes: `ARCHITECTURE.md`,
`DATA-MODEL.md`, `REPORTING.md`, `PRICING.md`, `SECURITY.md`, `UI-SYSTEM.md`.

## Rules

- **Amend, don't fork.** If a fact belongs in an existing doc, update it there.
  Don't spawn a second source of truth for the same contract.
- **Register new docs here.** A contract doc that isn't in this map is invisible
  to the next agent. Add it the moment it's created.
- **Meta is an aid.** Anything under `docs/_meta/*` (generated indexes,
  embeddings, retrieval helpers) supports lookup but never overrides an owning
  doc.
- **The map is itself a contract.** Changing precedence or the doc set is a
  lane like any other — write it back here.
