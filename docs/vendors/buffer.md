# Vendor runbook — Buffer

Our publisher for **TikTok, X, and LinkedIn** (Meta handles FB/IG; YouTube is
direct). Operating guide; validate against Buffer's current API docs
(https://buffer.com/developers) — Buffer's API has changed over time, so treat
endpoint specifics as needing confirmation in **BUFFER-1**.

## Per-brand credentials (no globals)
- `GE_BUFFER_API_KEY` — the Bearer token (already set in the cloud env).
- ⚠️ The code today reads the **global** `BUFFER_API_TOKEN` (`buffer.py`).
  BUFFER-1 routes it through `brand_env` so it reads `<PREFIX>_BUFFER_API_KEY`.

## How the code uses it (`platforms/buffer.py`)
- API base: **`https://api.buffer.com`** (Buffer's GraphQL API).
- Auth header: `Authorization: Bearer <token>`.
- **Async publish:** `publish()` returns a `webhook_pending:<buffer_post_id>`
  sentinel; the post is finalized later via Buffer's webhook. `poll_status_for_post()`
  checks status.
- **Signed media URL:** Buffer fetches the media from our app's
  `GET /media/fetch?token=<signed>` route (the file URL is passed untouched, which
  avoids the re-mux audio issues other vendors caused).
- Platform keys: `buffer_tiktok`, `buffer_linkedin`, `buffer_instagram`,
  `buffer_youtube` (brand config).

## State (BUFFER-1 done)
- Token is per-brand via `brand_env("BUFFER_API_KEY")` → `GE_BUFFER_API_KEY` (no global).
- `create_post(brand, service, text, media_url, mode)` posts to any connected
  service with **dynamic channel resolution** (`account → organization → channels`,
  matched by service; x/twitter aliased). No per-platform config needed.
- GE connected channels (verified live): TikTok `glitchexec`, X `GlitchExecutor`,
  LinkedIn `glitch-executor` (org `69e4c24477ef919b5a3837d5`). A real X post was
  queued via `/internal/buffer/test-post`.
- Endpoints: `/internal/buffer/channels`, `/internal/buffer/test-post` (x-jobs-token).
- ⚠️ The legacy video `publish()` still reads channel/org id from brand config;
  `create_post` (the new path) resolves them dynamically.

## Notes
- Buffer is **publish-only** — it cannot read comments/mentions. Engagement (if
  ever added) needs the native platform APIs, not Buffer.
- Each brand's Buffer channels must be connected in the Buffer account that owns
  the API token.
