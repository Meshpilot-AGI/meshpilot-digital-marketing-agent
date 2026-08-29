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

## Current state / gap (BUFFER-1)
- `publish()` **only supports TikTok today** — it raises `NotImplementedError`
  for other targets, and X is not yet in its platform map.
- BUFFER-1 extends it to **X + LinkedIn**, reconciles the token env name to
  `<PREFIX>_BUFFER_API_KEY`, and validates the GraphQL calls against Buffer's docs.

## Notes
- Buffer is **publish-only** — it cannot read comments/mentions. Engagement (if
  ever added) needs the native platform APIs, not Buffer.
- Each brand's Buffer channels must be connected in the Buffer account that owns
  the API token.
