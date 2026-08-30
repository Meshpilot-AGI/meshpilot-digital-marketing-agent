# Vendors — what we can do with each, today

The current, verified capabilities of every integrated vendor. Update this when a capability
lands or a limit is found. Each vendor has its own doc in this folder for setup + detail.

## Media generation

| Vendor | What the agent can do today | How | Notes |
|---|---|---|---|
| **MUapi** ([muapi.md](muapi.md)) | **Images** (logo, ad creative, IG post, UI design, YouTube thumbnail, nano-banana) and **videos** (Seedance 2, Kling, product/UGC/social video) | recipes, engine `muapi`; text also routes here | Unified gateway — one key powers **Seedance 2**, **Kling v2.5**, **Flux 2 Pro**, **Google Imagen 4 Ultra**, **GPT Image 2**, **Nano Banana Pro**. The premium third-party catalog. |
| **HeyGen** ([heygen.md](heygen.md)) | **Avatar / talking-head video**, photo-avatar creation, video translation (175+ langs), voices, templates | the agent's **MCP client** → HeyGen's real MCP (112 tools incl. `video_agent.generate`) | OAuth (not API key). The vendor-sanctioned v3 Video-Agent pipeline. Access token ~10-day; refresh token stashed. |
| **Higgsfield** ([higgsfield.md](higgsfield.md)) | **SDK:** own models (**Soul** text→image, **DoP** video, **Popcorn**). **MCP (new):** 84 tools — image/video/audio/**3D**, **Marketing Studio**, **Shorts Studio**, clipper, media | SDK: engine `higgsfield` / recipe `engine: "higgsfield"`. **MCP:** the agent's MCP client (OAuth) → `mcp__higgsfield__*` in the loop | SDK API key exposes **8** models (Seedance/GPT-Image/Recraft NOT on the API — use MUapi). MCP = OAuth (like HeyGen), `provider='higgsfield'` in `oauth_tokens`. |
| **Native (Pillow)** | **Deterministic image edits** — exact resize, crop/pad to aspect, text overlay, format convert | the `edit_image` loop tool | For the precise edits AI models fumble. Complements generation. |

**Rule of thumb:** Seedance / Kling / Flux / GPT-Image / Imagen → **MUapi**. Avatar/talking-head
video → **HeyGen**. Higgsfield Soul/DoP → **Higgsfield**. Exact edits → **Pillow**.

### Recipes available now

- **MUapi images:** `muapi-logo-creator`, `muapi-ad-creative`, `muapi-instagram-post`,
  `muapi-nano-banana`, `muapi-ui-design`, `muapi-youtube-thumbnail`
- **MUapi video:** `muapi-seedance-2`, `muapi-cinema-director` (Kling), `muapi-product-video-ad-maker`,
  `muapi-social-media-video`, `muapi-ugc-video-factory`
- **Higgsfield:** `higgsfield-soul-image`

## Publishing (⚠️ gated OFF by policy — `agent_publish_enabled=False`)

| Vendor | Targets | Doc |
|---|---|---|
| **Buffer** | TikTok, X, LinkedIn | [buffer.md](buffer.md) |
| **Meta** | Facebook, Instagram (MeshPilot default app + per-brand) | [meta.md](meta.md) |
| **YouTube** | direct upload | — |

## Infrastructure

| Vendor | Role | Doc |
|---|---|---|
| **Anthropic / Claude** | The agent's **brain** — Messages API (loop LLM, `claude-sonnet-5`) | [anthropic.md](anthropic.md) |
| **FastAPI Cloud** | Runtime for the agent (`api.meshpilot.app`) | [fastapi-cloud.md](fastapi-cloud.md) |
| **Cloudflare** | Edge: WAF, TLS, origin-auth, web (Pages) | [cloudflare.md](cloudflare.md) |
| **Supabase** | Postgres (memory, runs) + Storage (per-brand media buckets) | [supabase.md](supabase.md) |
| **Anthropic (Claude)** | The agent **brain** — loop + curator | — |
| **NVIDIA NIM** | Memory **embeddings** (nemotron) | — |
| **MCP servers** | Any tool the agent connects to via its MCP client (HeyGen today) | — |
