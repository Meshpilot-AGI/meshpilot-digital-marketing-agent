# Vendor runbook — CaptAPI (discovery: trending social content)

CaptAPI (`captapi.com`) is a purpose-built social-data REST API — trending reels/feed/hashtags/
songs/creators for **Instagram + TikTok** — powering the agent's **discovery** ability. Chosen over
general scraping infra (Apify actors, Bright Data proxies) because it gives **direct trending
endpoints as clean JSON**, no scraping fragility. Base `https://api.captapi.com`, Bearer auth,
credit-metered with a free 24h cache.

## How the agent uses it (DISCOVERY, 2026-08-30)

- **Client:** `src/glitch_signal/agent/discovery/captapi.py` — `trending(platform, kind, country?,
  cache=True)` → the endpoint's `data` payload. Auth `Authorization: Bearer $CAPTAPI_KEY`
  (`capt_live_…`). `cache=true` (default) = free 24h cache hit (conserves credits).
- **Loop tool:** `discover_trending(platform, kind?, country?)` — returns the top ~10 trending items
  compacted to the signals the agent needs (caption, engagement, hashtags, author, url; noisy
  video/thumbnail-expiry fields dropped).
- **⚠️ Gated OFF by default.** The policy denies `discover_trending` unless **`agent_discovery_enabled`**
  is true (mirrors the email/publish kill-switches) — so the ability ships **inert, no external
  pulls**, until deliberately flipped. Per-run cap `agent_max_discovery_per_run` (default 5) bounds
  credit spend once on.

## Endpoints wired

| platform | kind | path |
|---|---|---|
| instagram | reels (default) | `/v1/instagram/trending-reels` |
| tiktok | feed (default) | `/v1/tiktok/trending-feed` |
| tiktok | hashtags | `/v1/tiktok/popular-hashtags` |
| tiktok | songs | `/v1/tiktok/popular-songs` |
| tiktok | creators | `/v1/tiktok/popular-creators` |

## Config

- `CAPTAPI_KEY` — the Bearer key (FastAPI Cloud env secret + local `.env`).
- `AGENT_DISCOVERY_ENABLED` (default `false`) — flip to `true` (+ redeploy) to let the agent pull.
- `AGENT_MAX_DISCOVERY_PER_RUN` (default `5`) — per-loop-run pull cap.

## To enable discovery

Set `AGENT_DISCOVERY_ENABLED=true` on FastAPI Cloud env + redeploy. Endpoint verified live during
build (US IG trending-reels → real reels with caption/engagement/hashtags). Credit-metering of pulls
is a possible follow-up (INC-style), like the vendor cost meter.

## Other providers on hand (not yet wired)

`APIFY_KEY` (apify.com — general scraping actors) and `BRIGHTDATA_KEY` (brightdata.com — enterprise
proxy/scraping + datasets) are held in local `.env` for deeper/custom scrapes CaptAPI doesn't cover;
no code uses them yet.
