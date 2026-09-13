# OFF-PAGE — the SEO program after the blog: syndicate, listen, draft, earn the right to post

Status: DESIGN, approved in conversation 2026-09-12 (approach A, ordering S1→S4). Brand-neutral;
GE is the first tenant. Operator decisions recorded here: **the ladder** (agent drafts → operator
approves → graduates on evidence) for Reddit; **HARO stays draft-only, permanently**; the operator
posts Reddit drafts by hand while the account earns standing; **approvals live in Discord**.

Reading before this: `docs/plans/2026-09-02-targeting-and-distribution.md` (the loop, Reddit terms,
Zernio, standing), `docs/vendors/seo.md` (the on-page ladder this mirrors),
`~/dev/glitch-executor/glitch-trade-app/docs/marketing/ai-seo-program.md` § Phase 10 (the
operator's own tier list — this executes it, it does not invent one).

## 1. What "off-page" means here, and what it does not

On-page is done: seven posts merged under the SEO ladder, GE at S1. Off-page is everything that
earns the site attention it did not publish itself. Of the operator's seven tiers, four are
automation problems; three are not (podcasts, calculator embeds, Wikipedia) and stay human.

| Lever | Surface it acts on | Risk to the brand | Mode |
|---|---|---|---|
| **S1 Syndicate** | our own X / LinkedIn | none — our accounts | autonomous from day one |
| **S2 Listen** | Reddit threads, web mentions, AI answers | none — read-only | autonomous from day one |
| **S3 Reply** | other people's Reddit threads | the account's standing | **ladder**: draft → operator posts → graduates |
| **S4 HARO** | journalists' queries, under a legal byline | reputation, legal | **draft-only, permanently** |

Hard limits carried over unchanged from the program: no paid links, PBNs or exchanges; no
"guaranteed pass" or outcome claims; firm figures only from `firm_rule`; no third party ever
holds Reddit credentials (reads via redditapis, writes only via Zernio OAuth); every subreddit's
own rules are a gate, not advice.

## 2. Shape: one spine, four levers

Everything flows through the same four records, so there is one approval UX, one graduation
ladder and one digest — a lever is a plug-in, not a subsystem.

```
signal   what we noticed        (signal_item — exists, TARGET-1)
  → candidate   what we could say, where   (offpage_candidate — new)
    → approval  what the operator said     (Discord reaction, read back into the candidate row)
      → outcome what happened              (offpage_outcome — new: posted / karma / link / citation)
```

A lever supplies: a **finder** (signals → candidates), a **drafter** (candidate → text under the
lever's contract), and an **actor** (what "post" means for it). The spine supplies: storage,
the Discord approval loop, the ladder, the digest, and the cron capabilities.

## 3. Data model (Supabase, new)

```sql
create table offpage_candidate (
  id            uuid primary key default gen_random_uuid(),
  brand_id      text not null,
  lever         text not null,            -- syndicate | reply | haro
  surface_kind  text not null,            -- x | linkedin | youtube | subreddit | haro
  surface       text not null,            -- handle / r/name / query source
  target_url    text,                     -- the thread / query being answered; null for syndicate
  source_ref    text,                     -- seo_publication.slug or signal_item.id — provenance
  score         numeric,                  -- finder's ranking (see §5)
  draft         text not null,
  draft_meta    jsonb not null default '{}', -- flair, subreddit rules hash, grounding rule keys
  status        text not null default 'drafted',
     -- drafted | offered | approved | edited | rejected | posted_by_operator | posted_by_agent
     -- | expired | skipped
  discord_msg_id text,                    -- the #approvals message; null for autonomous levers
  offered_at    timestamptz, decided_at timestamptz, expires_at timestamptz,
  created_at    timestamptz not null default now(),
  unique (brand_id, lever, target_url, source_ref)   -- one candidate per thread/post per lever
);

create table offpage_outcome (
  candidate_id  uuid references offpage_candidate(id),
  brand_id      text not null,
  lever         text not null,
  posted_url    text,                     -- comment permalink / tweet url / null
  measured_at   timestamptz not null default now(),
  metrics       jsonb not null default '{}', -- {"score":12,"replies":3} / {"impressions":..}
  primary key (candidate_id, measured_at)
);

create table offpage_standing (            -- the evidence the ladder reads; one row per check
  brand_id      text not null,
  surface_kind  text not null,            -- subreddit (account-level) for now
  checked_at    timestamptz not null default now(),
  account_age_days int, comment_karma int, link_karma int,
  approvals_30d int, rejections_30d int, posted_by_operator_30d int,
  primary key (brand_id, surface_kind, checked_at)
);
```

Existing tables reused, not duplicated: `signal_item` (sensing), `surface` (+ `surface_score`,
rules), `seo_publication` (the syndication source), `agent_secret` (Discord bot token already
present as `DISCORD_BOT_TOKEN` in the cloud env).

## 4. The levers

### S1 — Syndicate (autonomous; ships first)
**Finder:** `seo_publication` rows with `merged_at` set and no `syndicate` candidate yet. Also a
backfill run over the 7 already-merged posts, throttled to one per day so the feeds don't dump.
**Drafter:** per platform, from the post's title + first paragraph + one concrete fact the post
proves (a firm rule it cites, pulled by `firms.rules_for_names`) — never a summary of the whole
post. X ≤ 240 chars + link; LinkedIn ≤ 700 chars, link in body. YouTube is deliberately out:
the Data API has no community-post write, and a synthetic video per blog post is thin content by the
program's own definition. Same generator checks as the blog: no unsupported figures, no outcome
promises, brand terms word-bounded.
**Actor:** the existing `publish.fan_out` / Buffer publishers, staggered — X on day 0, LinkedIn
day 1 — so one post earns two days of signal. One syndication set per
merged post, ever (the unique key).
**Measure:** `social_post_metric` already ingests Buffer metrics → `offpage_outcome`.

### S2 — Listen (autonomous, read-only; ships with S3)
Three feeds into `signal_item`, each a cron capability:
- **Reddit threads** — `discovery.reddit.search_posts` over the brand's `audience_queries` (config)
  × the top-N `surface` rows of kind `subreddit`; window 48h; dedupe on permalink. ~$0.002/read.
- **Web mentions** — Bright Data SERP (`BRIGHTDATA_KEY` held, unwired; wire behind the existing
  hardened-egress pattern, same allowlist/timeout/size caps as `web_fetch`): brand + product names,
  weekly. Classifies each hit **linked / unlinked / competitor-list**. Unlinked mentions and
  "best X tools" lists that omit us become **outreach drafts** (an email the operator sends —
  draft-only like HARO, because it carries the legal entity's name).
- **AI citations** — the program's ~30 tracked prompts, run weekly against the providers the router
  already has (OpenRouter/Azure), answers scanned for the site's domain → citation rate per prompt,
  per provider. This is the program's Phase 6 tracker, executed inside the agent instead of ported
  as a script.

### S3 — Reply (the ladder)
**Finder:** Reddit signals scored (§5); top `reply.daily_candidates` (config, default 3) per day.
Excludes: threads older than 48h, threads where we already commented or were mentioned, subreddits
whose synced rules (`surfaces.sync_rules`, Zernio) forbid self-promotion or require karma we do not
have, subreddits with a live candidate in the last `reply.min_gap_hours` (default 72) — the
self-promo ratio budget from the targeting design, made concrete.
**Drafter:** answers the question in the thread; may mention GE **only** if the thread asks for a
tool, and then once, plainly, with the disclosure the subreddit rules require. Grounding: firm
figures only via `firms.rules_for_distribution`; every claim checkable by the existing
`unverified_product_claims` / `unsupported_generalisations` checks reused from `seo.generate`;
a `dead_sources` check on any link. Flair chosen from the subreddit's flair list when one is
required. The draft records the rules hash it was written against, so a rules change invalidates it.
**Actor — three stages, derived from evidence, no setter** (mirrors `seo.track.standing`):
- **R0 (now):** candidate → `#approvals` card (thread title, subreddit, why it scored, the draft,
  flair, rules excerpt). Operator reacts: ✅ *I'll post this* → status `approved`; ✏️ *posted with
  edits* (operator posts their own version) → `edited`; ❌ → `rejected`; 📤 *posted* → operator
  pastes the permalink as a reply, or the agent finds it by scanning the thread for the account's
  comment within 24h → `posted_by_operator` + outcome row. Cards expire after 36h (threads go
  stale) → `expired`; expiry is not a rejection.
- **R1:** the agent posts via Zernio itself, **after** a `#approvals` card sat for 2h with no ❌
  (a veto window, not an approval). Entry: `comment_karma ≥ 100 AND account_age_days ≥ 180 AND
  approvals_30d + posted_by_operator_30d ≥ 20 AND rejections_30d ≤ 2`, all from `offpage_standing`
  rows the `reply_standing` capability writes daily from `discovery.reddit.user`.
- **R2:** no veto window; card is informational. Entry: 30 consecutive R1 posts with no ❌ and no
  moderator removal (detected by re-fetching the comment 24h later — a removed comment is a hard
  failure that drops the stage to R0 and alerts).
Cadence caps at every stage: ≤ `reply.daily_candidates` drafts/day, ≤ 1 post per subreddit per 72h,
≤ 1 GE mention per 5 comments (the ratio budget), measured over `offpage_candidate`.

### S4 — HARO (draft-only, permanently)
**Finder:** Featured.com / HARO query feeds (email → the inbound Resend route the domain already
has, or the RSS where offered), keyword-matched to the brand's `expertise` list (config).
**Drafter:** a pitch under the legal byline the config names (`haro.byline`), ≤ 200 words, facts
only from published posts and `firm_rule`, with the post URL as the source.
**Actor:** `#approvals` card with the query, deadline and draft. No stage above R0 exists for this
lever by construction — the capability has no Zernio/email actor.

## 5. Scoring a Reddit thread (S3 finder)

```
score = surface_fit × recency × question × novelty
  surface_fit  = surface_score.fit for the subreddit (exists; provisional until measured)
  recency      = 1.0 (<6h) · 0.7 (<24h) · 0.3 (<48h) · 0 (older)
  question     = 1.0 if the title/body asks for a tool, comparison, rule, or how-to; 0.4 otherwise
  novelty      = 0 if we commented / were named; 0.5 if a competitor is already recommended; else 1
```
Stated so it can be argued with: recency and novelty are gates disguised as factors; the only
tunable opinion is `question`, and it exists because answering a question is the one behaviour
every subreddit's rules permit.

## 6. The Discord approval loop

- Channel: the existing `#approvals` (1543461330277761118). Post via the bot token (REST); **no
  second gateway session** — the Railway bridge holds the only one a bot token allows.
- Card = one message per candidate: header line `[reply · r/propfirm · score 0.81 · expires in 36h]`,
  the thread link, the draft in a code block, and the reaction legend. The message id is stored on
  the candidate.
- Reading decisions: the `offpage_decide` capability polls `GET /channels/{ch}/messages/{id}/
  reactions/{emoji}` for every `offered` candidate every 15 min, honours only reactions from user
  ids in `approvers` (config; the operator's id), applies the first decisive reaction, sets
  `decided_at`. A 📤 reaction with no permalink triggers the thread scan described in §4.
- Every state change is a line in `#agent-activity`; expiries and stage changes go to `#alerts`.

## 7. The digest (weekly, `#alerts`)

One message: syndication sets published; threads found / offered / approved / posted / expired and
the current stage with its entry-condition deltas ("karma 41/100, age 133/180 d"); new mentions
(linked / unlinked, with the outreach drafts offered); backlinks gained/lost since last week (from
the SERP mention delta — no paid backlink API); AI-citation rate per provider vs last week. Written
so the operator can read it in one screen and act on nothing unless a number moved.

## 8. Capabilities and schedules (all `REQUIRED_CAPABILITIES`-gated, brand-scoped)

| capability | schedule | requires |
|---|---|---|
| `offpage_syndicate` | daily 09:00 ET | `publish` |
| `offpage_listen_reddit` | every 6h | — |
| `offpage_listen_web` | weekly Mon | — |
| `offpage_listen_citations` | weekly Mon | — |
| `offpage_reply_draft` | daily 08:00 ET | — |
| `offpage_decide` | every 15 min | — |
| `offpage_reply_post` | every 15 min | `publish` + stage ≥ R1 (derived; refuses otherwise) |
| `offpage_reply_standing` | daily | — |
| `offpage_haro_draft` | every 6h | — |
| `offpage_digest` | weekly Mon 08:00 ET | — |

Each cycle records a row (the `seo_cycle` pattern) so the heartbeat can alert on silence.

## 9. Brand config additions (schema-extended, all optional)

```json
"offpage": {
  "audience_queries": ["prop firm drawdown rule", "ftmo daily loss", "..."],
  "expertise": ["prop-firm rules", "drawdown maths", "MetaApi", "backtesting"],
  "reply": {"daily_candidates": 3, "min_gap_hours": 72, "mention_ratio": 5},
  "haro": {"byline": "Tejas Karan Agrawal, founder, Glitch Executor"},
  "approvers": ["<discord user id>"],
  "tracked_prompts": ["best prop firm tracker", "..."]
}
```
Nothing in code names a subreddit, a firm or an industry.

## 10. Failure handling

Same posture as the blog ladder: **refuse loudly, never post uncertainly.** No rules for a
subreddit → skip the thread and say so. A draft that fails a generator check → not offered,
reason in the row. Discord unreachable → candidates stay `drafted`, retried next tick; nothing is
lost because the card is written after the row. Zernio post fails → `offpage_outcome` records the
error; the candidate is not retried (a duplicate comment is worse than a missed one). A comment
removed by moderators → stage drops to R0, alert. Budget: every LLM call goes through the existing
per-brand daily cap.

## 11. Testing

Unit, with the deps-dict pattern `drive_to_social` uses (every external call injectable):
scoring table (§5) as a parametrised test; ladder stage derivation from synthetic `offpage_standing`
+ candidate histories, including the removal-drops-to-R0 rule; the approval reader honours only
`approvers` and the first decisive reaction; expiry; cadence caps; syndication uniqueness and
staggering; every generator check reused from `seo.generate` runs on reply and HARO drafts.
Live, before arming each lever: one syndication of an already-merged post; one `#approvals` card
whose reactions round-trip into the row; `reply_standing` writes the real karma numbers.

## 12. Order of work (each step live before the next starts)

1. **OFFPAGE-1 Syndicate** — tables, spine store, S1 finder/drafter/actor, backfill, cron. Visible
   result: the 7 live posts on X/LinkedIn over a week.
2. **OFFPAGE-2 Listen + Reply-draft (R0)** — Reddit feed, scoring, drafter with reuse of the blog
   checks, Discord cards, decide loop, standing capability. Visible result: ≤3 drafts/day in
   `#approvals`, operator posts by hand.
3. **OFFPAGE-3 Mentions + citations + digest** — Bright Data wiring, citation runner, outreach
   drafts, weekly digest.
4. **OFFPAGE-4 HARO draft** — feed intake, matcher, pitch drafter.
5. **OFFPAGE-5 R1/R2** — Zernio actor + veto window + removal check. Code lands with OFFPAGE-2 but
   cannot fire until `offpage_standing` says so; this step is the live verification when it does.

Out of scope: podcasts, calculator embeds, Wikipedia, any paid placement, Devvit (separate lane).
