# Agent Sync Protocol

> The contract every agent on a repo agrees to. Make Claude, Codex, and Kimi
> operate as one coordinated team instead of independent sessions with
> drifting context. Adapt the names to whatever agents you run.

## 1. Source-of-truth order

Decision precedence, highest first:

1. direct operator instruction
2. repo `docs/DOC-SYSTEM.md`
3. repo product / architecture docs named by that doc system
4. live control-plane docs (`control-plane/ACTIVE_LANE_BOARD.md`, `SESSION_COORDINATION.md`)
5. historical evidence (`control-plane/ENGINEERING_SUPERVISOR.md`)
6. generated retrieval/meta artifacts (`docs/_meta/*`)
7. current codebase
8. prior chat claims

No agent may skip to code if the repo has a doc system and the task touches
product behavior, IA, reporting, pricing, tracking, security, or UX.

## 2. Shared operating contract

Every agent must:

- verify the active repo and its state first (`hostname; whoami; pwd; git status`)
- read the repo's master doc map (`DOC-SYSTEM.md`) before assuming anything
- read the live control-plane doc before editing, when one exists
- read the specific spoke docs for the active lane before editing
- verify real file + git state before trusting earlier claims or chat
- update the doc system when work changes a product, architecture, IA,
  reporting, UI, or process contract
- update the control-plane doc when scope or status changes
- append lane evidence to the supervisor log before calling a lane closed
- treat `docs/_meta/*` as generated aids, not authority on their own

## 3. Division of labor

Default split when multiple agents are active (see `ROLES.md` for detail):

- **Claude** owns the implementation-heavy lane by default.
- **Kimi** owns coordination, cross-repo orchestration, and parallel verification.
- **Codex** runs as verifier, rendered-UI inspector, doc enforcer, or a bounded
  frontend/detail lane.

Default, not a hard wall. All can code; exploit comparative advantage.

## 4. Handoff protocol

When an agent **finishes** a lane, the closure states:

- what docs were read
- what files changed
- what verification passed
- what docs were updated
- what remains / next lane

When an agent **picks up** a lane another touched, it first verifies:

- current git state
- the active lane / control-plane entry
- the supervisor evidence entry
- the relevant source-of-truth docs
- the exact touched files

## 5. Mandatory doc updates

A lane is not closed if it changed a contract but didn't update the contract
doc. Minimum updates by change type:

- product / IA / navigation → `DOC-SYSTEM.md` references + the relevant IA doc
- UI-system change → UI / design-system doc
- reporting / metric semantics → reporting docs
- pricing / gating change → pricing/gating baseline doc
- process / coordination change → control-plane + session-coordination + supervisor
- security / tracking / backend foundation → the specialized architecture doc

## 6. Anti-drift rules

- Don't create a new source-of-truth doc when an existing one should be amended.
- Don't leave a lane's key decision only in chat.
- Don't let the supervisor log become the only place a product law lives — it's
  a lane log, not the full contract.
- Don't use a supervisor log as the live queue when an active lane board exists.
- Don't treat generated `_meta/*` artifacts as authoritative without checking
  the owning docs.
- Don't let code outrun docs on architecture-heavy work.

## 7. Startup rule for every new session

Before coding, read:

- this file
- the repo's `docs/DOC-SYSTEM.md`
- the repo's `control-plane/ACTIVE_LANE_BOARD.md` when present
- the relevant spoke docs for the task

## 8. Execution rule

When an agent has the access needed to finish a lane end to end — deploy, env,
build, test, verify — it does so itself instead of handing shell steps back to
the operator. Hand a step back only on a real blocker: a missing secret it
can't read, a policy/permission wall, an unapproved destructive action, or an
action outside the current environment.
