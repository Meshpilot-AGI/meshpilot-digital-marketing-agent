# Roles — who does what, and why

Agents are not interchangeable. The Method gets its speed from assigning each
lane to the agent with the comparative advantage for it. These are defaults you
tune to your own roster; the principle (assign by strength, not by who's free)
is what matters.

## Claude Code — the builder

**Strengths:** deep coding throughput, multi-file backend/frontend
implementation, migrations, route + data-contract work, large refactors once a
lane is clear, authoring long structured docs.

**Default lane:** the implementation-heavy lane. When a lane means touching many
files coherently or holding a lot of context, it's Claude's.

## Codex — the verifier & finisher

**Strengths:** browser-led and rendered-page verification, frontend/content/
detail polish, independent bug-finding, confirming a claim with a second pair
of eyes, doc enforcement.

**Default lane:** verification and bounded polish. After a build lands, Codex
confirms it renders/behaves as claimed and tightens the details. If Codex
implements, it prefers narrow lanes with clear acceptance.

## Kimi — the orchestrator

**Strengths:** coordination and cross-repo orchestration, parallel verification,
running many commands at once, infra/runtime checks, longer verification loops,
background task management.

**Default lane:** coordination, cross-repo work, parallel verification, and
infra. When work spans repos or needs many things checked at once, it's Kimi's.

## The split in one line

> **Claude builds. Codex verifies and finishes. Kimi orchestrates and checks
> in parallel.**

## Rules of the split

- It's a **default, not a wall.** All three can code. Assign by advantage, then
  by availability.
- **One lane, one owner.** Two agents never hold the same surface at once.
- **The owner closes the lane** — including the write-back. You don't hand a
  half-closed lane to another agent without a clean handoff (see
  `AGENT-SYNC-PROTOCOL.md` §4).
- **Escalate by strength.** A lane stuck on the wrong agent should be re-cut and
  reassigned, not forced.

## Mapping to your roster

Running a different set (Cursor, Aider, Gemini, OpenClaw…)? Keep the three
*functions* — **builder / verifier / orchestrator** — and map your agents onto
them. The Method depends on the functions being covered, not on these specific
tools.
