---
name: meta-ads
description: Meta (Facebook/Instagram) paid-ads handbook covering account/campaign audit checklists, cold-pixel and new-account scaling strategy, and Meta Marketing API operational best practices (rate limits, checkpoint avoidance, idempotency). Use when auditing a Meta ad account, launching or scaling a new account with a cold pixel, or building/debugging automation against the Meta Marketing API.
---

# Meta Ads Handbook

## When to Use This Skill

Use this skill when working on a brand's Meta (Facebook/Instagram) advertising, or building
automation that touches the Meta Marketing API:

- Auditing an existing Meta ad account (structure, creative, pixel/CAPI, audiences)
- Launching a brand-new ad account or a cold pixel and needing a scaling strategy
- Diagnosing a performance drop, high CPM, or "Learning Limited" ad sets
- Building or debugging server-side automation against the Meta Marketing API
- Avoiding or recovering from a security checkpoint, rate-limit throttle, or account
  disablement risk

---

## Part 1 — Account & Campaign Audit Checklist

A condensed, ID-keyed catalog of what to check on any Meta ad account. Each check carries a
**severity** (critical/high/medium/low), and a rough **weight** within its category. Category
weights: **Pixel/CAPI 30% · Creative 30% · Structure 20% · Audience 20%.** Substitute the brand's
own targets (target CPA, target ROAS, breakeven ROAS) wherever a check references "target."

Checks marked "(ecom)" apply to D2C/ecommerce/subscription brands; "(lead-gen)" to
local-service/B2B/financial lead-gen brands; unmarked checks are universal.

### Pixel / CAPI Health (30%)

- **Primary conversion event firing** — CRITICAL. Fires on every conversion with value + currency
  set. Fail: zero fires in 7 days while spend is live. Every other check is invalidated if this
  fails. Fix via the platform's native pixel connector; dedupe on `event_id`.
- **CAPI (server-side) active** — CRITICAL. Server-side event count should be ≥0.7× the pixel-side
  count for the primary event. Post-iOS-14.5, attribution loses 30-40% without CAPI. Enable in the
  native connector and verify counts in Events Manager.
- **Event deduplication** — pixel + CAPI should share `event_id` on ≥90% of events (70-90% =
  warning, <70% = fail). Fix: one canonical emitter per event, remove duplicate tag-manager tags.
- **Event Match Quality (EMQ)** for the primary event — target ≥8.0 in Events Manager (6.0-7.9 =
  warning, <6.0 = fail). Pass hashed email, phone, and `external_id` on every conversion event to
  climb the score. Meta favors event *volume* over match quality above ~8 — don't sacrifice volume
  chasing 9+.
- **(ecom) Full funnel events present** — ViewContent + AddToCart + InitiateCheckout + Purchase all
  firing in 7 days. Missing AddToCart starves creative-stage learning.
- **(ecom/marketplace) UTM coverage on web orders** — ≥60% of web orders should carry a
  `utm_source`. Set an account-level URL template in Ads Manager → Settings; propagation takes
  4-8 hours.
- **Domain verification** — verified in Business Manager, with an Aggregated Event Measurement
  (AEM) priority list configured for iOS.
- **(ecom) Currency consistency** — pixel currency must match store currency on every event, or
  ROAS misreports.
- **(lead-gen) Lead-form pixel/CAPI firing on submit** — CRITICAL for lead businesses. No Lead
  event = no algorithm signal = wasted spend.
- **(lead-gen) Offline-conversion CRM upload** — the CRM should push qualified-lead/booked-appointment/
  closed-won events back to Meta via the offline-conversions API, ≤24h lag. Raw Lead volume alone
  is junk-inflated; closing the loop with real outcome data is what makes cost-per-*qualified*-lead
  meaningful.
- **(ecom) Catalog feed health** — <5% errors, all top-50-by-spend SKUs in stock, prices matching
  the site. Feed errors hide products from Advantage+ Shopping and Dynamic Product Ads.
- **Ad-copy compliance scan** — zero active ads should contain personal-attributes phrasing
  ("is your dog struggling with…") or, in regulated verticals, disease-claim language
  (treats/cures/prevents/heals/reverses). These patterns run a meaningfully elevated rejection
  and account-ban risk.

### Creative (30%)

- **Format diversity** — ≥3 active formats (image/video/carousel) account-wide. Since Meta's
  Andromeda algorithm update (late 2025), near-identical creatives get penalized in retrieval.
- **Creatives per active ad set** — ≥5 is healthy, ≤2 is a fail.
- **Creative diversity floor (brand-wide)** — ≥15 distinct active creative concepts across the
  brand. Andromeda rewards genuine variety, not duplicate variants of one hero; ≤9 concepts means
  the algorithm collapses to a single hero and fatigue becomes inevitable.
- **Creative fatigue (CTR drop)** — pass if 7-day CTR is ≥0.7× the ad's lifetime-peak CTR
  (0.5-0.7× = warning, <0.5× = fail). Action on fail is **refresh, not pause** — pausing loses
  accumulated learning; a fresh variant of the same concept preserves it.
- **Frequency cap, prospecting** — 7-day frequency should stay under 3.0 (3.0-5.0 = warning,
  >5.0 = fail).
- **Frequency cap, retargeting** — under 8.0 (8.0-12.0 = warning, >12.0 = fail). Tighten further
  by funnel stage if you can classify ad sets as cold/warm/hot: cold ≤3.0, warm ≤6.0, hot ≤8.0.
- **Andromeda similarity** — max pairwise text/creative similarity across active creatives should
  stay under 0.55 (0.55-0.70 = warning, >0.70 = fail — retrieval-suppression risk). Ten genuinely
  distinct concepts consistently outperform 100 minor variants of one.
- **Ad text length** — primary text <125 characters, headline <40, or it gets truncated on mobile
  feed.
- **UGC / testimonial creative tested** (stronger signal for ecom/consumer/creator/app) — D2C and
  consumer accounts consistently see UGC/testimonial creative outperform studio-produced creative
  at 2×+ CTR; less pronounced for B2B/lead-gen.
- **Creative refresh cadence** — at least one new creative every 14 days on each top-spend
  campaign (14-28 days = warning, >28 days = fail).
- **(lead-gen) Qualifying questions on lead forms** — 2-4 qualifying questions, ≥1 short-answer.
  Zero qualifiers means the CRM fills with junk and raw cost-per-lead becomes meaningless (quality
  can drop 60-80%).

### Account Structure (20%)

- **Campaign consolidation** — ≤5 active campaigns carrying meaningful spend is healthy; >15 means
  fragmented learning. Meta's own post-2024 guidance is that 1-3 well-fed campaigns beats many
  thin ones.
- **"Learning Limited" share** — <30% of active ad sets in Learning Limited is healthy (30-50% =
  warning, >50% = fail). Fix by raising budgets to ≥5× the target-metric value per ad set, or
  consolidating ad sets.
- **Budget per ad set** — every active ad set should carry a daily budget ≥5× the target-metric
  value (2-5× = warning, <2× = fail — it will never exit the learning phase).
- **Testing surface (algorithmic vs. manual mix)** — keep at least one manual ABO test campaign
  for ad-level R&D even when running mostly algorithmic (Advantage+/ASC) campaigns; 100% either
  way is a warning/fail.
- **Campaign carried by one ad** — no active campaign should draw ≥70% of its revenue from a
  single ad (70-85% = warning, >85% = fail). When it happens: isolate the winner into its own ad
  set and scale it, pause the rest.
- **Naming conventions** — ≥80% of campaigns and ad sets should follow a documented naming schema
  (whatever the brand's own convention is) so analytics and dedup logic stay reliable; <50%
  conformance is a fail. Never rename by touching object IDs — preserve history.
- **CBO pause-pitfall awareness** — pausing one ad set inside a Campaign Budget Optimization
  campaign redistributes budget to the others, it does not save spend. Any planning/automation
  logic should call this out explicitly rather than assume a pause reduces total spend.
- **(ecom) Advantage+ Shopping (ASC) coverage** — ≥60% of ecommerce spend should run through ASC
  once the brand has a catalog; ASC is Meta's default prospecting surface for catalog-based ecom
  post-Andromeda. A reasonable target split is 60-80% ASC / 20-40% manual ABO for testing;
  0% ASC leaves the algorithm's strongest surface unused, but 100% ASC leaves no testing surface.
- **(marketplace) Per-side conversion separation** — supply-side and demand-side campaigns need
  separate conversion events, each reporting its own cost-per-first-transaction. One campaign
  optimizing on combined volume can't be read or managed per side.
- **(B2B/marketplace) Long attribution window enabled** — 7-day click + 1-day view or longer, with
  conversion lookback ≥30 days for high-consideration verticals. A 1-day-click-only default misses
  conversions that land weeks after the original ad click.

### Audience & Targeting (20%)

- **Custom audiences exist** — ≥3 active (web visitors, customer list, engagement). Build the
  highest-value list for the business model: purchasers (ecom), closed-won (B2B), qualified leads
  (service), subscribers (creator).
- **Lookalike audiences tested** — ≥2 seed sizes (e.g. 1% + 3-5%).
- **Exclusion hygiene** — existing customers/closed-won/qualified-leads excluded from prospecting;
  converters excluded from cold ad sets. No exclusions at all is a fail.
- **Audience overlap** — <30% overlap between any two active prospecting ad sets (via the
  platform's audience-overlap tool); >50% means the ad sets are cannibalizing each other's spend.
- **Advantage+ Audience tested** against manual targeting on at least one campaign — Meta reports
  ~7% lower cost-per-result for Advantage+ Audience vs. manual targeting/lookalikes on average,
  and is actively deprecating manual interest-based targeting.
- **Geo targeting hygiene** — every active campaign's geo should align with its destination URL
  (no campaign targeting a market whose currency/site the destination doesn't serve).
- **(B2B/lead-gen) CRM-stage audiences synced** — live sync to custom audiences keyed on lifecycle
  stage (Lead/MQL/SQL/Opportunity/Closed-Won), refreshed daily if possible. Without it, MQL and
  SQL retargeting messages can't differ even though they should.
- **Destination-URL performance** — every destination URL with meaningful 14-day spend should have
  at least one attributed conversion; a dead destination (broken checkout, redirect loop,
  out-of-stock landing page, geofencing mismatch) is a silent budget sink.
- **Audience freshness** — custom audiences refreshed ≤30 days, lookalikes regenerated ≤60 days,
  lookalike seed size ≥1,000. Never delete a superseded lookalike — mark it superseded and let the
  new one take over.

### Critical checks (always surface, even on pass)

Primary conversion event firing · CAPI active · Creative fatigue · Learning Limited share ·
Campaign-carried-by-one-ad · Lead-form pixel/CAPI firing (lead-gen brands) · account-level
disablement-risk score (see §3.5 below).

### Health-Score Formula

```
sub_score = sum(check_score × weight × W_sev) / sum(100 × weight × W_sev)   # per category
health    = 0.30·pixel_capi + 0.30·creative + 0.20·structure + 0.20·audience
```
`check_score ∈ {0, 50, 100}` for fail/warning/pass; `W_sev = {critical 5.0, high 3.0, medium 1.5,
low 0.5}`. Grades: 90-100 A · 80-89 B · 70-79 C · 60-69 D · <60 F. A critical FAIL caps that
category's sub-score at 50.

---

## Part 2 — Cold-Pixel & New-Account Scaling Strategy

Strategy for launching a brand-new ad account with a cold pixel (near-zero counted conversions),
running at modest daily budget (roughly $30-100/day), largely on autopilot with a continuous
creative supply. This is deliberately conservative — it trades a slower ramp for materially lower
risk of a security checkpoint or account disablement, both of which are much more expensive than
a few slow days.

### The one-paragraph strategy

Run **one manual ABO Sales campaign → one broad ad set → 3-5 ads**, optimized for **Initiate
Checkout (not Purchase)** while the pixel is cold, on broad geo / wide-age targeting, and **do not
touch it for 5-7 days at a time**. Feed it a steady stream of new creative tested in a separate
ABO testing campaign; graduate winners into the scaling campaign. Graduate the optimization event
itself to Purchase only once the account has accumulated roughly 30-50 real conversions. Avoid the
three mistakes that most reliably wreck a cold launch: Purchase-optimizing a cold pixel,
fragmenting budget across too many ad sets, and toggling settings mid-learning-phase.

### 1. Account & campaign structure

**Manual ABO, consolidated — not Advantage+/ASC yet, on a brand-new account.**

- **1 campaign → 1 ad set → 3-5 ads.** On $50-100/day this is close to unanimous guidance across
  practitioners: fragmenting a small budget across many ad sets is one of the most common reasons
  new campaigns fail to ever exit the learning phase, because no single ad set accumulates enough
  event volume.
- **3-5 ads per ad set** concentrates signal on a small budget; scale ad count up as budget grows.
- **Why not Advantage+ Sales (ASC) immediately:** ASC is what the platform pushes and what
  performs well at scale, but on a brand-new account it needs more weekly conversion volume than
  a cold pixel can feed it. The consistent new-account guidance is: start manual ABO, accumulate
  roughly 30-50 conversion events, *then* graduate to CBO/Advantage+.
- **Graduation path:** manual ABO now → once ~30-50 account conversions exist and you have proven
  winners → CBO / Advantage+ Campaign Budget to scale → test Advantage+ Sales as a parallel
  20-30% slice once you can feed it enough volume.

### 2. Targeting

**Broad geo/demo, wide age range, no interest stacks.**

- Broad targeting plus strong creative is the current default for conversion campaigns — interest
  stacks and static lookalikes are steadily being deprioritized as a targeting mechanism, and the
  platform's own audience-expansion tooling reports meaningfully lower cost-per-result than manual
  lookalikes.
- If a broad campaign is launched from a genuinely cold pixel, feeding it a customer/engager
  custom audience as a *suggestion* (not a hard target/exclusion) — where one already exists — is
  a reasonable middle ground: it gives the algorithm a seed without constraining reach. Avoid hard
  exclusions on a cold, low-volume campaign; they raise cost without enough data to justify it.
  Creative is the real targeting lever now — independent research attributes roughly half or more
  of incremental sales lift to creative rather than targeting.

### 3. Optimization event — the single most important early decision

**Optimize for Initiate Checkout (or the platform's next-best real conversion signal) while the
pixel is cold. Graduate to Purchase later.**

Purchase-optimizing a pixel with zero (or near-zero) counted purchases is the single most common
cause of extreme CPMs on new accounts. The mechanism: exiting the learning phase needs roughly
50 optimization events per ad set per 7 days; at even a moderate target CPA, that volume
requirement massively outstrips a $30-100/day budget for a Purchase event specifically — so the
ad set stays "Learning Limited" indefinitely and the platform rations impressions to a tiny,
expensive predicted-buyer pool.

There are two schools of thought here, worth knowing because they get argued past each other:
- One camp argues for optimizing on Purchase from day one and eating a slow start, because
  "seasoning" the pixel with low-quality events (raw link clicks, page views) teaches the
  algorithm the wrong signal.
- The more common practitioner guidance is: when you can't realistically hit the weekly
  conversion threshold on the true bottom-of-funnel event, optimize for the nearest **genuinely
  high-intent** event instead (Initiate Checkout → Add to Cart → View Content, in that order of
  preference), then graduate up.

**Initiate Checkout resolves the disagreement in practice**: it's a real high-intent signal (not
junk like a raw link click), and it's frequent enough to actually accumulate the volume needed to
exit the learning phase on a modest budget — so it satisfies both camps' underlying concern.

- **Graduation trigger:** switch the ad set's optimization event to Purchase once you can
  realistically sustain roughly 50 purchases/week (~7/day), OR the account has accumulated
  roughly 30-50 counted purchases and Initiate-Checkout volume is healthy. Changing the
  optimization event resets the learning phase, so make this switch **once, deliberately** — never
  repeatedly.
- **Prerequisite:** CAPI + browser pixel with `event_id` dedup must already be verified working
  (see §3.4 below) — verify that a real conversion actually counts once, cleanly, before trusting
  any of the volume math above.

### 4. Tracking — event_id deduplication (the fix for "conversions aren't counting")

This is the single most common silent failure mode on a new pixel, and it invalidates every
volume-based decision above if it's broken.

- Browser pixel and server-side CAPI must send **the exact same `event_name`** (case-sensitive —
  `purchase` ≠ `Purchase`) **and the exact same `event_id`**, within the platform's dedup window
  (Meta's is 48 hours; the first event received wins).
- **Mint one `event_id` at checkout-session creation** (derived from the payment processor's
  session or payment-intent ID), store it, and reuse that identical value for both the browser
  pixel fire on the thank-you page and the server-side CAPI event fired from the payment webhook.
  This guarantees the server-side conversion still counts even when the buyer never lands on the
  thank-you page (closed tab, ad blocker, iOS restrictions).
- **Verify in the platform's Events Manager (or equivalent):** the primary conversion event's
  dedup rate should land near 100% where both pixel and CAPI fire. Use the platform's test-event
  tooling before trusting production numbers.
- **Event Match Quality (EMQ):** score out of 10, recalculated on a rolling window. Target 6-8 —
  diminishing returns above ~8. The highest-value match parameters are hashed email plus the
  platform's own click-ID cookies; add phone/name/zip/external-ID/IP/user-agent to climb from 5 to
  8-9. Don't sacrifice event *volume* chasing a marginally higher match score.
- **Attribution window:** 7-day-click + 1-day-view is a reasonable default for a low-volume new
  account (more learning signal than 1-day-click-only), but cross-check against 1-day-click for
  fast-impulse products — a large gap between the two windows means the headline number is
  flattering true impulse economics. Reconcile ad-platform-reported conversions against your own
  backend/payment-processor data as ground truth; if the ad platform under-reports vs. your
  backend, you have an attribution or tracking gap, not a targeting problem.

### 5. New-account warm-up & scaling discipline

- **Pre-spend trust signals (lower CPM):** complete Business Manager verification, use a business
  (not personal) payment card, verify the domain, populate the Page fully, and get pixel + CAPI
  firing with standard events *before* meaningful spend. New accounts typically sit under a
  modest daily account cap and an initial trust-warm-up window; business verification is one of
  the strongest available CPM-lowering signals.
- **Budget ramp:** start at $30-50/day, raise by no more than ~20% every 2-3 days (48-72 hours
  lets the attribution window register the change before the next one). A single large jump can
  reset the learning phase. Some platforms now surface a safe-to-raise amount that's sometimes
  higher than 20% — but 20% remains the safe default on a fragile new account.
- **What resets the learning phase (avoid):** changing targeting, the optimization event, bid
  strategy, placements, creative edits, budget changes >20%, or pausing for 7+ days. Adding a
  brand-new ad on top of existing ones may not reset learning on some platforms — but name changes,
  schedule changes, and <20% budget raises are generally safe.
- **Keep ≥30% of budget spending *past* the learning phase** — i.e., don't let the account live in
  a permanent reset loop from over-eager optimization.

### 6. Creative system

Continuous creative supply is the actual scaling lever on a new account — brands that ship more
distinct creative concepts at equal budget consistently get more winners, while typically only a
small single-digit percentage of any batch of ads becomes a genuine winner. Volume and iteration
beat any single "perfect" creative.

- **Blend static + video.** Statics are meaningfully cheaper to produce and often cheaper CPA;
  video typically shows higher CTR and higher cold-audience ROAS. A reasonable mix at low spend is
  roughly 60% static / 40% video, shifting toward video as budget scales.
- **Video length:** 15-30 seconds, with 21-24s as a common sweet spot. Deliver the core value
  proposition by second 5 or the viewer is gone.
- **Aspect ratio:** build a 9:16 master (1080×1920) for Stories/Reels placements, export 4:5
  (1080×1350) for Feed. Keep on-screen text out of the top ~14%/bottom ~35% of the 9:16 frame
  (UI overlap).
- **Burned-in captions are close to mandatory** — a large majority of video is watched sound-off.
  Verify captions are actually burned into the exported video, not just available as an optional
  toggle, before anything goes live.
- **UGC / authentic formats over polished studio production** for consumer-facing products —
  founder-led, customer-story, and authority-voice formats are outperforming scripted
  talking-head studio ads in most current benchmarks. Branded static works well as the
  credibility-building complement.
- **Hooks (first 1.5-3 seconds decide almost everything):** pattern-interrupt + curiosity gap,
  immediate relevance (name the audience/problem fast), and a credibility spark. Proven angle
  frameworks: curiosity gap, contrarian take, problem-agitation, "secret reveal" / common mistake,
  founder-authority ("I spent $X testing…"), social-proof/stat lead, before/after, "people always
  ask me…". Layer a visual hook + a short on-screen text hook (5-8 words) + a verbal hook, all
  landing inside the first ~1.5-3 seconds.

### 7. Creative testing cadence (weekly operating rhythm)

- **Separate a TESTING campaign (ABO, equal budget) from the SCALING campaign** (the proven
  winner). Test new-vs-new concepts only — never a fresh concept against an ad with accumulated
  history, which biases the read toward the established ad.
- **Volume:** ship 3-5 genuinely distinct concepts per week (distinct hook × format, not trivial
  color/text variants — assets too similar to existing ones tend to get suppressed as redundant
  rather than scored fresh). Scale volume up as budget grows.
- **Budget per test:** roughly $30-50/day per concept, total test window $600-1,500 spent over
  5-7 days. Most scoring tools need a meaningful minimum spend per creative (commonly cited around
  $50) before a score is statistically meaningful.
- **Verdict at:** ~50 events, OR 7 days, OR roughly 2-3× target CPA spent per variant — whichever
  comes first. Minimum before judging anything: ≥3 days AND ≥2,000 impressions.
- **Metric ladder — diagnose in this order, then fix in this order:**

  | Metric | Formula | Kill / weak | Good (cold) | Strong |
  |---|---|---|---|---|
  | Hook rate | 3-sec views ÷ impressions | <20-25% | 25-30% | 35-40%+ |
  | Hold rate | 15-sec (or ThruPlay) ÷ 3-sec views | <30% | 40-50% | 60%+ |
  | CTR (link) | clicks ÷ impressions | <0.8-1% | 1-1.5% | >1.5% (ecom 1.5-2.5%) |
  | Cost/conversion | — | >2-3× target, no conversion | ≈ target | < target |

  Hook rate does **not** predict conversion by itself — it's a diagnostic for where in the funnel
  a creative is failing. Ultimately scale on CPA/ROAS/profit, benchmarked against the brand's own
  top-performing ads rather than generic industry numbers.

### 8. Fatigue & refresh

- Cost-per-result reaching roughly 2× its prior level is the standard definition of creative
  fatigue; anything elevated but under that line is "creative limited" rather than fully fatigued.
  Conversion likelihood drops meaningfully by around the 4th exposure to the same creative.
- **7-day frequency thresholds:** cold prospecting fatigue typically starts above 2.5-3.0
  (Reels tolerate slightly less, ~2.8; static Feed tolerates slightly more, ~3.5-4); retargeting
  tolerates materially higher frequency, 4-8+.
- **First-time-impression ratio <50%** signals audience saturation; a healthy prospecting ratio is
  65-80%.
- **Other fatigue signals:** CPM creep >18-35% vs. baseline, or CTR decay >20-25% vs. the week-1
  baseline.
- **Refresh cadence:** roughly every 2-3 weeks for active cold campaigns; Reels-format creative
  tends to burn out faster (7-14 days) than Feed video. Reacting late to fatigue wastes a
  meaningful share (commonly cited 15-25%) of spend on a declining asset.

### 9. Scaling & kill rules

- **Scale vertically first** (the large majority of early scaling): raise budget on winners by
  ≤20% every 2-3 days. Add a **horizontal** duplicate (new angle/geo/lookalike-seed) once vertical
  scaling shows diminishing returns or frequency exceeds 3-4. A duplicate enters its own fresh
  learning phase — don't risk the original by editing it directly.
- **Scale-up trigger:** ROAS/CPA at or beyond target+20% sustained over 7 days with ≥10
  conversions → raise budget +20%, at most once per day.
- **Kill rules:**
  - Ad set: 2× target CPA with zero conversions (3× if being more patient), or 3× CPA sustained
    over 3+ consecutive days.
  - Creative: hook rate <25% ("a creative problem, not a media-buying problem"), or CTR <0.8%
    over 7 days / 2,000+ impressions, or CTR <50% of a control creative combined with CPA >25%
    worse after 48-72 hours.
  - Never judge before ≥3 days AND ≥2,000 impressions AND roughly ≥2× target-CPA spend.

### 10. Policy compliance — avoid disapproval / account risk

Any vertical touching finance, business-opportunity, health, or "make money" framing sits in the
platform's highest-scrutiny bucket, and enforcement applies even to fully legitimate offers.
Treat every ad as guilty until proven compliant.

- **Unacceptable Business Practices:** no deceptive or exaggerated success claims, no
  get-rich-quick or unrealistic-outcome framing, no misrepresented financial benefit.
- **Personal Attributes (the most common auto-rejection trigger):** ads must not assert or imply
  knowledge of the viewer's personal attributes, including financial status. The trigger is
  typically "you/your" + an implied attribute. Avoid: "Struggling financially?", "Broke?",
  "Tired of your 9-5?" — prefer third-person, benefit-led framing: "A framework for building X."
- **Earnings-claim ban (for anything money/business-opportunity adjacent):** no specific or
  guaranteed earnings figures, no "replace your salary" framing, no before/after income-screenshot
  imagery as a "typical result." The line: specific or guaranteed earnings claims are banned;
  a realistic description of what the product/service actually does is allowed. Sell the
  process/skill, not a promised income outcome.
- **Keep income or outcome-proof imagery off ad creative entirely** where a vertical is
  sensitive; if it appears at all, put it on the landing page only, clearly framed as one
  individual's own result with a "results not typical" disclaimer directly adjacent, and never
  imply the viewer will achieve the same outcome.
- **Landing-page requirements** (the platform reviews the destination page, not just the ad):
  ad-to-page message congruence, working links, a functional checkout, visible Privacy/Terms/
  Refund/contact info, an explicit outcome disclaimer wherever any result is shown, no fake
  urgency/scarcity, no engagement-bait.
- **Account-level behavioral triggers:** rapid spend escalation reads as a compromised account
  and can trigger an automatic restriction. Ramp gradually (a multi-week ramp, not multi-day),
  keep a healthy approved:disapproved ad ratio (repeated disapprovals compound toward
  account-level enforcement), use a consistent payment method, avoid VPN/geo-mismatched logins,
  and complete business + domain verification early.
- **Appeals:** use the platform's account-quality review flow; attach business ID, the specific
  ad(s), landing-page screenshots, and a clear explanation. File one appeal per open review window
  — duplicate appeals tend to auto-reject.

---

## Part 3 — Meta Marketing API: Operational Best Practices

Engineering-level contract for any system that automates against the Meta Marketing API
(campaign/ad-set/ad creation, insight syncs, autopilot actuators). Pin a specific API version in
one constant and update deliberately — Meta deprecates versions on a roughly annual/quarterly
cadence. Everything below generalizes lessons from a real incident: an undisciplined burst of raw
API calls tripped a security checkpoint (error code 31) and hit two field-validation errors while
building a live campaign.

### 0. Architecture: a thin async client + middleware, not raw sequential calls

Do not fire raw sequential HTTP calls in a loop (this is what caused the checkpoint), and don't
lean on a blocking SDK with no retry/backoff logic. Build one async HTTP transport with
middleware that, on every call:

1. **Pins the API version** — one constant, updated deliberately.
2. Attaches the request-signing proof (`appsecret_proof` = HMAC-SHA256 of the token with the app
   secret).
3. **Reads the usage headers on every response and throttles at ~75-80%** (§2 below).
4. **Classifies the error** and only applies backoff-with-jitter to genuinely transient/rate
   error codes (§2 below) — never blind-retries a hard failure.
5. **Enforces idempotency**: encode a spec-hash into the object's `name` field, read-back-by-name
   before creating, and keep a local request-id → object-id map so a retry never duplicates an
   object.
6. **Caps concurrency** to roughly 5-10 in-flight requests per ad account.
7. Optionally dry-runs writes with the platform's `validate_only` execution option before a real
   write.

A vendor SDK can still be useful offline for cross-checking field names or running validate-only
dry-runs, but shouldn't be the thing making live, unthrottled calls.

### 1. Auth — a non-expiring System User token per brand/account

A personal user token is the wrong tool for server automation: it's tied to a human, expires, and
breaks on password changes or personal-account checkpoints — which can itself look like a security
flag to the platform.

**Use a Business-Manager System User token** instead — a server identity, non-expiring, built for
automation:
- Create it under Business Settings → Users → System Users → Add (Admin or Employee role).
- **Assign only the needed assets** to it (the specific ad account, Page, pixel/dataset) —
  least privilege.
- Request it with only the scopes actually needed: `ads_management` + `business_management` for
  write access, `ads_read` only for read-only integrations.
- **Never use a single shared token across multiple brands/ad accounts** — concentrating
  automated write activity on one actor across many accounts reads as anomalous and has led to
  multiple account suspensions in practice. One token per brand, bound to that brand's own
  credential record.
- Also pursue business verification and the platform's higher API-usage tier where available
  (typically auto-granted after a sustained period of API calls with a low error rate) — it
  raises write-volume quotas substantially and sharply reduces checkpoint risk.

### 2. Rate limits, error handling, resilience

**Business-Use-Case (BUC) rate limiting** operates per business, per use-case, per ad account,
on a rolling ~1-hour window. Read these headers on every response and throttle the relevant
bucket at **~80% utilization**:
- The Business-Use-Case usage header — reports `call_count`, `total_cputime`, `total_time` (all
  as % 0-100), `estimated_time_to_regain_access` (minutes), and `type` (e.g. `ads_management` vs
  `ads_insights`).
- The app-wide usage header, and an insights-specific throttle header for per-account/app
  utilization.
- **Scoring:** a read costs 1 point, a **write costs 3 points** — writes burn the budget 3× as
  fast as reads. Your own error rate *shrinks* the available quota over time, so keep the error
  rate under roughly 15%.

**Classify the error before reacting — never blind-retry everything:**

| Error class | Meaning | Action |
|---|---|---|
| Transient service error | temporary platform issue | retry with exponential backoff + jitter (idempotent operations only) |
| App rate limit | app-wide throttle | back off app-wide, read the app-usage header |
| User rate limit | per-user throttle | back off, exponential retry |
| Page/custom rate limit | per-object throttle | back off |
| BUC throttle codes | business-use-case throttled | **pause that use-case for the reported `estimated_time_to_regain_access` minutes** |
| Temporary policy block | short-lived policy hold | wait, slow retry |
| **Security checkpoint** ("authenticate your account") | account-level flag, NOT a rate limit | **STOP. Only a human can clear it in the platform's UI. Never auto-retry — retrying deepens the flag.** |
| Invalid/expired token | token no longer valid | re-issue the token; do not loop-retry |
| Invalid parameter | payload error | fix the payload using the error's field-blame data; no retry |
| Permission denied | scope/asset-assignment issue | fix scopes or asset assignment; no retry |

**Backoff policy:** exponential with full jitter (base ~2s, doubling, capped around 5 minutes,
at most ~5 retries). For hard throttles, treat the platform's reported wait time as a floor, not
a suggestion. **Never blind-retry a create operation after a network timeout** — the object may
have been created server-side despite the timeout; always reconcile by reading back by name
first. Keep overall concurrency under roughly 100 QPS per account, 5-10 in-flight.

### 3. Security / checkpoint avoidance

A security checkpoint is an account-level flag, not a rate limit, and only a human can clear it
by completing an identity-confirmation step in the platform's own UI. Common triggers: a
new or recently-rotated app with no history, rapid bursty machine-cadence writes, a token that
was just rotated (which looks like a new actor), or inconsistent IP/geo on requests. Avoid it by:

1. Completing business verification — the single biggest lever.
2. **Warming up** a new or rotated app/token over roughly 7-14 days — start at low write volume
   and ramp, rather than bursting immediately.
3. **Pacing writes like a human** — small delays between mutating calls, never tight
   create-in-a-loop patterns.
4. Treating any token/app rotation as "cold" — reduced write volume for a day or two afterward.
5. Keeping egress IP/geo stable and consistent with the account's normal usage pattern.
6. On a checkpoint: stop immediately, alert a human, and resume at reduced pace only after a
   human has cleared it.

### 4. Object model & correct creation flow

**Hierarchy:** Campaign → Ad Set → (Ad Creative) → Ad. Create top-down, everything **PAUSED**
initially, verify by reading it back, then activate. **Run every payload through the platform's
`validate_only` dry-run first** — it catches most field-level errors for free, before they ever
reach a live account.

- **Campaign:** set `name`, `objective` (an outcome-based objective, e.g. sales/conversions),
  `special_ad_categories` (required — send an empty list for a normal, non-regulated campaign),
  and `status`.
  - ⚠️ **Common mistake:** any campaign-level budget, bid-strategy, or budget-sharing field puts
    the campaign onto the Campaign Budget Optimization (CBO) contract, and the platform then
    requires the rest of that contract's fields. **For an ad-set-budget (ABO) campaign, send zero
    budget/bid/CBO fields on the campaign itself** — budget and bid live on the ad set.
- **Ad Set:** `name`, `campaign_id`, `optimization_goal`, `billing_event`, `status`,
  `daily_budget` (in the account's minor currency unit, e.g. cents), `targeting`, and for
  conversion campaigns a `promoted_object` + `destination_type`.
  - For website purchase/checkout campaigns: optimize on the conversion event, bill on
    impressions (never bill on the conversion event itself), and set the destination type to
    website.
  - `promoted_object` (pixel ID + custom event type) is **required and immutable after creation**
    for conversion campaigns — get the event-type spelling exactly right per the platform's
    documented values (they're easy to get subtly wrong, e.g. an underscore/word-order mismatch).
  - Choose a bid strategy that doesn't require a bid amount unless you're intentionally setting a
    cap — mixing a capped bid strategy with no bid amount (or vice versa) is a common validation
    error.
  - ⚠️ **Common mistake:** an audience-expansion/advantage-audience flag interacts with age
    targeting — enabling it can silently override or reject an explicit age cap. Decide
    explicitly: either disable audience expansion and keep a hard age cap (manual broad), or
    enable it and drop the age cap entirely (age becomes a soft suggestion, not a hard limit).
    Don't combine "expansion on" with a restrictive age cap and expect both to hold.
- **Ad:** `name`, `adset_id`, `creative` (by creative ID), `status`, and a conversion-domain field
  (the landing-page domain) — **required** on pixel/conversion campaigns and easy to forget. The
  Page binds via the creative's own story spec; the pixel binds via the ad set's promoted object;
  keep the conversion-domain field matched to the actual landing-page domain.

### 5. Creatives

- **Images:** upload via the ad-image endpoint with a real filename + extension; store the
  returned **hash**, never the temporary URL it also returns.
- **Videos:** use the resumable upload flow (start → transfer → finish) to get a video ID, then
  **poll the video's status until it reports "ready" before attaching it to a creative** — this is
  the classic "video is still processing" publish failure if skipped. Always set a thumbnail.
- **Dedup:** re-posting an identical creative spec returns the *existing* creative ID rather than
  creating a duplicate — treat creation as idempotent and key your own database on the returned
  ID; reuse one creative ID across multiple ads rather than re-uploading.
- Use "dark post" creative (not tied to an organic Page post) for machine-generated creative, to
  keep the Page's own timeline clean; only reference an existing organic post ID when you
  specifically want to boost that post and inherit its social proof.
- Always set the Page ID; add the current Instagram user-ID field (not a deprecated equivalent)
  for Instagram placements.
- **For clean creative tests:** disable automatic creative enhancements/dynamic optimizations
  explicitly per variant during a test — accounts get auto-enrolled into automatic creative
  "enhancements" that silently alter creative and pollute A/B reads. Turn dynamic/automatic
  creative optimization back on only once you're scaling a proven winner, not while testing.
- **Burned-in captions must be baked into the video at export time** — the API can only attach a
  separate closed-caption file, it cannot add on-screen burned-in text to an existing video.
- After creation, poll the ad's effective status; on disapproval, read the platform's detailed ad
  review feedback (both global and placement-specific reasons), log the reason, and route to
  regeneration. Ads can be disapproved *after* going live too — keep monitoring, don't just check
  once at launch.

### 6. Insights (reading performance data)

- **One account-level call per grain** (e.g. one call at the ad level returns all ads) — never
  loop and call per individual object.
- **Use async report jobs** for anything non-trivial: kick off the insights job, poll until it
  reports complete (with backoff), then fetch results. Report jobs typically expire after about
  30 days if not fetched.
- **Conversions:** read the platform's deduplicated/omni conversion count and its paired value
  field rather than a raw pixel-only or CAPI-only conversion count — **never sum a deduplicated
  count with a raw pixel/CAPI count**, that double-counts. All numeric values typically come back
  as strings — parse them.
- **Attribution window:** pin a single, explicit attribution-window setting everywhere in your
  reporting (e.g. 7-day-click + 1-day-view) rather than relying on whatever the account's
  UI-level default happens to be — platforms have changed default/available attribution windows
  before without much notice.
- **Per-day series:** request daily granularity in a single call rather than looping per day;
  filter out zero-delivery rows to reduce noise.
- **Treat the most recent 48-72 hours of data as provisional** — insights typically restate for a
  couple of days and don't fully settle for weeks. Don't hard-pause or hard-scale a campaign off
  a single fresh-day reading.
- **High-cardinality breakdowns** (e.g. per-product, per-target-ID) should be scoped narrowly
  (shorter windows, fewer dimensions at once) — requesting too much at once is a common source of
  API errors; build an automatic fallback and log any rejected requests rather than failing
  silently.
- **Reconciliation reality:** the ad platform's own reporting, its pixel-side stats, and your
  backend/payment-processor data will never match exactly. Standardize on one attribution window
  when comparing, use the deduplicated conversion fields, and treat your backend/payment data as
  the directional ceiling — if the ad platform reports meaningfully fewer conversions than your
  backend, that's an attribution/tracking gap to fix, not a targeting problem.

### 7. Batch, async & idempotency

- **Batch requests** (a single call bundling many sub-operations, typically capped around 50 ops,
  with tighter per-type caps like ~10 ad-creates per batch) cut round-trips, **not your rate-limit
  quota** — every sub-operation still counts individually against usage. Dependent creation within
  one batch (e.g. campaign → ad set) is supported via a result-reference syntax. Watch for `null`
  entries indicating a partial timeout, and re-submit just those.
- **Async batch requests** (a larger job, often up to ~1000 operations) suit large bulk-create
  pipelines; poll the job rather than the individual operations.
- **Idempotency:** the platform has no idempotency-key header, so build it yourself — encode a
  spec-hash into the object's `name`, read-back-by-name before creating, and keep a local
  request-id → object-id map so retries never create duplicates.
- **Version discipline:** pin one API version in one constant; each version is typically
  supported for a couple of years. Watch for deprecation notices and test the next version in a
  staging environment before switching.

### 8. How this typically gets wired into an automation system

- **Auth layer:** resolves each brand's own system-user token from an encrypted per-brand
  credential store (never a single global token), and attaches the request-signing proof.
- **Client/transport layer:** the async HTTP transport + middleware described in §0 — version
  pin, header-based throttling (§2), error classification + backoff, concurrency cap,
  validate-only helper, batch/async helpers.
- **Dispatch layer:** every mutating operation (pause/resume a campaign, update an ad set's
  budget, create a new object) goes through the sequence: validate-only dry-run → read-back
  idempotency check → paced write → read-back verification.
- **Autopilot/actuator layer:** respects the throttle headers, never bursts writes, honors the
  "48-72h provisional data" rule before taking any hard action (pause/scale) on freshly reported
  numbers, and surfaces a security-checkpoint or invalid-token error straight to a human rather
  than auto-retrying.
- **Warm-up guard:** after any token or app rotation, automatically cap write volume for the
  following day or two.

### Master best-practice checklist

1. Non-expiring System User token, least-privilege asset assignment, request-signing proof,
   per-brand credential store — never one shared token across brands.
2. Business verification + a higher API tier where available; warm up after any rotation; pace
   writes; keep egress IP/geo stable.
3. A thin async client + middleware — not raw sequential loops, not a bare blocking SDK.
4. Read usage headers on every call; throttle at ~80%; honor the platform's reported
   wait-time-to-regain-access.
5. Classify errors before reacting; retry only genuinely transient/rate codes with backoff +
   jitter; never retry a security checkpoint, invalid token, validation error, or permission
   error.
6. Dry-run (`validate_only`) before every real write; create everything PAUSED → verify by
   reading back → activate.
7. For ad-set-budget (ABO) campaigns: zero budget/bid/CBO fields on the campaign object itself.
8. Get the conversion-optimization contract right: correct billing event, correct destination
   type, a correctly-spelled and immutable `promoted_object`.
9. Be explicit about audience-expansion vs. hard age caps — never assume both hold at once.
10. Set the conversion-domain field on every ad in a pixel/conversion campaign.
11. Creatives: image → store the hash not the URL; video → poll until ready before attaching;
    always set a thumbnail; use dark posts for machine-generated creative; dedup and reuse
    creative IDs; disable automatic creative enhancements during clean A/B tests; poll ad-review
    feedback after launch, not just at launch.
12. Insights: pull per-grain at the account level, use async report jobs, use deduplicated
    conversion fields, pin one attribution window, treat the last 48-72h as provisional, never
    expect exact cross-source equality.
13. Build idempotency yourself via spec-hash naming + read-back; never blind-retry a timed-out
    create.
14. Remember batching cuts round-trips, not your quota; use async batch jobs for real bulk-create
    work.
15. Pin one API version in one place; track deprecations; upgrade deliberately, not reactively.
