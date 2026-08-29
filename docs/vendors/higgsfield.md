# Higgsfield — third media provider (image / video / 3D / audio)

Behind the same `Engine` protocol as MUapi and HeyGen, via the official `higgsfield-client` SDK.

## What we can do today

Higgsfield's **own** models only (8 on the API): **Soul** text→image (recipe `higgsfield-soul-image`,
verified live), **DoP** video (`dop/standard`, `dop/turbo`, `dop/lite`, each with a `first-last-frame`
variant), **Soul Cinema**, and **Popcorn Auto**. **Not** a source for Seedance / GPT-Image / Recraft —
those aren't on the Higgsfield API (they're CLI/Marketing-Studio only); use **MUapi** for them. See
[README.md](README.md).

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

## Discovering valid model slugs (important)

The application slug **is the URL path** (the SDK POSTs to `platform.higgsfield.ai/<slug>`), so the
slug must be one your account actually has. The SDK README's example (`bytedance/seedream/v4/...`)
is **not** on this account and 404s as `model_not_found`. List what's real with:

```bash
curl -s https://platform.higgsfield.ai/models \
  -H "Authorization: Key $HIGGSFIELD_API_KEY:$HIGGSFIELD_API_SECRET" -H "User-Agent: higgsfield-client-py"
```

This account's models (namespace `higgsfield-ai/*`): `soul/v2/standard` (Soul 2, text→image),
`soul/cinema`, `popcorn/auto`, and the `dop/*` video models (`dop/standard`, `dop/turbo`,
`dop/lite`, each also a `first-last-frame` variant). Each record carries `operation_type`,
`output_type`, and `base_credits`.

**Verified working:** `higgsfield-ai/soul/v2/standard` produced a real 1536×1536 image through
`HiggsfieldEngine`. Recipe: `recipe_library/higgsfield-soul-image` (bundles the official
`higgsfield-generate` SKILL.md verbatim; `engine: "higgsfield"`, model the Soul 2 slug).
