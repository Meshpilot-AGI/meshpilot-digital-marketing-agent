# Vendor runbook — Meta (Facebook + Instagram Graph API)

Our publisher for Facebook Pages and Instagram. Operating guide; validate
against https://developers.facebook.com/docs/graph-api and the Pages/IG
publishing guides.

## Per-brand credentials (no globals)
All resolve via `config.brand_env` as `<PREFIX>_<KEY>` (GE's prefix is `GE`):
- `GE_META_APP_ID`, `GE_META_APP_SECRET`
- `GE_SYSTEM_USER_TOKEN` — a Meta **system-user** token with publish rights on
  the page/IG account (assigned in Meta Business settings).
- `GE_META_PAGE_ID` = `1120765137796667`, `GE_META_IG_USER_ID` = `17841468194646846`.
- Graph version is a global constant: `meta_graph_api_version` (currently `v21.0`).

## Token flow
System-user token → **page access token** via
`GET /{version}/{page_id}?fields=access_token&access_token=<system_user_token>`.
Use the returned page token as the bearer for publishing. (One system-user can
publish for many brands.)

## Facebook Page publishing (`platforms/facebook.py` — verified live)
`_GRAPH = https://graph.facebook.com`
- **Text / link:** `POST /{page_id}/feed` — form `{message, [link], access_token}`
- **Image:** `POST /{page_id}/photos` — form `{url, caption, access_token}`
- **Video:** `POST /{page_id}/videos` — form `{file_url, description, access_token}`
  (Meta fetches the media server-side from the URL.)
- Response id → `post_id` or `id`; permalink `https://www.facebook.com/{post_id}`.
- ✅ Verified: real post `1120765137796667_122116654083395430`.

## Instagram publishing (two-step container — not yet wired here)
1. `POST /{ig_user_id}/media` — image `{image_url, caption}`; reel
   `{media_type:"REELS", video_url, caption}` → returns a creation_id.
2. Poll `GET /{creation_id}?fields=status_code` until `FINISHED`.
3. `POST /{ig_user_id}/media_publish` `{creation_id}` → media_id.
4. `GET /{media_id}?fields=permalink`.

## Trigger (verification)
```bash
curl -X POST https://api.meshpilot.app/internal/facebook/test-post \
  -H "x-jobs-token: $GE_JOBS_AUTH_TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"..."}'
```

## Gotchas
- The **system-user token must have the page assigned** with publish tasks, or
  the page-token exchange returns nothing / the post 403s.
- Common Graph error codes: 190 (token invalid/expired → refresh), 200/10
  (missing scope/permission).
- Long-lived tokens expire (~60 days); plan a refresh path before relying on it.
