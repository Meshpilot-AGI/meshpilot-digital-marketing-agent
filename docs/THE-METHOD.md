# The Method

> One operator, a coordinated team of AI agents, and zero drift. This is the
> loop the whole kit exists to enforce.

```
docs first  →  lanes assigned  →  code  →  write back  →  no drift
```

Most people use AI coding agents as a chat that occasionally edits files. That
works for toys and falls apart on real systems: the agent forgets last week's
decisions, two sessions contradict each other, and the codebase outruns any
record of *why* it looks the way it does. The Method fixes that by making
**documents the source of truth** and **lanes the unit of work** — so multiple
agents (and your future self) stay aligned without a human babysitting context.

## 1. Docs first

Before code on anything non-trivial, the relevant design or contract doc is
written or updated. Code never outruns docs on: product behavior, information
architecture, reporting/metrics, pricing/gating, tracking, security, or UX.

Why: the doc is the durable memory. An agent that reads the doc starts aligned;
an agent that reads only the code re-derives intent (often wrongly) every time.

## 2. Lanes assigned

Work is cut into **bounded lanes** on a live control-plane doc
(`ACTIVE_LANE_BOARD`). A lane is the smallest end-to-end slice that can be
owned, verified, and closed by one agent. Every lane declares:

- **Owner** — which agent holds it
- **Required reading** — the docs to read before touching code
- **Acceptance** — what "done" means, verifiably
- **Write-back duty** — which docs get updated on close

One lane, one owner, at a time. Lanes prevent two agents editing the same
surface and prevent a single agent sprawling across the whole repo.

## 3. Code — by comparative advantage

Agents are not interchangeable. Assign lanes to the agent that's best at them
(see `ROLES.md`). The default split:

- **Claude** — heavy multi-file authoring, refactors, migrations, data-contract work.
- **Codex** — browser/rendered verification, detail/content polish, independent bug-finding, a second pair of eyes on claims.
- **Kimi** — cross-repo orchestration, parallel verification, infra/runtime checks, background tasks.

This is a default, not a wall — all can code. The point is to exploit strengths.

## 4. Write back

A lane is **not closed** until:

- the contract doc that the change affects is updated,
- the lane board reflects the new status,
- evidence (what was read, what changed, what verification passed) is appended
  to the supervisor log.

A change that altered a contract but didn't update the contract doc is an
**open lane**, not a finished one. This step is what makes the method compound
instead of decay.

## 5. No drift

Precedence is explicit and ordered. When sources disagree, the higher one wins:

1. direct operator instruction
2. the doc system (`DOC-SYSTEM.md` and the docs it names)
3. live control-plane docs (`ACTIVE_LANE_BOARD`, `SESSION_COORDINATION`)
4. historical evidence (`ENGINEERING_SUPERVISOR`)
5. generated/meta retrieval artifacts (aids, not law)
6. the current codebase
7. prior chat claims (lowest — memory is unreliable)

No agent skips to code when a doc system exists and the task touches a
contract. No key decision lives only in chat. Generated indexes are never
treated as product law on their own.

## The payoff

- **No re-litigation.** Decisions are written once and read by every agent.
- **Parallelism without collisions.** Lanes + precedence let agents run concurrently.
- **Auditability.** The supervisor log is a tamper-evident record of why the system is what it is.
- **Replaceable sessions.** Any agent can pick up any lane cold by reading the docs — including you, in three months.
