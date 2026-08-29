# Vision — a cloud digital-marketing agent

The north star. Every lane builds toward this; when a design choice is unclear,
this doc and `DOC-SYSTEM.md` win (see precedence there).

## What we're building

A **cloud-hosted digital-marketing agent**, operated **entirely through its
FastAPI service**. The app is the agent's single control surface — endpoints and
an in-process scheduler are how it acts. Nothing runs from a developer's Mac; the
Mac only edits code, commits, and triggers deploys.

Live at **api.meshpilot.app** (FastAPI Cloud, deploy branch `production`).

## Two independent axes

The whole design is **Projects × Capabilities**.

### Projects (tenants / brands)
The agent serves many projects at once. Each project brings **its own** keys and
infrastructure — its own Meta app, Buffer token, Google service account + GCP
project, brand config. There are **no global credentials**: everything resolves
per-project as `<BRAND>_<KEY>` (e.g. `GE_META_APP_ID`, `GE_GOOGLE_DRIVE_SA_JSON`).
Onboarding a new project = a new brand tag + its `<TAG>_*` env set + a brand
config. Glitch Executor (`GE`) is the first project.

### Capabilities (what the agent can do)
Capabilities are modular and added over time without reworking the others.

- **Capability #1 — social-media posting** (this phase): a scheduled item comes
  from a **source** (DB `scheduled_post`, or a Google Sheet + Drive media link)
  and is **published to a platform API** — Buffer (TikTok/X/LinkedIn), Meta Graph
  (Facebook/Instagram), or YouTube (direct). No ORM/engagement in this phase.
- **Future** — SEO, paid ads, email, analytics, reporting, … each a new
  capability module plugged into the same app + project model.

## Principles

1. **Runs on the cloud app only.** All runtime work (scheduler, posting, Drive,
   migrations, LLM calls) executes in the deployed service. Migrations are
   app-driven, not run from a Mac.
2. **Per-project keys, no globals.** Credentials resolve as `<BRAND>_<KEY>`; the
   cloud env is the source of truth for runtime config.
3. **Capabilities are pluggable.** A capability owns its routes, scheduler hooks,
   and config; adding one doesn't disturb the rest.
4. **Live service — evolve safely.** Lane → PR into `preview`; promote
   `preview → production` (CI-gated) to ship. Replace before you remove.

## Source material — the "bible"

The earlier **Mesh Pilot monorepo** is our reference bible: a large body of
already-built, proven work. When we add a capability, we look there **first**,
pull the relevant files, and **adapt** them to this app's workflow (cloud agent,
per-project keys, runs-on-app). It was built as a multi-tenant SaaS product, so
expect changes on pull — we take the proven logic, not the shape. We keep it as
reference only; we never run, ship, or deploy it. (Canonical clone on this Mac:
`~/dev/meshpilot/meshpilot-digital-marketing-stack`.)

## Where the current code stands

Extracted from the earlier Mesh Pilot monorepo (package `glitch_signal`), it is
today a single social-posting agent reading unprefixed global keys. The near-term
lanes move it toward this vision: a project-agnostic per-brand resolver (GE-1),
Buffer/Meta publishers (GE-1/BUFFER-1), and pruning everything outside
capability #1 (PRUNE-1/VENDOR-1). See
`docs/plans/2026-08-28-phase1-source-to-publish.md`.
