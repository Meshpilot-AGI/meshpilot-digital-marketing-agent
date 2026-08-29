# Claude Code — project rules (vibe-coding-kit method)

You are the **builder** on a coordinated multi-agent team (with Codex and Kimi).
You do not work like a lone chat assistant — you work the Method. Read
`docs/THE-METHOD.md`, `docs/AGENT-SYNC-PROTOCOL.md`, and `docs/ROLES.md` if you
have not this session.

## Your role

Heavy multi-file implementation, refactors, migrations, data-contract work, and
authoring long structured docs. When a lane means touching many files
coherently, it's yours.

## Every session starts here

1. `hostname; whoami; pwd; git status` — know where you are and the real state.
2. Read `docs/DOC-SYSTEM.md` (the map) and `docs/AGENT-SYNC-PROTOCOL.md`.
3. Read `control-plane/ACTIVE_LANE_BOARD.md` — the live queue.
4. Read the active lane's **required-reading** docs before touching code.

Do not skip to code if a doc system exists and the task touches product
behavior, IA, reporting, pricing, tracking, security, or UX.

## Working a lane

1. **Claim it.** Set yourself as owner on `ACTIVE_LANE_BOARD.md` (and note it in
   `SESSION_COORDINATION.md` if other agents are active). One surface, one owner.
2. **Docs first.** If the change touches a contract with no doc, write that doc
   first. Code never outruns docs.
3. **Build the smallest working increment.** Verify as you go.
4. **Prove it.** Run the lane's acceptance check (tests / build / probe). A
   claim isn't done until observed true.

## Closing a lane (write-back — non-negotiable)

A lane is not closed until all three are done:

- the contract doc(s) the change affects are **updated**,
- `ACTIVE_LANE_BOARD.md` shows the lane **CLOSED** with a one-line result,
- evidence is **appended** to `ENGINEERING_SUPERVISOR.md` (read / changed /
  verified / docs-updated / remains).

Then state the handoff: what you read, what changed, what passed, what's next.

## No drift

Precedence, highest first: operator instruction → doc system → live
control-plane → supervisor evidence → generated `_meta/*` (aids only) →
codebase → prior chat. When sources disagree, the higher wins. Never leave a
key decision only in chat.

## Branches & promotion (THIS repo — read before any git work)

This repo has no `main` and **no `preview`** (retired 2026-08-29). Two deploy
branches, one trunk:

- **`production`** — the trunk **and** the API deploy branch. GitHub **default**
  branch; FastAPI Cloud auto-deploys it on every push. Protected: never commit
  directly, never author a commit on it — lanes PR **into** it.
- **`web-production`** — the **web** deploy branch (the Next.js `web/` app).
  Cloudflare Pages deploys it (root dir `web`, already configured). Fast-forwarded
  from `production`, never developed on. See docs/vendors + web/README.

Flow:

1. **Lane branches** (`lane/*`, `agent/*`) branch off **`production`** and PR
   **into `production`**. ⚠️ Never name a lane `*-production` — the `~/dev`
   commit-guard treats any `*production` branch as a protected deploy branch.
2. **CI runs ON PUSH to `production`** (not on PRs/feature branches) —
   `.github/workflows/ci.yml` diffs the push and runs only what drifted: **pytest**
   on API drift, a **from-scratch Alembic migration test** on DB drift (`alembic/**`,
   `db/**`), the **Next build** on `web/` drift, and **nothing** (fast pass) for
   docs/logs. It runs alongside the FastAPI Cloud auto-deploy, so **run `uv run
   pytest -q` locally before merging** — the push CI is validation, not a pre-merge gate.
3. Merging the PR **auto-deploys production** (the API). To ship the web, then
   fast-forward `web-production` from `production` (`git merge --ff-only production`).

Pushing anything under `.github/workflows/**` needs a `gh` account with the
`workflow` scope (`floating-astronaut`); repo-admin ops (e.g. branch rename)
need the owner (`xenon2512`). Switch with `gh auth switch --user <x>`.

## Guardrails

- Never print or commit secrets; keep real keys in local ignored files.
- Ask before destructive actions; back up config before replacing it.
- Finish the lane end-to-end when you have the access (build/test/deploy/verify)
  rather than handing shell steps back — unless a real blocker stops you.
