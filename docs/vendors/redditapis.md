# redditapis.com — Reddit discovery (reads)

The agent's Reddit **sensing** layer (TARGET-1). Public post + community search, pay-per-call, no
Reddit account credentials involved.

## Why this and not Reddit's own API

Reddit's Data API free tier is **non-commercial only** and names brand/social monitoring as
commercial; the commercial tier runs ~**$0.24/1k calls from ~$12,000/month**, with no smaller plan,
and self-service client registration closed in late 2025. This costs **$0.002 per read** — roughly
**$12/month** at 200 reads/day.

⚠️ Sourced from consistent third-party reporting, **not** Reddit's own page: Reddit blocks automated
fetching of both `reddit.com` and `support.reddithelp.com`. Confirm before committing larger spend.

## What we use

`REDDITAPIS_TOKEN` (cloud secret + local `.env`), `Authorization: Bearer`. Base
`https://api.redditapis.com`. Client: `agent/discovery/reddit.py`.

| Call | Purpose |
|---|---|
| `GET /api/reddit/search` | live threads matching a query → `discover_conversations` |
| `GET /api/reddit/search/communities` | the ROOMS an audience gathers in, **with subscriber counts** → `discover_communities` |
| `GET /api/reddit/user/{name}` | account standing (karma, age) — the gate on automated posting |

## ⚠️ Reads only — deliberately

The same vendor offers `POST` comment / vote / DM, and an auth route that takes a Reddit **username
and password** to mint session cookies. We do not use those. Writing to Reddit goes through
**Zernio's OAuth connection** (`docs/vendors/zernio.md`), so no third party ever holds account
credentials and activity stays attributable to an authorised app.

## ⚠️ `sort=relevance` is the only sort that targets

Measured on one query, 2026-09-02:

| sort | What came back |
|---|---|
| `relevance` | "Stop giving your money to prop firms" (93↑), "What's the WORST rule a futures prop firm can have?" — on-topic |
| `top` | r/apolloapp, r/nosleep, r/news — **all-time global top posts**, query nearly ignored |
| `new` | r/CrusaderKings, an anime sub — recency beats meaning |

The client defaults to `relevance`. Use `new` **only** with a `subreddit`, where the room supplies
the relevance and recency is the point.

## Gating

Both tools sit in `policy.DISCOVERY_TOOLS`, so they inherit the existing kill-switch and per-run cap:

- `AGENT_DISCOVERY_ENABLED` (default **false**) — no external pull until flipped.
- `AGENT_MAX_DISCOVERY_PER_RUN` (default 5) — bounds spend per loop run.

Observations persist to `signal_item` (migration `20260902090000`), upserted on
`(brand_id, source, external_id)` so re-observing refreshes traction instead of duplicating.
