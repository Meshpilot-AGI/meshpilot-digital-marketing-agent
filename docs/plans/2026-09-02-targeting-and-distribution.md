# TARGETING — give the agent real reach: sensing, surfaces, Reddit, SEO

**Status:** design, pending operator sign-off
**Date:** 2026-09-02
**Operator brief:** *"give the agent real capabilities so he can find what is happening on the
internet, where to hit, and what to hit… prop firm trading challenge [people] are not sitting on
insta reels, we need to penetrate hard to platforms like X and Reddit, work on SEO… try not to
hardcode GE things."*

---

## 1. The gap, measured

The agent today **broadcasts**: matrix → idea → media → captions → publish, on a cron. Nothing in
that loop decides *where* to speak or *whom* to answer. The content matrix picks a **format**; no
component picks a **surface**.

What sensing exists (audited 2026-09-02):

| Capability | Reality |
|---|---|
| `discover_trending` | CaptAPI — **Instagram + TikTok only**. Gated off |
| `web_search` | OpenRouter's web plugin (LLM-grounded, not a search API). Gated off |
| `web_fetch` | Genuinely hardened — SSRF-safe, IP-pinned, 500KB cap. Gated off |
| `orm` pipeline | A shell over those gated tools; its "monitoring" is a **static markdown playbook** |
| SEO | A markdown checklist. **No executing code** |
| Reddit | **No reader, no publisher.** Explicitly excluded from `_PUBLISH_PRIORITY` |
| `platform_profile` | Seeded for x, linkedin, facebook, instagram, tiktok — **no Reddit row** |

So the single sensing organ we have points at the two platforms the operator says this audience is
not on. That is the gap, precisely stated: **the agent cannot currently perceive the places that
matter.**

Assets already paid for and **completely unwired** (zero code references): `APIFY_KEY`,
`BRIGHTDATA_KEY`, and `SCRAPEGRAPH_API_KEY` (added 2026-09-02).

---

## 2. The shape: a targeting loop, not a bigger broadcast

    listen → surface → score → decide → act → measure → learn

The unit of work becomes a **Surface**: a place a conversation happens. A subreddit, an X account or
hashtag, a search query with intent, a forum, a Discord. Surfaces are **discovered and scored, never
hardcoded** — which is simultaneously better targeting and the thing that keeps this brand-neutral.

**The brand declares who it serves; the agent discovers where they are.** GE declares
"traders running funded prop-firm challenges" (already in its positioning row as `visual.audience`);
the agent finds r/propfirm, r/Forex, the X accounts, and the queries. A skincare brand declares its
audience and the same machinery finds entirely different surfaces. No GE constant anywhere.

New per-brand tables (all `brand_id`-keyed, RLS like the rest):

- `surface` — kind (subreddit / x_account / x_hashtag / query / forum), handle, discovered_at,
  status, and **rules metadata** (see §3).
- `surface_score` — measured fit: audience overlap, our historical engagement, cost to participate.
- `signal_item` — an observed thing worth reacting to (a thread, a post, a SERP result), with
  source, url, captured text, and a decay clock.

Scoring is **measured, not asserted** — it reuses the outcome ingestion already built for social
posts. A surface earns its rank; it does not get one from a config file.

---

## 3. Reddit — answering "do we need a third party?"

**Short answer: not for posting. Effectively yes for discovery — but not a Reddit tool.**

### What Reddit's terms actually allow

Verified 2026-09-02 via search (⚠️ Reddit blocks automated fetching of both `reddit.com` and
`support.reddithelp.com`, so this comes from multiple consistent third-party sources, **not**
Reddit's own page — confirm before committing spend):

- **Free tier: 100 queries/minute per OAuth client, non-commercial only** — personal projects, bots,
  mod tools, academic research.
- **Brand and social monitoring is named as commercial** and does not qualify for the free path.
- **Commercial: ~$0.24 per 1,000 calls, from roughly $12,000/month for 50M calls. No smaller plan.**
- **Self-service app registration closed in late 2025** — every new OAuth client needs manual
  approval through a ticket.

### The consequence

Building brand monitoring on Reddit's Data API is either a terms violation or a $12k/month line
item. Neither is acceptable. But scraping Reddit is *also* against their user agreement, so
"just scrape it" is not the clean answer either.

### redditapis.com — tested live, 2026-09-02 ✅

The operator supplied a token for **redditapis.com**, a third-party Reddit proxy. Verified working
against the real service (not read from docs):

| Test | Result |
|---|---|
| `GET /api/reddit/search?q=trailing drawdown&sort=new` | **200** — 5 live posts with subreddit, upvotes, permalink |
| `GET /api/reddit/search/communities?q=prop firm` | **200** — 10 communities **with subscriber counts** |

The community search returned `r/propfirm` (39,227), `r/PropFirmTester` (28,257), `r/PropFirms`,
`r/PropfirmsForum`, `r/PropFirmHunter`, `r/PropFirmExchange`, alongside the broad rooms
(`r/Daytrading` 5.2M, `r/Forex` 547k). The post search surfaced `r/tradeify` and `r/Propfirmstory` —
**subreddits we would not have guessed** — and a direct competitor launching an "AI-powered trading
journal for prop firm traders" in `r/SideProject`.

That is the `surface` discovery primitive and the `signal_item` feed, working, today. Pricing is
**$0.002/read**: ~200 reads/day is roughly **$12/month**, against Reddit's $12,000/month commercial
minimum.

### ⚠️ Use it for READS. Do not route WRITES through it.

The same service offers `POST` comment / vote / DM, and an auth route that takes a **Reddit username
and password** to mint session cookies. Reads and writes have very different risk profiles and
should not be treated as one decision:

- **Reads** fetch public data through a proxy. No credentials of ours, nothing attributed to our
  account. This is the low-risk half and it is the half we need most.
- **Writes** require handing a third party our Reddit password and then acting through an unofficial
  API. That is against Reddit's User Agreement, and the account it puts at risk is precisely the one
  whose standing the whole Reddit strategy depends on. Automated DMs are the fastest ban of all.

**Recommendation: discovery and listening through redditapis.com; posting through Reddit's own OAuth
API or the Devvit app.** This costs nothing extra — we need the official client for posting anyway —
and it keeps the account's activity sanctioned and attributable.

### The rest of the design

**Discovery** via redditapis.com (above), with the SERP (Bright Data) as a second source for
`site:reddit.com` intent queries. **Reading a specific thread** via the existing SSRF-hardened
`web_fetch`. **Posting** via Reddit's official OAuth API — no third party publishes to Reddit, which
is why `_PUBLISH_PRIORITY` excludes it.

### Zernio — tested live 2026-09-02, and it resolves the credential objection ✅

`https://zernio.com/api/v1` (operator-supplied key). A full social-management platform — **419
endpoints** — with **`reddit / glitchExecutor` already connected and active** via OAuth.

Verified against the live API:

| Call | Result |
|---|---|
| `GET /v1/accounts` | **200** — one account: `reddit / glitchExecutor`, `isActive: true` |
| `GET /v1/accounts/{id}/reddit-subreddits/Daytrading/rules` | **200** — full structured rules: `kind`, `shortName`, `description`, `violationReason`, `priority` |
| `GET /v1/accounts/{id}/reddit-subreddits/propfirm/rules` | **200** — `rules: []` plus site rules |
| `GET /v1/reddit/search` | 200 but 0 items for our query (needs `accountId`); redditapis.com is the better search |

Reddit surface it exposes: `reddit-subreddits`, **`/rules`**, `reddit-flairs` (many subs *require* a
post flair), `reddit-vote`, `/v1/reddit/feed`, `/v1/tools/validate/subreddit`, and `POST /v1/posts`
for publishing.

**This resolves the objection I raised against third-party writes.** That objection was specifically
to handing over a Reddit *username and password* (redditapis.com's auth route). Zernio is
**OAuth-connected** — the same model as our existing Buffer integration, which already publishes to
X, LinkedIn and TikTok. No credential sharing, activity attributable to an authorised app.

**`/rules` is the guardrail primitive, and it already exists.** §3 specified "per-subreddit rules are
fetched and stored on the `surface` row before we ever post there." That is now one API call
returning machine-readable rules with `violationReason` — a real gate, not a manual audit.

⚠️ **Unverified: commenting on arbitrary threads.** Zernio's comment endpoints sit under
`/v1/inbox/comments/*`, which in these platforms usually manages engagement on *your own* posts, not
replying into someone else's thread in `r/propfirm`. Since participation-by-comment is the whole
Reddit thesis, **this must be verified before TARGET-4 is scoped.** If it is post-only, commenting
still needs Reddit's own OAuth API.

**Revised split:** discovery via redditapis.com (proven, ~$12/mo) · rules + flairs + posting +
voting via Zernio (OAuth, no credential sharing) · commenting via Zernio if it supports arbitrary
threads, otherwise Reddit's own API.

### ⚠️ The real blocker is ACCOUNT STANDING, not API access (measured 2026-09-02)

The Mac is authenticated to Devvit as **`u/glitchExecutor`** (`~/.devvit/token`, `devvit whoami`).
That token publishes Devvit apps; it is **not** Data API auth and does not let the agent comment in
`r/propfirm`.

More importantly, the account itself was measured via `GET /api/reddit/user/glitchExecutor`:

| Field | Value |
|---|---|
| created | **2026-05-02** (~4 months old) |
| total_karma | **1** |
| comment_karma | **0** |
| link_karma | 1 |
| has_verified_email | true |

**A 4-month-old account with zero comment karma cannot participate.** Most of the target rooms
(`r/Forex`, `r/Daytrading`, the larger prop-firm subs) enforce karma and age minimums via AutoModerator;
posts and comments from an account like this are removed before a human sees them. Automating it
would spend the account's one chance and achieve nothing.

So the sequencing changes. **TARGET-4 (Reddit write) is not blocked on OAuth — it is blocked on
standing**, and standing is earned by genuine participation, which is the one thing that cannot be
shortcut. Concretely:

1. **Do now:** TARGET-1..3 (discovery + listening). Works today, ~$12/month, zero account risk, and
   it produces the thread queue a human can answer.
2. **In parallel, by a human:** build `u/glitchExecutor` standing — or use an existing personal
   account with real history. The agent drafts; a person posts. This is the S0 of Reddit, and it is
   the same "earn it, then automate" shape as the SEO graduation in §4.
3. **Gate TARGET-4 on a measured threshold** — comment karma and account age minimums recorded on
   the brand's config, checked before any automated action. The account-standing check already
   specified below stops being a formality and becomes the actual gate.

This also strengthens the DEVVIT lane: **publishing a useful app does not depend on karma.** It is
the one Reddit surface open to us today.

### The constraint that actually decides success

Reddit removes and bans promotional automation regardless of API compliance. "Penetrate hard" is
precisely the instinct that gets an account shadowbanned in week one. What works is participation
from an account with standing. Encoded as hard gates, not advice:

- **Per-subreddit rules are fetched and stored** on the `surface` row before we ever post there;
  a subreddit whose rules forbid self-promotion is marked `read_only` and never posted to.
- **Self-promo ratio budget** — a configurable share of a brand's Reddit actions may contain a link
  or brand mention (default low). Exceeding it blocks the action, the way the publish gate does.
- **Account standing check** before acting — age and karma thresholds, so a fresh account cannot
  start posting.
- **Cadence cap** per subreddit per day, brand-configurable.
- **The conscience gate already applies** — the same critic that reviews social copy reviews the
  comment before it is submitted.

**Recommendation: start listen + draft, and enable posting per-subreddit** as each one's rules are
recorded and its budget set. That is not a slower version of "participate/post" — it is the only
version that survives contact with Reddit.

---

## 4. SEO — execute the existing program, do not invent one

GE is **not greenfield**. `glitch-trade-app` already carries a documented 10-phase AI-SEO program
(`docs/marketing/ai-seo-program.md`), 11 live posts, and a full marketing doc set (content operating
system, marketing voice, competitor research, SEO audit, intl plan). **Phase 7 is "Content
engine — 2 blog posts/week."** The agent's job is to execute that phase, not to have opinions about
SEO strategy.

### The publishing target is better than expected

Posts are **typed structured data** in `src/data/blog.ts` — a `BlogBlock` union (`p`, `h2`, `h3`,
`stat`, `list`, `table`, `antiPattern`) plus a typed `faq`, rendered by `BlogPost.tsx`, emitting
FAQPage + Quotation JSON-LD. Publishing = appending a typed object, committing, and letting
Cloudflare Pages build.

This matters because **the editorial contract is machine-checkable**, not a matter of taste:

- lede ≤ 60 words and contains the direct answer
- ≥ 1 StatCallout with a primary-source URL
- ≥ 4 H2 sections
- one comparison table OR ordered list
- one anti-pattern callout
- FAQ with ≥ 5 Q&A pairs
- ≥ 3 internal links across clusters
- every quantitative claim cites a primary source

And the program's **verification gates are real commands**: build & typecheck, prerender check,
`pnpm run schemas:validate` (0 errors), `pnpm run links:audit` (0 broken), sitemap audit,
Lighthouse SEO ≥ 95.

### ⚠️ Conflict with the program's own guardrails — operator decision required

`ai-seo-program.md` lists under **Out of scope (explicit)**:

> *AI-generated thin content at scale; every page human-edited.*

The operator has asked for autonomous publishing with no human in the loop. These cannot both hold.
The doc is the operator's own and can be amended — but it should be **amended deliberately**, not
contradicted silently. Also binding, and not in tension: no "guaranteed pass" claims (YMYL-adjacent),
no fake reviews, no scraped competitor copy, no paid links.

### Autonomy graduation — earn it, then take the human out

The operator's instruction: publish with no HITL, *"but only when we prepare him to do that."* So
autonomy is the target and the preparation is part of the plan.

| Stage | Behaviour | Exit criterion |
|---|---|---|
| **S0 — Draft** | Agent writes the post object, opens a PR. Human merges. | 5 consecutive posts pass **every** gate with **zero human edits to the body** |
| **S1 — Gated auto-merge** | Agent opens the PR and merges it **itself** when all gates pass; a failed gate holds it for review. | 10 consecutive auto-merges with no post-publish correction and no factual escalation |
| **S2 — Autonomous** | Agent publishes on cadence. Gates still run and still block. | — |

Gates that run at **every** stage, S2 included — autonomy removes the human, not the checks:

1. Every editorial-contract rule above, checked programmatically on the post object.
2. The program's verification gates (typecheck, schemas, links, sitemap, Lighthouse).
3. **The conscience critic**, already built and already fail-closed.
4. **Grounding**: every firm-rule figure comes from the `firm_rule` table, never the model — the
   guard that already exists for social copy.
5. **Cannibalisation check** — the target keyword must not already be owned by a live post.

"Zero human edits" is measurable: the diff between what the agent proposed and what was merged.
That is the evidence that earns S1, and it is why S0 is not busywork.

---

## 5. Multi-brand, structurally

- Surfaces, keywords, authors, cadences and budgets are **rows**, keyed by `brand_id`.
- The brand declares **audience and domain**; the agent **discovers** surfaces. Nothing about
  Reddit, trading, or prop firms appears in code.
- The blog target is per-brand config: repo, file path, author ids, and the gate commands to run —
  because another brand's site will not be a Vite app with `src/data/blog.ts`.
- Follows the de-branding already done (PR #236): content literals live in the positioning row.

---

## 6. Lanes

| Lane | Scope | Depends on |
|---|---|---|
| **TARGET-1 — sensing** | Wire Bright Data SERP + ScrapeGraphAI behind the existing hardened-egress pattern; `signal_item` table; a `search_surfaces` tool. Ships gated off. | — |
| **TARGET-2 — surfaces** | `surface` + `surface_score` tables; discovery from sensing; scoring from existing outcome ingestion. | TARGET-1 |
| **TARGET-3 — Reddit read** | Subreddit rules capture, thread ingestion via SERP + `web_fetch`, `platform_profile` row for Reddit. | TARGET-2 |
| **TARGET-4 — Reddit write** | Reddit OAuth client (needs operator ticket), publisher, self-promo budget, standing check, cadence cap, conscience gate. | TARGET-3 + approved client |
| **SEO-1 — post generation** | Generate a valid typed post object; contract checks as code; grounded stats. | — |
| **SEO-2 — publish path** | Commit + PR into `glitch-trade-app`; run the program's gates; CF Pages verify. Stage **S0**. | SEO-1 |
| **SEO-3 — autonomy** | Track record measurement, S1 gated auto-merge, then S2. | SEO-2 evidence |

### DEVVIT — a separate lane, and a different kind of bet

`~/dev/reddit-devvit/glitch-executor` exists: a Devvit (Reddit Developer Platform) app, currently the
**unmodified "vibe coding" starter** — `src/server/core/count.ts` is still the Redis counter demo.
Name set to `glitch-executor`, dev subreddit `glitch_executor_dev`, permissions declared
(`SUBMIT_POST`, `SUBMIT_COMMENT`, `SUBSCRIBE_TO_SUBREDDIT`, all `asUser`). No commits, no remote, not
published.

**This does not replace the Reddit lanes.** Devvit builds experiences that run INSIDE Reddit —
interactive posts, games, mod tools — installed **per-subreddit**, and installation is the
subreddit's decision. The `asUser` permissions let the app act for a user *interacting with it*, not
broadcast into subreddits. It gives no cross-Reddit listening. (⚠️ Reddit blocks automated fetching
of `developers.reddit.com`, so this characterisation needs confirming against their docs.)

**But it is the better-shaped bet, and worth its own lane.** It is the one form of Reddit presence
Reddit actively rewards rather than punishes — there is a Developer Funds programme paying for
engagement. Something genuinely useful to this audience (a drawdown calculator as an interactive
post, a "would this trade have breached your firm's rules?" checker, a prop-firm rules quiz) earns
installs and native brand presence with none of the shadowban exposure that automated participation
carries.

The strategic point: **participation is the risky channel; a genuinely useful app is the sanctioned
one.** Note this is a TypeScript app on Reddit's platform — it shares almost no machinery with the
agent, which is why it is a separate lane rather than a sub-lane of TARGETING.

Open questions: is the agent meant to build/feed it, or is it the operator's own project? And which
subreddit is the target — one the operator moderates, or build-it-and-they-install?

**Open decisions for the operator**

1. Amend `ai-seo-program.md`'s "every page human-edited" guardrail, or keep HITL for the blog?
2. Reddit OAuth client — who files the approval ticket, and under what declared use case?
3. Does the agent commit to `glitch-trade-app` directly, or to a fork it PRs from?
4. Confirm reads-only through redditapis.com — or is routing writes through it an accepted risk?
5. DEVVIT: agent-owned or operator-owned, and which subreddit is the target?
