# Zernio — the OAuth social surface (rules, and later posting)

`https://zernio.com/api/v1`, 419 endpoints. Holds an **OAuth-authorised** connection to the brand's
Reddit account — the same model as our Buffer publisher, which is why writing to Reddit needs no
credential sharing and no Reddit Data API client of our own.

## Why it exists in the stack

| Need | Vendor | Why |
|---|---|---|
| Discovery / search | redditapis.com | Zernio's `/v1/reddit/search` returned nothing useful for our queries |
| **Subreddit rules, flairs** | **Zernio** | returns rules fully structured |
| Posting, voting, threaded replies | Zernio | OAuth, no credentials shared |

Each vendor is used for what it demonstrably does well, verified live rather than from docs.

## Config

- `ZERNIO_API_KEY` — tenant key (cloud secret + local `.env`).
- `<PREFIX>_ZERNIO_REDDIT_ACCOUNT_ID` — **per brand**, so a second tenant points at its own connected
  account with no code change.

## Rules capture — the permission gate

`GET /accounts/{id}/reddit-subreddits/{sub}/rules` → `{rules: [...], siteRules: [...]}`, each rule
carrying `kind`, `shortName`, `description`, `violationReason`.

Measured live 2026-09-02, and this is why rules are captured **before** any participation:

| room | rules | self_promo | ai_content | verdict |
|---|---|---|---|---|
| r/Forex | 11 | **False** — *"Do not self promote here"* | — | `read_only` |
| r/Daytrading | 7 | **False** | **False** — *"No ChatGPT or AI-Generated Content"* | `read_only` |
| r/propfirm | 0 | unknown | unknown | not permitted |
| r/PropFirmTester | 5 | unknown | unknown | not permitted |

⚠️ **r/Daytrading bans AI-generated posts outright** — a prohibition on what this agent *produces*,
independent of self-promotion. A room can welcome brands and still ban AI text, which is why
`ai_content_allowed` is a separate column from `self_promo_allowed`.

`classify_rules()` can only ever return `False` or `None` — **never `True`**. Silence in a room's
rules is not consent, and a keyword scan must not let a machine grant itself permission to post
publicly under the brand's name. A false `False` costs one room; a false `True` costs the account.

## Account state (2026-09-02)

4 connected accounts, **3 needing reconnect**: `reddit/glitchExecutor` (healthy),
`instagram/glitch_executor`, `tiktok/glitchexec`, `tiktok/namhya.ayurveda` — the last a **different
brand**, so this tenant is already multi-brand.

The Inbox add-on is enabled; `/v1/inbox/comments/{postId}` reads and replies on **arbitrary** threads
(verified against threads we did not author), which is what TARGET-4 will use.
