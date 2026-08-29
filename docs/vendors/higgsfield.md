# Higgsfield — third media provider (image / video / 3D / audio)

Behind the same `Engine` protocol as MUapi and HeyGen, via the official `higgsfield-client` SDK.

## Keys (global infra, FastAPI Cloud secrets)

- `HIGGSFIELD_API_KEY` and `HIGGSFIELD_API_SECRET` — the SDK credential is the pair joined as
  `"<key>:<secret>"`. Get them from cloud.higgsfield.ai. Both are set as cloud secrets + local
  `.env`. **Auth verified** (a bad pair returns `Invalid credentials`; the stored pair authenticates).

## Engine (`media/generation/engines/higgsfield.py`)

`HiggsfieldEngine.generate(model, prompt, *, images, params)`:
- `model` → the Higgsfield **application slug** (the SDK's `subscribe(application, arguments)`).
- `prompt` → `arguments.prompt`; `params` merged into `arguments`; `images[0]` → `image_url`.
- `subscribe` submits + polls to completion; the result's asset URL is extracted from
  `images/videos/audios/models` (or a `video`/`image` object).

Select it: `POST /internal/media/generate {recipe, inputs, engine: "higgsfield"}`, or a recipe
that declares `"engine": "higgsfield"`. Resolve in code via `engines.get_engine("higgsfield")`.

## Vendor skills

Official skills: <https://github.com/higgsfield-ai/skills> — `higgsfield-generate`,
`higgsfield-product-photoshoot`, `higgsfield-soul-id`, `higgsfield-brandkit`,
`higgsfield-marketplace-cards`. They wrap the `higgsfield` CLI and cover generic image/video/3D/
audio generation plus Marketing Studio. Model display-name → id mapping lives in the skill's
`references/model-catalog.md`; discover live with `higgsfield model list --json`.

## ⚠️ Open blocker — models not accessible on this account

Auth works, but **every tested application slug returns `model_not_found`** — including the SDK
README's own example (`bytedance/seedream/v4/text-to-image`) and others (`gpt-image-2`,
`recraft_v4_1`, `seedream_v4`, `higgsfield/text-to-image`). This is an **account/model-access
issue on the Higgsfield side**, not our integration. To unblock:

1. In the Higgsfield dashboard (cloud.higgsfield.ai), confirm the account/plan has API model
   access enabled, or
2. Run `higgsfield model list --json` (authenticated) to get a **valid application slug** for this
   account and share it.

Once a working slug is confirmed, add a `recipe_library/higgsfield-*` recipe (SKILL.md provenance +
recipe.json with `"engine": "higgsfield"`) and verify a real generation.
