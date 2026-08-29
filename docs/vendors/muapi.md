# Vendor runbook — MUapi (muapi.ai)

Our **media-generation** vendor — images and video (and audio) across 100+ models
(Flux, Seedance, Wan, nano-banana, gpt-image, Veo, Kling…). The first engine behind
the pluggable media capability (MEDIA-1); fal / HeyGen slot in behind the same
`Engine` protocol later. Operating guide — validate against https://muapi.ai/docs.

## Key (global infra — not brand-scoped)

- `MUAPI_API_KEY` — one muapi account for all brands. **Global**, like the DB /
  Logfire / Sentry keys (see `docs/BRANDS.md`). Brand *style* (palette, voice,
  reference images) flows through the **brief**, not the key.
- `MUAPI_API_BASE` — optional; defaults to `https://api.muapi.ai/api/v1`.
- ⚠️ Setting it in FastAPI Cloud: `env set` **won't overwrite** an existing var
  (silent no-op → blank value → `MUAPI_API_KEY not set` at runtime). Always
  **delete then set fresh**, then redeploy. See `docs/vendors/fastapi-cloud.md`.

## HTTP contract (what `engines/muapi.py` uses)

Deterministic submit → poll (prod-proven in the bible):
```
submit : POST {base}/{model}                 header x-api-key   -> { request_id }
poll   : GET  {base}/predictions/{id}/result                    -> { status, outputs: [url] }
```
- The recipe's `model` **is the endpoint slug** (e.g. `flux-2-pro-edit`,
  `wan2.5-image-to-video-fast`, `nano-banana-pro-edit`, `seedance-2-vip-image-to-video`,
  `gpt-image-2-text-to-image`). We POST straight to `{base}/{model}` — no curated
  model→endpoint map to maintain; new models work with no code change.
- Payload: `{prompt, image_url?, images_list?, **params}`. Reference images go as
  BOTH `image_url` (first) and `images_list` (all) — what multi-image edit models want.
- `params` are the recipe's declared knobs, passed through untouched:
  `aspect_ratio`, `duration`, `generate_audio`, `cfg_scale`, `negative_prompt`,
  `num_images`, `resolution`, `output_format`.
- Terminal statuses: done = {completed, succeeded, success, done}; failed =
  {failed, error, cancelled}. Poll every 3s; per-phase timeout 360s.

## How we drive it — recipes, not raw calls

The runtime never freeform-calls muapi. It runs a **recipe** (`src/glitch_signal/
media/generation/recipe_library/<slug>/`): a `SKILL.md` (bundled verbatim from the
installed `muapi-*` skills — provenance) + a structured `recipe.json` (the execution
plan). The deterministic `runner` fills `{{placeholders}}`, executes each phase
(a phase's output becomes the next phase's input), and returns a hosted `Asset` URL.

- **Template recipes** (e.g. `muapi-product-video-ad-maker`) run with **no LLM**.
- **Prompt-authored recipes** (instagram/youtube/ugc) mark phases `prompt_mode: llm`
  / `op: llm` and need the injected composer — wired in **MEDIA-2**.

## Endpoints (auth: `x-jobs-token` = `GE_JOBS_AUTH_TOKEN`)

```
GET  /internal/media/recipes                 # list bundled recipes (+ needs_composer)
POST /internal/media/generate                # {recipe, inputs{...}, brand?} -> {url, kind, engine}
```

## Verify

```bash
curl -s -H "x-jobs-token: $TOK" https://api.meshpilot.app/internal/media/recipes
curl -s -X POST https://api.meshpilot.app/internal/media/generate \
  -H "x-jobs-token: $TOK" -H 'content-type: application/json' \
  -d '{"recipe":"muapi-product-video-ad-maker","inputs":{"product_image":"<url>"}}'
```
Proven 2026-08-29: real video at `cdn.muapi.ai/outputs/generated/8382032…mp4` (~108s).

## Notes

- The `muapi` CLI (PyPI `muapi-cli`) exists too (`muapi image|video|run …`, MCP mode);
  we use the **HTTP path** in-process for determinism, not the subprocess. A CLI
  transport can be added behind the same engine later if ever needed.
- Adding a recipe = drop its `SKILL.md` + author a `recipe.json`; the parity test
  (`tests/test_media_generation.py`) asserts every manifest model traces to its SKILL.md.
