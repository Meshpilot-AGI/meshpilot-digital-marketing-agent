# Plan — Media Generation Capability (MEDIA-1)

**Date:** 2026-08-29 · **Status:** DONE — MEDIA-1 (4 starter recipes, real video live) + MEDIA-2 (LLM composer via muapi + 7 more recipes = **11 total**, real LLM-authored image live; 2 clipping recipes deferred to a future video-edit lane). See ENGINEERING_SUPERVISOR MEDIA-1 / MEDIA-2.
**Depends on:** GE-1 (brand_env), the publish capabilities (Meta/Buffer/YouTube — closed)
**Related:** DB-OPT (this answers its open scope question — see §7)

## Decision (operator, 2026-08-29)

- **All image / video / caption generation goes through MUapi first**, with
  **other vendors (fal, HeyGen) pluggable later**.
- **Runtime execution = a deterministic Python engine** (no LLM-drives-shell in
  the hot path).
- **The muapi recipe skills are used AT RUNTIME** when generating content. The 13
  `muapi-*` skills already installed on the Mac (`~/dev/agent/skills/muapi-*`) are
  the source of truth — but the deployed cloud app has no access to the Mac, so
  they must be **bundled into the repo** and executed by our runner.

## The model in one line

A **brief** (from the existing LLM content pipeline) selects a **recipe** and
fills its inputs; a **deterministic runner** executes the recipe's phases against
a **pluggable engine** (MUapi now), polls to completion, and returns an **Asset**
(hosted URL) that the publisher (Buffer/Meta/YouTube) then posts.

```
content pipeline (LLM: author brief, pick recipe, fill {{inputs}})
        │  Brief{ brand_id, recipe_slug, inputs{...} }
        ▼
recipe registry ──loads──► recipes/media/<slug>/SKILL.md   (bundled, parsed)
        ▼
recipe runner (deterministic): fill placeholders → resolve model→endpoint
        │  → engine.generate(phase) → poll → chain phase output → next phase
        ▼
engine layer (pluggable):  muapi (first)  ·  fal / heygen (later)
        ▼
Asset{ url, kind, engine, prompt, metadata }  → publisher
```

## What a recipe is (already the right shape)

Each `muapi-*/SKILL.md` is semi-structured and parseable:
- **frontmatter** `description`
- **Inputs** table — name · type · required · default · description
- **Steps** — phases, each a numbered step: `muapi <command>` + `model=<id>` +
  a `{{placeholder}}` prompt template + aspect ratio + reference-image source
- **Trigger Keywords** — for selection
- **Notes for the Executing Agent** — the human/LLM-interactive bits (ask-to-upload,
  present-for-approval) that our **autonomous** runner **skips or gates**.

Runtime fidelity: we **bundle the SKILL.md verbatim and parse it at runtime**, so
the recipes stay faithful to the installed library (no hand-port drift). Filling
inputs from a brief is the existing LLM step (upstream); execution stays
deterministic and unit-testable.

## Components (new, under `src/glitch_signal/media/generation/`)

1. **`engines/` (pluggable, adapted from the bible `meshpilot_creative/engines/`)**
   - `base.py` — a minimal `Engine` Protocol: `generate(endpoint, params) -> str(url)`
     (submit+poll internally), `upload(path) -> url`. Plus `EngineError`.
   - `muapi.py` — httpx async client; `IMAGE_ENDPOINTS`/`VIDEO_ENDPOINTS` model→endpoint
     maps; submit→poll→wait; `MUAPI_API_KEY`/`MUAPI_API_BASE` (global infra key — see §6).
     Lifted near-drop-in from bible `engines/muapi.py` (self-contained httpx).
   - *(later)* `fal.py`, `heygen.py` — same Protocol, drop-in. Not in MEDIA-1.

2. **`recipes/` (the bundled library + loader)**
   - `recipes/media/<slug>/SKILL.md` — verbatim copies of the 13 `muapi-*` skills.
   - `loader.py` — parses a SKILL.md → `Recipe{ slug, description, inputs:[InputSpec],
     phases:[Phase{command, model, prompt_template, aspect, ref_source}], triggers }`.
   - `registry.py` — loads all recipes at import; lookup by slug + trigger keywords.

3. **`spec.py`** — `Brief`/`Asset` dataclasses (from bible `spec.py`, pure, drop-in).

4. **`runner.py`** — `async def run_recipe(recipe, inputs, brand_id) -> Asset`:
   fill `{{placeholders}}`, resolve each phase's `model` → engine endpoint, execute
   phases in order (Phase B's reference = Phase A's output URL), poll each, return
   the final Asset. No LLM, no network in tests (engine injectable).

5. **caption** — reuse the existing LLM path (`influencer/caption.py` + `llm.py`),
   brand voice per-brand. Captions are text, not a muapi recipe.

6. **selection** — extend the existing `media/content_router.py`: brief.kind +
   triggers → recipe slug (deterministic map + explicit override). The LLM may also
   name the slug directly.

## Verification (evidence before claims — runs on the app)

- Unit: SKILL.md parser (all 13 parse), placeholder fill, phase chaining, endpoint
  resolution — all with an injected fake engine (no network).
- Live: `POST /internal/media/generate` (x-jobs-token) → run e.g.
  `muapi-product-video-ad-maker` for GE with a sample product image → returns a
  real hosted video URL. Same pattern as the FB/Buffer test endpoints.

## §6 — Keys

`MUAPI_API_KEY` stays a **global infra key** (one muapi account; not a brand
identity like a Meta Page). Per BRANDS.md, infra keys are global. **Brand style**
(colors, voice, reference images) is per-brand and flows through the **brief**, not
a key. If we ever want per-brand muapi billing, `brand_env("MUAPI_API_KEY")` is the
switch — deferred.

## §7 — Resolves DB-OPT's open scope question

Generation **is** in scope → the `signal / scout_checkpoint / video_asset /
video_job` tables **stay**. DB-OPT prunes only the old-SaaS ORM/engagement tables,
not the generation ones.

## Reuse map (from the bible, per read of `meshpilot_creative/`)

- **Near-drop-in:** `spec.py`, `engines/muapi.py`, `engines/muapi_cli.py` (fix the
  hardcoded `MUAPI_CLI_BIN` path → env), `router.py`, `engines/fal.py` (later).
- **Adapt (strip `meshpilot_platform`/Postgres coupling):** `generate.py` dispatch
  shape, `usage.py` (cost metering — later), `brand_assets.py` (per-brand B-roll).
- **Reimplement interface only:** recipe layer — we build a **SKILL.md loader**
  instead of the bible's `recipes.py` (better: uses the actual installed skills);
  `persona_adapter.py` is a worked example, not reusable.

## Sequencing

MEDIA-1 is largely **independent** of PRUNE-1/VENDOR-1 (new subsystem under
`media/generation/`). VENDOR-1 later re-points publishing onto Buffer/Meta/YouTube;
MEDIA-1 feeds those. Old `media/` modules (`image_gen.py` references a `muapi.*` that
was never extracted; `carousel_gen.py`; `html_render.py` for text cards) are
reconciled during build: keep `html_render` (deterministic text cards), supersede
`image_gen`/`prompt_recipes` with the new engine+recipe layer, prune the rest under
PRUNE-1.

## Out of scope (MEDIA-1)

fal/HeyGen engines, cost metering (`usage.py`), per-brand muapi keys, wiring into the
live scheduler (that's a VENDOR-1 follow-on), the human-approval gate.
