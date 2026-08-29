---
name: amazon-ads
description: Amazon Ads (Sponsored Products/Brands/Display) + listing audit handbook — category-weighted checklist, severity levels, thresholds, and fix tactics for any brand selling physical inventory on Amazon.
---

# Amazon Ads & Listing Audit Handbook

A structured audit checklist for Amazon Sponsored Products (SP), Sponsored
Brands (SB), Sponsored Display (SD), and the organic listing surface that ad
spend depends on. Applies to any brand selling physical inventory on Amazon
(first-party seller or marketplace operator reselling on Amazon) — not tied
to any specific brand or vertical.

Craft distilled from field practice documented by Helium 10 / Destaney
Wishon (BetterAMS), BellaVix, Ad Badger, Canopy Management, Feedvisor,
SellerApp, MyAmazonGuy, Incrementum Digital, Pixamp (attribution), Jon
Loomer, Titan Network, headlineMA, and CaptenAMZ.

## When to use this handbook

Use it whenever asked to audit, diagnose, or improve an Amazon Ads account
or a product listing that ads are driving traffic to. It covers both sides
of the equation deliberately — a perfect campaign structure still bleeds
money if it points at a listing that doesn't convert, and a perfect listing
still under-monetizes if the campaign structure or keyword hygiene is weak.

---

## Scoring model

Every check has: a **weight** (relative importance within its category), a
**severity** (`critical` / `high` / `medium` / `low`), and three grading
tiers (`pass` / `warning` / `fail`, sometimes `n/a` when data volume is too
low to grade safely).

**Category weights (Health Score = weighted sum of category sub-scores):**

| Category | Weight |
|---|---|
| Tracking / Attribution Health | 20% |
| Listing & Creative | 25% |
| Account Structure | 30% |
| Keyword & Negative Hygiene | 25% |

This mix is deliberate and differs from a Meta/paid-social audit — on
Amazon, leverage sits more in campaign and keyword discipline than in
creative, because the marketplace itself (not an ad platform algorithm)
mediates most of the relevance signal.

**Per-check scoring:** `check_score ∈ {0, 50, 100}` for fail / warning /
pass (n/a checks are excluded from the denominator).

**Severity multiplier (`W_sev`):** critical 5.0 · high 3.0 · medium 1.5 ·
low 0.5.

**Category sub-score:**
```
sub_score = Σ(check_score × weight × W_sev) / Σ(100 × weight × W_sev)
```

**Final health score:**
```
health = 0.20 · tracking_score
       + 0.25 · listing_score
       + 0.30 · structure_score
       + 0.25 · keyword_hygiene_score
```

**Grade letters:** 90–100 A · 80–89 B · 70–79 C · 60–69 D · <60 F.

**Critical checks always surface in output**, even when they pass, and a
FAIL on any critical check caps that category's sub-score at 50 regardless
of how the rest of the category scores. Treat a critical FAIL as a
headline finding, not one line in a list.

**Critical-checks list:** Brand Registry status, 6-campaign spoke per hero
SKU (when missing for a top-spend SKU), keyword graduation rule, negative:
positive keyword ratio, ACOS within target band, title structure, out-of-
stock cover.

**Primary metric:** most checks grade against ROAS (`1 / ACOS`) rather than
cost-per-purchase — Amazon's own reporting is ROAS/ACOS-native, and
TACoS/ACOS trade-offs are central to how Amazon accounts are actually
managed. A few structural/listing checks grade against a generic "health"
metric instead (they're pass/fail on presence or spec compliance, not a
cost efficiency number).

---

## Category A — Tracking & Attribution Health (20%)

### Brand Registry enrollment
- severity: **critical**
- **Pass:** brand enrolled in Amazon Brand Registry in every marketplace it
  spends in.
- **Warning:** enrolled in the primary marketplace only — other
  marketplaces are locked out of A+ content, Sponsored Brands, Stores, and
  the Attribution API.
- **Fail:** not enrolled anywhere — the brand is limited to Sponsored
  Products only and is missing 30–50% of available ad leverage.
- **Why it matters:** roughly half of Amazon's ad surface area (Sponsored
  Brands, Sponsored Display, Stores, Attribution) is gated behind Brand
  Registry. It's the single highest-leverage unlock available.
- **Fix:** register IP with Amazon, then enroll via Seller Central → Brand
  Registry. Expect 2–4 weeks turnaround per marketplace.

### Attribution window discipline
- severity: high
- **Pass:** account docs explicitly cite Amazon's 14-day last-touch
  attribution default, and any cross-channel ROAS comparison documents its
  own normalization method rather than comparing raw numbers.
- **Warning:** the 14-day default is documented but there's no written
  cross-channel comparison methodology.
- **Fail:** ROAS is compared across Amazon and another channel (e.g. Meta)
  at face value.
- **Why it matters:** Amazon defaults to 14-day last-touch; Meta defaults
  to 7-day-click + 1-day-view. A naive comparison overstates Amazon's
  relative performance by roughly 20–40%. The honest normalization is a
  sessions-delta comparison (measuring incremental total-store sessions,
  not comparing platform-reported ROAS directly).

### Cross-SKU sales visibility in keyword decisions
- severity: high
- **Pass:** keyword-level ROAS analysis joins the keyword report with the
  per-ASIN attributed-sales report and includes "sales of other SKUs"
  columns (7d/14d/30d), so a keyword driving cross-category conversions
  isn't mistaken for a dead keyword.
- **Warning:** cross-SKU sales are checked for top keywords only — the
  long tail isn't covered.
- **Fail:** kill/negate decisions are made on same-SKU sales alone.
- **Why it matters:** a keyword with zero same-SKU conversions but real
  spend-adjacent revenue in other SKUs is a cross-category discovery
  driver, not waste. Killing it cuts revenue invisibly — it never shows up
  as a regression in that keyword's own numbers.

### Search Term Report cadence
- severity: high
- **Pass:** the Search Term Report is pulled every 7 days with monitoring,
  and no week has been skipped in the last 60 days.
- **Warning:** weekly cadence exists but is unmonitored — recent weeks
  look fine but there's no alert if a pull silently fails.
- **Fail:** last pull is more than 14 days old, or there's any gap in the
  last 60 days.
- **Why it matters:** Amazon retains only 60 days of search-term history.
  Miss a weekly pull and that week's keyword-discovery signal is gone
  permanently — it cannot be backfilled.
- **Fix:** schedule via cron/Airflow (or equivalent) with failure alerting.

### Amazon Attribution API (per-click, off-Amazon → Amazon)
- severity: medium
- **Pass:** off-Amazon paid channels (Meta, Google, TikTok, etc.) are
  wired into Amazon Attribution so per-click cross-channel data is
  visible, not just modeled.
- **Warning:** enabled, but the UTM/attribution-tag template is missing or
  applied inconsistently.
- **Fail:** not enabled, or the brand isn't registered in an eligible
  marketplace (available in US/UK/EU markets).
- **Why it matters:** per-click attribution closes the measurement gap
  that sessions-delta normalization only approximates.
- **Fix:** Brand Registry in an eligible marketplace → Attribution
  console → append the attribution tag to every off-Amazon URL pointing at
  a product detail page.

---

## Category B — Listing & Creative (25%)

### A+ Content on top-spend SKUs
- severity: high
- **Pass:** A+ content (comparison chart + brand story) is live on every
  SKU in the top 10 by ad spend.
- **Warning:** present on 50–90% of the top 10.
- **Fail:** present on fewer than 50%.
- **Why it matters:** A+ content lifts conversion rate roughly 5–10%
  (Amazon-reported average). Paying for clicks that land on a bare listing
  is one of the most common — and most avoidable — sources of wasted
  Amazon spend.
- **Fix:** produce A+ assets in descending order of ad spend; each SKU
  typically takes 3–7 days to design and publish.

### Hero image spec compliance
- severity: medium
- **Pass:** hero image ≥1600px on the longest side, pure-white background,
  product fills ≥85% of the frame, no text overlay — checked on the top
  10–100 SKUs by ad spend.
- **Warning:** spec passes but the image is under 2000px, which loses
  eligibility for Amazon's Zoom feature.
- **Fail:** any top-10 SKU fails spec — Amazon can downrank listings with
  non-compliant images in search.
- **Fix:** re-shoot or vector-replace; bulk upload via Seller/Vendor
  Central.

### Listing copy keyword coverage
- severity: medium
- **Pass:** the title carries the single highest-converting keyword from
  the Search Term Report; bullets carry the next 4–6 highest-converting
  terms; backend search terms (250-character limit) are fully populated
  with no duplication of title/bullet content.
- **Warning:** title is on-target but bullets are thin, or backend terms
  are half-empty.
- **Fail:** title is a generic product name with no keyword intent, and
  backend terms are empty.
- **Why it matters:** both organic and paid relevance key off listing
  copy. Thin copy caps how far an Exact-match campaign can scale, because
  Amazon's own relevance model has less to work with.
- **Fix:** pull winners from the Search Term Report into title and
  bullets; fill backend terms with non-redundant synonyms/variants.

### Buy Box ownership
- severity: high
- **Pass:** the brand owns the Buy Box ≥95% of the time on every SKU
  running Sponsored Products.
- **Warning:** 80–95% — intermittent loss, usually a pricing or stock
  issue.
- **Fail:** below 80% — ads keep running but the Add-to-Cart button routes
  to a competitor or third-party seller.
- **Why it matters:** Sponsored Products without the Buy Box effectively
  funds a competitor's revenue with your ad budget.
- **Fix:** pause Sponsored Products on any SKU without the Buy Box while
  investigating root cause (price parity, FBA stock, listing suppression).

---

## Category C — Account Structure (30%)

### Six-campaign spoke per hero SKU
- severity: high
- **Pass:** every hero SKU runs all six canonical campaign types — Auto
  (Discovery), Broad (Expansion), Phrase (Intent), Exact (Conversion),
  Brand Defense, and Competitor — at roughly this budget split: **Auto
  15% · Broad 20% · Phrase 20% · Exact 30–40% · Brand Defense 5% ·
  Competitor 10%.**
- **Warning:** 4–5 of the 6 are present, or Exact is under 25% of the
  SKU's total ad budget.
- **Fail:** 3 or fewer campaign types present, or there's no Exact
  campaign at all (no funnel destination for proven converters).
- **Why it matters:** this structure is the point of convergence across
  the field-practice sources this handbook draws on. The most common
  failure mode — and the one that caps scale hardest — is missing the
  Exact campaign, because discovery campaigns (Auto/Broad) are inherently
  more expensive per conversion.
- **Fix:** stand up whichever campaign types are missing; rebalance budget
  toward the canonical split; never over-allocate to Auto/Broad since
  those are discovery tools, not scale tools.

### Bid strategy matched to campaign role
- severity: medium
- **Pass:** Auto/Broad run on **Dynamic bids — down only**; a new SKU's
  Exact campaign also runs Dynamic-down; an established SKU's Exact
  campaign runs **fixed bids**; Brand Defense runs Dynamic-up-and-down
  with a small premium; a top-converting Exact campaign carries a
  placement bid modifier of **+50–100% on Top-of-Search**.
- **Warning:** 1–2 campaigns are on the wrong strategy for their role.
- **Fail:** the account runs blanket Dynamic-up-and-down everywhere —
  Amazon's algorithm keeps ratcheting up bids on already-scaling terms,
  bleeding ACOS with no ceiling.
- **Fix:** reassign bid strategy per campaign role; this is a one-time
  configuration change with no learning-phase penalty.

### Keyword graduation rule
- severity: high
- **Pass:** when a search term surfaced through Auto/Broad converts ≥2
  orders within 14 days at an ACOS below target, it gets (a) added as an
  Exact-match keyword in the Exact campaign at a higher bid, AND (b) added
  as a negative-exact in the source campaign it graduated from.
- **Warning:** graduation happens, but step (b) — the negative in the
  source campaign — is skipped, so the same term now bids against itself
  from two campaigns.
- **Fail:** no graduation flow exists at all — proven winners stay buried
  in Auto, where bid granularity and match-type control are unavailable.
- **Why it matters:** this is the core mechanic of a healthy Amazon SP
  account — Auto/Broad exist to discover, Exact exists to scale. Without
  the graduation loop, the whole structure degenerates into noise.
- **Fix:** run this as a scheduled weekly job with human approval on the
  proposed adds/negatives.

### Budget velocity discipline
- severity: medium
- **Pass:** no campaign's daily budget moved more than ±20% of its
  prior-week average within any single 7-day window. (Cumulative shifts
  across 4 weeks can legitimately reach +300% for a deliberate scale-up —
  the constraint is on the pace, not the destination.)
- **Warning:** one campaign shifted 20–40% within a single window.
- **Fail:** a blanket shift greater than 40% happens within a week —
  Amazon's bid optimizer gets destabilized, typically producing 7–14 days
  of erratic ACOS afterward.
- **Fix:** enforce the ±20%/week cap in whatever tool proposes budget
  changes.

### Auto/Broad budget cap
- severity: medium
- **Pass:** Auto + Broad combined are ≤35% of a SKU's total ad budget —
  they're data-mining tools, not primary delivery.
- **Warning:** 35–50%.
- **Fail:** over 50% — the account is paying premium discovery-tier rates
  for traffic that Exact could pick up more cheaply once graduated.
- **Fix:** rebalance toward Phrase and Exact.

### Brand Defense campaign live
- severity: medium
- **Pass:** Sponsored Products + Sponsored Brands campaigns bid on the
  brand's own name and key product names, at roughly 5% of the SKU's ad
  budget.
- **Warning:** live but underbudgeted (under 2% — competitors can still
  win the impression on price).
- **Fail:** not live — competitors have free reign to capture branded
  search traffic.
- **Why it matters:** branded clicks are cheap and branded conversion rate
  is high, so the ROI is almost always strongly positive; the downside of
  skipping it (a competitor buying your brand name) is large and
  asymmetric.
- **Fix:** stand up the campaign; bid roughly 1.5× the current category
  CPC to guarantee top-of-search placement.

---

## Category D — Keyword & Negative Hygiene (25%)

### Negative:positive keyword ratio
- severity: high
- **Pass:** account-wide negative-keyword count is ≥3× the positive-
  keyword count.
- **Warning:** 1.5–3×.
- **Fail:** under 1.5× — search-term contamination is capping relevance
  and wasting spend on near-misses.
- **Why it matters:** healthy PPC accounts run roughly 3–5× as many
  negatives as positives. Under-negating means cheap, irrelevant clicks
  are consuming budget that proven Exact-match terms would otherwise
  convert.
- **Fix:** run the weekly kill-list process and maintain preemptive
  category negatives (below).

### Weekly search-term kill-list
- severity: high
- **Pass:** a weekly process identifies search terms with 20+ clicks and
  0 orders over 30 days, and adds them as negative-exact in the ad group
  that spent on them, with human approval.
- **Warning:** the process exists but has a lag of more than 14 days.
- **Fail:** no kill-list process — wasted spend accumulates indefinitely.
- **Fix:** schedule the weekly job; gate any proposed negative against the
  cross-SKU check (a term with real cross-SKU revenue shouldn't be
  killed even if it has zero same-SKU orders).

### CTR-floor negation
- severity: medium
- **Pass:** search terms with 50+ impressions and CTR below 0.3% over 14
  days are added as negative-phrase in the source campaign.
- **Warning:** the rule exists conceptually but isn't enforced with a
  hard threshold.
- **Fail:** low-CTR impressions accumulate unchecked — Amazon's
  account-level relevance/quality signal takes a hit.
- **Fix:** enforce the threshold in whatever process manages negatives.

### Preemptive category negatives
- severity: medium
- **Pass:** a per-vertical negative-keyword list is deployed across every
  campaign in that vertical from day one (e.g. a supplement brand negates
  "cheap," "free sample," "discount code"; an electronics brand negates
  "repair," "manual," "for parts").
- **Warning:** the list exists but isn't deployed to every campaign.
- **Fail:** no such list — the first 60 days of any new campaign donate
  budget to the same predictable category-level junk clicks.
- **Fix:** maintain and version a per-vertical negative list; deploy it by
  default on every new campaign launch.

### ACOS within lifecycle-appropriate target band
- severity: high
- **Pass:** 30-day ACOS sits within the target band appropriate to the
  SKU's lifecycle stage — **Launch 40–80%** (deliberately aggressive),
  **Growth 25–40%**, **Mature 15–30%**, **Decline ≤15%** (efficiency
  mode).
- **Warning:** outside the band by up to 1.3×.
- **Fail:** more than 1.5× the upper bound for 14 consecutive days.
- **Why it matters:** lifecycle stage, not a single universal number,
  should drive the target. A Launch-stage SKU at 60% ACOS is healthy; a
  Mature SKU at the same 60% is bleeding money.
- **Fix:** cut bids on the worst-offending Exact/Auto keywords first; if
  there's no improvement in 14 days, escalate to a structural review.

### TACoS trend
- severity: medium
- **Pass:** Total Advertising Cost of Sales (ad spend ÷ total sales
  including organic) is flat or trending down month-over-month.
- **Warning:** trending up by less than 20%.
- **Fail:** trending up more than 20% month-over-month — organic share is
  shrinking and paid spend is masking a listing, pricing, or review
  problem underneath.
- **Why it matters:** ACOS alone can look fine while TACoS deteriorates —
  TACoS is the only metric that captures organic cannibalization.
- **Fix:** investigate organic rank, review velocity, and price
  competitiveness before scaling paid spend further.

### Catalog / feed health
- severity: high
- **Pass:** every top-10 ad-spend SKU appears cleanly in the product
  catalog with sales-rank and category-classification data populated, and
  at least one declared product type matches the brand's actual category.
- **Warning:** one or more top-10 SKUs is missing sales-rank or
  classification data (a suppression risk — the listing exists but hasn't
  been cleanly classified, so ad eligibility may be intermittent).
- **Fail:** a top-10 SKU doesn't return a catalog record at all (feed
  stale, listing suppressed, or a variant orphaned) — ad spend is landing
  on an undetectably broken product page.
- **Why it matters:** Sponsored Products campaigns target catalog ASINs;
  a stale or suppressed catalog feed silently caps every campaign
  pointed at that SKU.
- **Fix:** re-trigger feed processing; fill missing classification/variant
  attributes; resolve any listing-quality alerts in Seller Central.

### Off-Amazon ad URLs target the canonical product page
- severity: medium
- **Pass:** every off-Amazon paid ad pointing traffic at Amazon links to a
  canonical product-detail-page URL (`/dp/<ASIN>`) — never a search-
  results URL.
- **Warning:** 90–99% of URLs are canonical.
- **Fail:** any active ad points at a search-results URL.
- **Why it matters:** a search-results URL surfaces competitors'
  Sponsored Products above (or instead of) the intended product — the
  brand may be paying to send its own paid traffic to a competitor's ad.
- **Fix:** rewrite ad URLs; add a pre-publish check that rejects any
  non-canonical Amazon URL.

---

## Extended checklist — deeper ads-side tactics

These extend the four core categories with more advanced levers. Grade
them the same way (pass/warning/fail, weight × severity), but they assume
the account has already cleared the core checklist above.

**Search-term mining → exact-match harvest.** High-converting terms
surfaced by Auto/Broad should graduate to exact-match within the week they
clear the threshold (≥2 orders, on-band ACOS). Leaving them in Auto/Broad
means paying 2–3× the CPC for the same conversion, because those campaign
types bid on broader, more contested traffic. Fail state: 5+ harvestable
terms ignored for more than 30 days.

**Single-keyword ad groups (SKAG) for the top 20 keywords by spend.** A
mixed-intent ad group lets a cheap-converting keyword inherit an expensive
keyword's bid ceiling. Isolating the top 20 into single-keyword ad groups
lets each pace independently. Peel these off gradually (one SKU's top
keywords per week) — a bulk restart clears Amazon's learning phase.

**Dayparting / hour-of-day bid adjustment.** Many B2C verticals see 3–5×
ACOS variance by hour of day; flat bidding pays the worst hour's
economics to win the best hour's buyer. Pass: hourly ACOS variance ≤40%,
or bid modifiers already applied. Fix: reduce bids ~30% in the worst
quartile of hours, raise in the best quartile.

**Sponsored Brands video on hero ASINs' branded terms.** SB-video is the
cheapest video ad real estate on Amazon and defends branded search share
while lifting new-to-brand percentage. Target: ≥30% impression share on
each hero ASIN's top branded terms (a stronger bar of ≥60% is achievable
once the campaign has matured). Requires Brand Registry.

**Sponsored Display retargeting on detail-page viewers.** SD retargeting
clicks against an already-viewed-PDP audience run 3–5× cheaper than SP for
the same cohort. Set the audience to "viewed the brand in the last 30
days," excluding anyone who already purchased in that window. Use a
window of at least 7 days — a window of 3 days or less misses the natural
click-to-conversion lag.

**Branded-query dependence (share-of-voice).** Compute branded impressions
÷ total impressions for the ASIN. Above ~85% branded means the account is
harvesting existing demand rather than acquiring new customers — non-
branded search share is the real growth engine. Below ~70% is healthy.
Fix: shift budget toward non-branded category head terms and work those
terms into the listing itself.

**Branded vs. non-branded TACoS split.** Branded-keyword spend should be
≤5% of total ad spend, since organic should be winning most branded
searches for free. Above 15% branded spend usually means paying for
traffic organic would capture anyway — reasonable only when a competitor
is actively bidding on the brand name.

**Coupon / Lightning Deal cadence.** Amazon's best-seller-rank algorithm
rewards sales-velocity spikes. Each hero SKU should run at least one
coupon or Lightning Deal per month; a gap over 60 days on a hero SKU is a
missed opportunity to protect rank between organic pushes.

**Negative product targeting on non-converting competitor ASINs.** SP
auto and category-targeting campaigns often spend on competitor product
pages that never convert. A weekly review that adds a negative-product
target for any competitor ASIN with ≥10 clicks and 0 orders typically
recovers 10–25% of otherwise-wasted spend.

**ASIN targeting depth: conquest / defensive / cross-sell.** Each hero SKU
should have separate campaigns for conquesting competitor ASINs,
defending the brand's own related ASINs, and cross-selling complementary
products — because bid and budget rules need to diverge by mode. Lumping
all ASIN targets into one bucket prevents that divergence.

**Placement bid modifiers (Top-of-Search / Product Page / Rest-of-
Search).** Tune each placement toward its own optimum
(`revenue_per_click × target_ACOS`) once a placement has ≥30 clicks of
signal. Top-of-Search is generally the highest-intent surface and often
merits a +50–100% modifier when its ROAS beats brand average; Rest-of-
Search rarely deserves a positive lift.

**Campaign-carried-by-one-keyword risk.** If a single keyword or target
drives more than 70% of a campaign's revenue with 5 or fewer keywords in
the campaign, that's a concentration risk, not a success — isolate the
top performer into its own ad group at a higher bid and let the rest of
the campaign refresh or pause, rather than letting the whole campaign's
fate ride on one term.

**Suggested-bid drift.** Amazon periodically publishes a suggested-bid
range per keyword. A proven Exact-match converter that has drifted more
than 50% below the current suggested-bid median for an extended period is
quietly losing impression share; climb toward the suggested median in
capped increments.

**Budget pacing.** Yesterday's spend should sit within roughly 0.4–1.5× of
the trailing 7-day average, and the trailing 3-day average shouldn't fall
below 0.4× of the 7-day average. A day at more than 2× the 7-day average
is urgent over-pacing (budget likely to run out mid-day, missing the
highest-conversion hours); sustained under-pacing below the 0.4× floor
usually means a bid or targeting problem, not a lack of demand.

**Sponsored Brands store-spotlight + lifestyle creative.** SB Lifestyle
ads linking into a keyword-organized brand store convert 1.4–1.8× a
standard SB ad. Each hero SKU should have a corresponding store sub-page
linked from its SB creative. Requires Brand Registry, A+ Premium content,
and a live brand store — treat as a one-time setup investment, not a
recurring task.

---

## Extended checklist — listing / SEO depth

**Title structure.** Brand name in the first 30 characters, primary
keyword within the first 100, total length under 200 characters, no
`||`-style separators or ALL-CAPS "screaming." Recommended pattern:
`[Brand] [Primary Keyword] [Variant/Size] [Differentiator] [Pack/Quantity]`.
Brand-first placement both improves click-through on branded search and
makes it harder for a competitor to hijack the branded query with paid
placement.

**Bullet points.** Exactly 5 bullets, each ≤200 characters (over 250
truncates on mobile, where 70%+ of Amazon traffic lands), each led with
customer benefit rather than a bare feature ("Helps with Y because of X,"
not "Made with X"). Amazon's own A/B testing shows benefit-led copy
out-converting feature-led copy by roughly 18–30%.

**Description / A+ Content depth.** A+ live with at least 5 modules
including a comparison chart (which specifically discourages cross-
shopping), or — absent Brand Registry — a plain description of at least
500 characters. Under 200 characters with no A+ is a fail.

**Backend search terms.** Use at least 200 of the 250-byte budget, with no
duplication of title/bullet content, no brand name (waste of a scarce
slot), and only one form of any plural. Backend terms are Amazon's only
non-visible indexing signal — leaving budget unused is SEO real estate
left on the floor.

**Indexing check.** Each hero SKU's top 5 target keywords should return
that ASIN somewhere in the organic top 50 search results. A keyword the
listing isn't indexed for can never convert organically — paying ad
budget to chase it is throwing money at a structural gap. Fix by
confirming the keyword actually appears in title, bullets, or backend
terms; adding it to backend terms is the lowest-friction fix.

**Best-Seller-Rank (BSR) trend.** BSR should be flat or improving over a
rolling 4-week window. A decline of more than 25% often precedes Buy Box
loss or a competitor breakout, and is worth investigating (sales velocity
drop, out-of-stock event, price change, or a competitor promotion) before
it compounds.

**Star rating and review count.** Every hero SKU should carry at least a
4.0 average with at least 20 reviews. Below 4.0 stars cuts conversion by
roughly 30–50% — ad spend just amplifies the bleed rather than fixing it.
4.0+ with fewer than 20 reviews is a social-proof gap, not a rating
problem. Fix by enrolling in Amazon Vine and addressing the themes
surfacing in the lowest-rated recent reviews.

**Q&A presence.** At least 3 answered questions visible on every hero
product page — Q&A is one of the top-two most-scanned elements on mobile
product pages, and its absence quietly signals "unsupported product."
Seed it via buyer-seller messaging, then answer publicly.

**Variation family grouping.** All product variants (size, color, etc.)
should share one parent ASIN so reviews and BSR roll up together. An
orphaned variant fights for rank starting from zero. Fixing this requires
a catalog correction through Seller Central, typically with about a
week's turnaround.

**Browse-node / category classification.** A hero SKU's primary
classification should match the category real buyers would search in —
verified by checking where its top search terms actually map. Wrong
classification (e.g. a pet-health product classified under Beauty) makes
BSR meaningless for competitive comparison and can cause Amazon's
recommendation engine to misroute cross-sells.

**Refund-rate trend.** A rising refund rate (units refunded ÷ units
ordered over a trailing window) is often the earliest quality signal
Amazon exposes — it tends to precede a review-rating decline by weeks.
Roughly: under 5% is healthy, 5–10% warrants attention, over 10% is a
fail. When it rises, triage the lowest-rated recent reviews for a
recurring theme and verify listing claims match what actually ships.

**Out-of-stock cover.** Inventory should cover at least 14 days of
trailing sales velocity; under 7 days is a fail. Going out of stock
auto-pauses ads and decays organic rank — every day out of stock costs
roughly a week of rank-recovery time afterward. If a replenishment lead
time will exceed current cover, raising price ~10% to slow the burn rate
while restock is in transit is a reasonable stopgap.

**Unit-session percentage (conversion rate) floor.** For any ASIN with at
least 50 sessions in a trailing 28-day window, conversion rate should be
at or above 10%; 5–10% is a warning, below 5% is a fail (meaningful
traffic is reaching the page and not buying). Below the 50-session sample
size, treat the check as not-yet-gradable rather than forcing a verdict on
noise. When it fails, work the cheapest lever first: price, main image
and gallery quality, star rating/review volume, A+ content and bullets,
then ad keyword relevance.

---

## What this handbook deliberately excludes

- **Amazon DSP (Demand-Side Platform).** DSP is its own surface with a
  distinct fee structure and buying model; most brands selling on Amazon
  never touch it. Treat it as a separate specialty if a brand actually
  runs DSP.
- **Marketplace expansion decisions.** Whether to register in an
  additional country marketplace is a business decision, not an audit
  finding — it only shows up here as a secondary condition under Brand
  Registry status.
- **Subscribe & Save adoption.** That's a subscription-toggle decision
  tied to listing setup, not an ads concern.
- **Vendor Central-specific mechanics.** Vendor accounts buy via
  purchase orders rather than retail arbitrage and have meaningfully
  different levers; this handbook assumes a Seller Central / first-party-
  seller account.

---

## How to use this in an audit

1. Pull the account's campaign structure, keyword/negative lists, Search
   Term Report, and listing content for the top-spend SKUs (start with the
   top 10 by ad spend — that's where leverage concentrates).
2. Grade each check pass/warning/fail against the thresholds above. Where
   data genuinely isn't available or sample size is too small, mark it
   n/a rather than guessing.
3. Compute category sub-scores and the final weighted health score; assign
   the letter grade.
4. Surface every critical-check result regardless of pass/fail, and lead
   the findings with any critical FAIL.
5. Order fix recommendations by (severity × weight) first, then by
   fix_effort (low-effort/high-impact fixes first) — a 6-campaign-spoke
   gap and an OOS cover, for instance, both outrank a Q&A gap even though
   all three might be "high" severity in isolation, because the former
   two cap scale account-wide.
