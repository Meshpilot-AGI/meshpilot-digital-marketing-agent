# Phase 1 — Source → Publish (no ORM)

**Decided 2026-08-28 (operator).** Reduce the extracted agent to one job:
take a scheduled item from a **source** and **post it to a platform API**.
No comment engagement, no ORM, no reputation management in this phase.

## Target shape

```
SOURCE                         PUBLISH
  DB (scheduled_post)   ─┐
                         ├─► scheduler dispatch ─► publisher ─► Buffer   (TikTok / X / LinkedIn)
  Google Sheet + Drive ─┘                                    ─► Meta     (Facebook / Instagram)
  (sheet_posting)                                            ─► YouTube  (direct)
```

- **Sources (keep):** the DB queue (`scheduler/queue.py` → `scheduled_post`) and
  the Google-Sheet-driven path (`sheet_posting/` + Drive media links).
- **Publishers (keep):** `platforms/buffer.py` (TikTok/X/LinkedIn),
  Meta Graph API (`influencer/meta_publish.py` + a new Facebook publisher),
  `platforms/youtube.py` (direct).
- **Per-brand config:** `GE_`-prefixed env keys (e.g. `GE_META_APP_ID`,
  `GE_BUFFER_API_KEY`) resolved for the active brand (`glitch_executor`).

## Remove

- **ORM / engagement:** `comments/` (sweeper, strategic, x_sweeper), `orm/`,
  and the ORM ticks in `scheduler/queue.py`. Engagement is out of scope.
- **Upload-Post:** `platforms/upload_post.py`, `webhooks/upload_post.py`,
  `analytics/upload_post.py`, `onboarding/upload_post.py`, and all `upload_post_*`
  routing in `publisher.py` / `_PUBLISH_PRIORITY`.
- **Redundant direct integrations** (Buffer/Meta cover them):
  `platforms/tiktok.py`, `platforms/twitter.py`, `platforms/instagram.py`,
  `integrations/linkedin.py`, `integrations/x.py`; plus the orphaned TikTok
  OAuth (`oauth/tiktok.py`, the `/oauth/tiktok/*` routes) once `tiktok.py` is gone.
- **Zernio:** already removed.

## Lanes (dependency order)

- **GE-1** — per-brand `GE_` resolver + Meta Graph **Facebook publisher** (FB/IG).
  Prerequisite for re-pointing FB/IG off Upload-Post. Meta creds already staged.
- **BUFFER-1** — extend `buffer.py` beyond TikTok to **X + LinkedIn**.
  Prerequisite for re-pointing X/LinkedIn off Upload-Post. Reconcile
  `BUFFER_API_TOKEN` vs the cloud-set `GE_BUFFER_API_KEY`.
- **PRUNE-1** — remove ORM/engagement (safe deletion; independent of GE-1/BUFFER-1).
- **VENDOR-1** — remove Upload-Post + redundant direct integrations; re-point the
  DB scheduler and `sheet_posting` onto Buffer/Meta/YouTube. **After** GE-1 + BUFFER-1
  (can't re-point until Buffer/Meta can do the job) and PRUNE-1.

## Guardrails

- The service is **live** (api.meshpilot.app). Work lane-by-lane, verify each,
  never one big cut. Removal that could change the posting path lands only after
  the replacement publisher is proven.
- Follow the branch model: lane → PR into `preview`; promote `preview → production`
  (CI-gated) to ship.
