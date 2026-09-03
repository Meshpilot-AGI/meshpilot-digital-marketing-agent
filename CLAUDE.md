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

This repo has no `main` and **no `preview`** (retired 2026-08-29). One trunk, and
**one** remaining deploy branch:

- **`production`** — the trunk **and** the deploy branch for BOTH the API and the
  gateway. GitHub **default** branch. FastAPI Cloud auto-deploys the API on every
  push; Railway auto-deploys the **gateway** (the Discord↔agent bridge in
  `gateway/`, root dir `gateway`, wait-for-CI on) from this same branch, but only
  when the push touched `gateway/**` (Railway **watch paths** = `gateway/**`), so
  unrelated API pushes don't churn the Discord socket. Because Railway builds the
  same `production` commit, wait-for-CI gates on the `gateway` build check that
  ran on that push. No manual step to ship the gateway — merging to `production`
  is the ship. Protected: never commit directly, never author a commit on it —
  lanes PR **into** it. See gateway/README.md.
- **`web-production`** — the **web** deploy branch (the Next.js `web/` app).
  Cloudflare Pages deploys it (root dir `web`, already configured). Fast-forwarded
  from `production`, never developed on. See docs/vendors + web/README.

> ⚠️ `gateway-production` is **RETIRED** (2026-08-30) — the gateway now deploys
> straight from `production` via Railway watch paths, ending the manual
> fast-forward dance. Do not recreate it.

Flow:

1. **Lane branches** (`lane/*`, `agent/*`) branch off **`production`** and PR
   **into `production`**. ⚠️ Never name a lane `*-production` — the `~/dev`
   commit-guard treats any `*production` branch as a protected deploy branch.
2. **CI is a PR GATE on pull requests into `production`** (and still runs on push to
   `production` as a backstop) — `.github/workflows/ci.yml` diffs the PR against its
   base and runs only what drifted: **pytest** on API drift, a **from-scratch migration
   test** on DB drift (`supabase/migrations/**`, `src/glitch_signal/db/**`), the **Next
   build** on `web/` drift, a **`docker build` + `py_compile`** on `gateway/` drift, and
   **nothing** (fast pass) for docs/logs.

   ⚠️ It used to run ONLY on push to `production`, which validated code that had already
   merged and already begun deploying: a red run told you the trunk was broken, it could
   not stop it. Catching drift before the merge is the point. The push run is kept because
   a PR that was green against a stale base can still break the trunk once other PRs land
   ahead of it — the PR run is the gate, the push run is the truth about `production`.
   Still run `uv run pytest -q` locally; the gate is a backstop, not a substitute.
3. Merging the PR **auto-deploys production** — the API (FastAPI Cloud) and, when
   the change touched `gateway/**`, the gateway (Railway, via watch paths). No
   fast-forward needed for the gateway anymore. To ship the **web**, fast-forward
   `web-production` from `production` (`git merge --ff-only production`) — web is
   still a separate deploy branch.

Pushing anything under `.github/workflows/**` needs a `gh` account with the
`workflow` scope (`floating-astronaut`); repo-admin ops (e.g. branch rename)
need the owner (`xenon2512`). Switch with `gh auth switch --user <x>`.

## Guardrails

- Never print or commit secrets; keep real keys in local ignored files.
- Ask before destructive actions; back up config before replacing it.
- Finish the lane end-to-end when you have the access (build/test/deploy/verify)
  rather than handing shell steps back — unless a real blocker stops you.
