# Contributing to MeshPilot

Thanks for your interest. MeshPilot is **open-core** (AGPL-3.0): the agent is open
source and self-hostable; a managed hosted platform is the separate paid product.
Contributions to the agent are welcome.

## Ground rules

- **By contributing, you agree your contribution is licensed under AGPL-3.0-or-later**
  (the project license). Keep it your own work or properly attributed.
- **No secrets, ever.** Real keys/tokens live only in the environment, never in code,
  tests, or fixtures. A `gitleaks` scan runs against the tree — dummy/test values must
  be allowlisted in `.gitleaks.toml`, not real ones.
- **Content the agent produces must pass the content policy** (no AI footprints — no
  em/en-dashes, no filler-ese). The same bar applies to docs and comments you write.

## Workflow (doc-driven, lane-based)

1. **Open a lane** — a branch off `production` (`git switch -c lane/<name>`). Never
   commit to `production` directly. This repo has no `main`; `production` is the trunk.
2. **Read the docs first** if your change touches product behavior, tracking, security,
   or the data model — see the doc index in the README (`docs/DOC-SYSTEM.md` →
   `control-plane/ACTIVE_LANE_BOARD.md` → the relevant spoke doc).
3. **Small, tested increments.** Tests are part of the change, not a follow-up:
   ```bash
   uv sync --extra dev
   uv run pytest -q
   ```
4. **PR into `production`.** Keep the diff focused; explain what you changed, what you
   verified, and what remains.

## Running it locally

You need Python ≥ 3.11 + `uv`, a Supabase Postgres (for memory/runs), and the vendor
keys you want to exercise (Anthropic for the brain; MUapi/HeyGen/Higgsfield for media;
NVIDIA NIM for embeddings). Copy `.env.example` to `.env` and fill what you need — the
app degrades gracefully when an optional capability's key is absent. Publishing is
**off by default** (`AGENT_PUBLISH_ENABLED` unset); the agent plans and generates but
does not post until you deliberately enable it.

## Reporting issues

Bugs, security findings, and feature ideas: open a GitHub issue. For anything
security-sensitive, please note it clearly so it can be triaged before public detail.
