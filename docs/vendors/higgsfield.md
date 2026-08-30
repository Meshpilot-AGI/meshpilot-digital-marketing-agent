# Higgsfield — third media provider (image / video / 3D / audio)

Behind the same `Engine` protocol as MUapi and HeyGen, via the official `higgsfield-client` SDK.
**Plus** an agent **MCP integration** (84 tools, OAuth) — see below.

## MCP integration (agent tool surface — 84 tools, OAuth)  ·  added 2026-08-30

The agent connects to Higgsfield's **remote MCP** at `https://mcp.higgsfield.ai/mcp` and exposes its
**84 tools** to the ReAct loop as `mcp__higgsfield__*` (image/video/audio/**3D** generation, **Marketing
Studio**, **Shorts Studio**, personal clipper, media upload/import, presets, jobs, balance). Far richer
than the 8-model SDK path — this is the full Higgsfield product surface.

- **Auth = OAuth (authorization_code + PKCE)**, same machinery as HeyGen. Discovery:
  `/.well-known/oauth-authorization-server` (authorize `…/oauth2/authorize`, token `…/oauth2/token`,
  register `…/oauth2/register`; scopes `openid email offline_access`, S256). A **public client** was
  dynamically registered (`client_id a5y2lobMyIvL2fnz`); the operator did the web auth, the code was
  exchanged for a bearer + **rotating refresh token**.
- **Token store:** `oauth_tokens` row `provider='higgsfield'` (`client_id`, `token_endpoint`,
  `resource=https://mcp.higgsfield.ai/mcp`). `agent/mcp/oauth.py::get_bearer('higgsfield')` returns a
  valid access token, refreshing rotation-safely (`grant_type=refresh_token`). Stored in the plaintext
  columns initially (like the heygen row); prod re-encrypts on the first refresh.
- **Wiring:** `AGENT_MCP_SERVERS` (global env) carries
  `{"name":"higgsfield","url":"https://mcp.higgsfield.ai/mcp","oauth":"higgsfield"}`.
  `manager_for_brand` resolves the bearer at connect time. Verified live: 84 tools discovered, each
  with an `input_schema` (works with the native-tool-use loop).
- **Re-auth if the refresh ever fails:** re-run the authorization-code+PKCE flow (register a client
  → build `…/oauth2/authorize?…&code_challenge=…` → exchange the code at `…/oauth2/token`) and upsert
  the `oauth_tokens` row. There is also a `device_code` flow at `fnf-device-auth.higgsfield.ai`.

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
