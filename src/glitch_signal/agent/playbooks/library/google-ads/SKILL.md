---
name: google-ads
description: Google Ads handbook covering account/campaign strategy by budget tier, bidding strategy selection, Performance Max structure, RSA + match-type best practices, conversion tracking, negative-keyword frameworks, 2026 compliance rules, an optimisation cadence, a Health Score audit rubric, and a keyword-research method via Keyword Planner. Use when launching, auditing, or scaling a Google Ads account, or when running keyword research for a new or existing brand.
---

# Google Ads Handbook

## When to Use This Skill

Use this skill when working on a brand's Google Ads account:

- Deciding which campaign type / bidding strategy fits a given budget
- Auditing an existing account (structure, bidding, tracking, negatives, compliance)
- Structuring or troubleshooting a Performance Max campaign
- Writing/reviewing RSAs, match types, or a negative-keyword list
- Running keyword research (via `KeywordPlanIdeaService` or equivalent) for a new market/SKU
- Computing a Google Ads Health Score for an audit deliverable

Every rule below carries a **stable check-ID** (`G01`–`G75`) so an audit can cite which specific
rule a campaign violates. Numeric thresholds are sourced from public benchmarks; where no
credible benchmark exists, the field reads "pull from Keyword Planner / first-party data."

Review cadence: **quarterly** — Google Ads policy and product surfaces churn fast. Last
reviewed: 2026-04-30. Source synthesis: Google Ads Help, Search Engine Land, Search Engine
Journal, WordStream, Optmyzr, smarter-ecommerce, Solutions 8, Storegrowers, Bigflare, Triple
Whale, ALM Corp, groas.ai, Lunio, Pattern AU, Workshop Digital, Adalysis.

---

## Part 1 — Strategy Playbook

**Calibrated for tight budgets** ($10–$100/day, $300–$3,000/mo) — the band where most cold-start
accounts sit. Numeric thresholds should be treated as defaults; override with a brand's own data
where it contradicts generic guidance below.

### I. Operating context — when each budget tier applies

| Attribute | Range this playbook covers |
|---|---|
| Vertical | D2C e-commerce on Shopify (or equivalent) |
| Daily budget | $10 – $100 USD-equivalent |
| Monthly budget | $300 – $3,000 |
| Stage | Cold start through first ~$5k cumulative spend |
| Primary KPI | True ROAS (Google Ads spend ÷ first-party-attributed revenue), not Google's reported number |
| Secondary KPI | CPA on Add-to-Cart when purchase volume is sub-15/mo |

Above **$3k/mo and post-cold-start**, move to the upgrade path (PMax + Search + Brand defence
hybrid) described in Part 2.

### II. Budget-to-campaign-type matrix

The single most expensive cold-start mistake is using the wrong campaign type for the budget.
PMax's stated minimum is **30–50 conversions/month** to optimise; a $10/day budget can't get
there.

| ID | Monthly budget | Recommended primary | Forbidden / wasteful |
|---|---|---|---|
| **G01** | < $300 | 1× Search Brand defence + 1× tightly-themed non-brand Search (Manual CPC) | PMax (no signal); Demand Gen (needs ≥$100/d per Google) |
| **G02** | $300 – $1,000 | Search Brand + Search non-brand (Exact + Phrase) | PMax; Broad match without Smart Bidding |
| **G03** | $1,000 – $3,000 | Brand Search + (Standard Shopping OR single PMax) | Two PMax campaigns (budget starvation, asset-group cannibalisation) |
| **G04** | $3,000+ | Hybrid: Brand Search + Non-brand Search + 1× PMax with brand exclusion + (optional) Standard Shopping for top SKUs | Demand Gen unless purely awareness-funded |

**G05** — Always run **Brand defence**, even on $10/day. Brand keywords convert 2–4× non-brand
at avg ROAS ~12.99× vs ~0.68× for generic. Skipping it lets competitors squat the brand name for
pennies per click.

### III. Bidding strategy framework

**Strategy → conversion-floor map (G06–G10)**

| ID | Strategy | Use when | Min conv/30d |
|---|---|---|---|
| **G06** | Manual CPC | New account, cold start, brand defence, regulated vertical | 0 (no minimum) |
| **G07** | Maximize Conversions (no tCPA) | Stable similar-value conversions; want to spend full budget | ≥15 stable |
| **G08** | Maximize Conversion Value (no tROAS) | E-com with varying basket values | ≥15–30 |
| **G09** | tCPA | Stable CPA target; goal-based reporting | Google floor: 0; best practice 15+, ideally 30 |
| **G10** | tROAS | Value reporting accurate ≥4 weeks; ≥50 conv/campaign before applying | 50+ |

**Operating rules (G11–G15)**

- **G11** — Smart Bidding learning phase is **1–2 weeks** and "donates" 30–50% of spend during
  it. Don't change bid strategy in week 1.
- **G12** — Below 15 conv/mo on Purchase: temporarily promote a micro-conversion (Begin
  Checkout) to Primary so the algorithm has signal. Demote once Purchase volume builds.
- **G13** — **Enhanced CPC (ECPC) sunset week of 31 Mar 2025.** Campaigns not migrated default
  silently to Manual CPC. Audit any campaign still claiming "Enhanced CPC."
- **G14** — Manual CPC remains valid in 2026 for tight budgets, niche markets, fixed CPA
  ceilings, and regulated verticals. Don't dismiss it as deprecated.
- **G15** — Use **bid caps** on tCPA to prevent runaway clicks during learning. Apply bid floors
  only after a 50+ conversion pool.

### IV. Performance Max specifics (only relevant ≥$1k/mo)

If the account isn't running PMax, skip this section.

**Structure (G16–G20)**

- **G16** — **3–7 asset groups per campaign.** Segment by product category or theme, NOT by
  audience signal — duplicate-by-audience asset groups converge to the same average and waste
  budget.
- **G17** — Each PMax campaign needs **20–30 conv/mo**; under that the algorithm guesses. Don't
  run two PMax campaigns on a tight budget — neither hits the learning threshold.
- **G18** — Audience signals are **hints, not hard targeting** — PMax expands beyond them. Stack:
  1× Customer Match (real buyers) + 1–2 in-market + 1 custom segment from competitor
  URLs/keywords.
- **G19** — Search themes raised from 25 → **50 per asset group** in 2025. Treat as "broad match
  equivalent" for PMax; pair with a negative-keyword list (10,000 cap at campaign level) to keep
  it on rails.
- **G20** — Final URL expansion is ON by default. Turn OFF when: only one converting page,
  branded campaign, regulated content, or past spend leaked to /blog or /about. Prefer **Final
  URL exclusion** to block specific paths instead of disabling expansion entirely.

**Brand handling (G21–G22)**

- **G21** — **Always exclude brand from PMax** if a dedicated Brand Search campaign also runs.
  The brand list catches misspellings + foreign scripts that negative keywords miss. Without
  exclusion, PMax double-counts brand purchases and inflates reported ROAS.
- **G22** — Brand exclusion is available at campaign level + account-level brand list. Use
  account-level when running multiple PMax campaigns under one brand-defence umbrella.

**Account-level negatives starter list (G23)**

Account-level negatives cap at **1,000 keywords**. Reserve for "would never want to show,
anywhere, ever":

```
Brand safety:    scam, fraud, torrent, crack, hack, illegal, adult, porn, xxx
Job intent:      jobs, careers, hiring, salary, vacancy, recruitment, internship
Pirated/used:    used, second hand, refurbished, knock off, replica, fake, dupe
Education only:  course, tutorial, how to make, DIY, recipe, homemade
Help/complaint:  refund, return, complaint, lawsuit, scam alert
```

Caveat: account-level negatives apply to all future campaigns — skip "free" if a "free shipping"
or "free trial" campaign might launch later.

**Feed + reporting (G24–G25)**

- **G24** — PMax Shopping placements pull from the Merchant Center feed; feed quality is
  upstream. Optimise titles (brand+category+attributes), populate GTINs, use high-quality
  images, keep price/availability accurate. Bad feed = bad PMax. Note the **Merchant API
  migration**: beta deadline Feb 28 2026; Content API sunset Aug 18 2026.
- **G25** — Read PMax performance via the **Insights tab + channel performance report**
  (Search/Shopping/YouTube/Display/Discover/Gmail split) to spot YouTube/Display waste.

### V. Search campaign specifics

**RSA (G26–G30)**

- **G26** — Up to 15 headlines + 4 descriptions; aim for **6–10 strong headlines**. Fewer
  high-quality variants beat stuffing weak ones.
- **G27** — **Pinning trade-off**: pinning one headline cuts testing potential ~75% and can drop
  Ad Strength from Excellent to Poor. Workaround: pin **multiple variants** to the same position
  (e.g. 3 headlines pinned to position 1) to preserve testing.
- **G28** — **Poor → Excellent Ad Strength: +15% clicks and conversions** (Google's stated
  number). Use as a diagnostic, not gospel — many "Excellent" ads underperform "Good" ones.
- **G29** — **Always run all three asset types** — sitelinks, callouts, structured snippets.
  Google explicitly favours ads with multiple asset types. Stated lifts: callouts ~10% CTR
  baseline, up to +52% CTR + 40% CR for trust-themed callouts; structured snippets +8% CTR /
  +1.3% conv-rate on branded terms.
- **G30** — For D2C ecom, a **landing page wins over a lead-form extension** — the goal is
  ATC/checkout, not an email. Reserve lead-form for content offers/quizzes only.

**Match types (G31–G33)**

- **G31** — Three match types remain: **Broad, Phrase, Exact**. Broad Match Modifier is gone
  (since 2021); existing BMM is treated as expanded Phrase.
- **G32** — For tight budgets: **Exact + Phrase by default**. Test Broad only on a separate
  campaign with strong negatives + Smart Bidding. Broad on tight budgets without Smart Bidding
  burns cash.
- **G33** — **AI Max for Search** (GA Q3 2025) — a one-click toggle on Search campaigns.
  Google's stated lift: **+14% conversions at similar CPA** on average; **+27% on campaigns
  still mostly using exact/phrase**. Brand controls live in the AI Max settings panel. Worth
  testing on Brand defence + Exact-heavy campaigns once they have ≥30 conv/mo.

**Brand defence specifics (G34–G35)**

- **G34** — Bidding: **Manual CPC preferred** for control on Brand defence; tROAS only if
  ≥15–50 conversions/mo specifically on brand.
- **G35** — Negatives on Brand defence: `jobs, careers, hiring, login, sign-in, cancel, refund,
  complaints` plus any review-only intent terms specific to the brand.

### VI. Conversion tracking + measurement

**Source of truth (G36–G40)**

- **G36** — **Use the Google Ads native tag (gtag.js or via GTM) as the primary conversion
  source for Smart Bidding.** Use GA4 key events for analytics, audience building, cross-channel
  reporting.
- **G37** — **A 5–15% gap is normal** between GA4 and Google Ads conversion counts. Reasons:
  counting model (Ads can count multiple conversions per click; GA4 counts events), date
  attribution (Ads attributes to click date, GA4 to conversion date), and attribution model
  (Ads = last-click or full credit; GA4 = data-driven multi-touch). Don't import GA4 conversions
  into Google Ads if native conversions are already firing — that double-counts.
- **G38** — **Enable Enhanced Conversions for Web** (gtag, GTM, or API). Google states ~17% avg
  lift; advertisers typically see 5–10%, 16–33% at the top of the range; it's required for full
  Smart Bidding signal in cookie-restricted regions (EEA + Safari).
- **G39** — **Data-driven attribution is default and recommended for 2026.** Last-click is only
  useful for diagnostic comparison. Position-based / time-decay / linear are deprecated paths.
- **G40** — **Consent Mode v2 required since March 2024** for EEA + UK traffic (deadline
  reinforced July 21 2025). Adds `ad_user_data` and `ad_personalization` parameters.
  Non-compliance means loss of EEA measurement signal + remarketing eligibility.

**Goal categories + remarketing (G41–G45)**

- **G41** — **Primary** = biddable, appears in the "Conversions" column. **Secondary** =
  observation only, in "All conversions," NOT used for bidding (exception: a secondary goal
  inside a custom goal IS biddable).
- **G42** — For tight-budget D2C: **Primary = Purchase**. Secondary = Begin Checkout, Add to
  Cart, View Item. If sub-15 conv/mo on Purchase, temporarily promote Begin Checkout to Primary
  (see G12).
- **G43** — **Customer Match minimum: 100 active matched users per network** for active
  targeting. Recommend ≥5,000 to ensure enough matched-active users. List members must be
  added/updated within the last **540 days** to stay eligible.
- **G44** — **View-through conversions are excluded from the "Conversions" column EXCEPT** for
  PMax (store goals), App, and Demand Gen. For ecom PMax, VTCs sit in "All conversions" only and
  won't inflate Smart Bidding optimisation.
- **G45** — **Opt out of auto-applied recommendations**, especially "remove redundant
  keywords" — it strips brand/PMax-protection negatives. Manage via Recommendations →
  Auto-apply settings, or the API's `RecommendationService.ApplyRecommendation` /
  `DismissRecommendation` for per-type control.

### VII. Negative keyword framework

**Standard ecom starter list (G46)**

```
Universal:    free, freebie, jobs, career, hiring, salary, vacancy, recruitment,
              crack, hack, torrent, pirate, illegal, scam, fraud, adult, porn, xxx,
              meme, joke, image, photo, gif, wallpaper
D2C-specific: wholesale, bulk, distributor, supplier, b2b, reseller,
              used, second hand, refurbished, replica, fake, knockoff, dupe,
              complaints, lawsuit, refund, return, cancel
Research:     how to make, recipe, DIY, homemade, do it yourself,
              tutorial, course, definition, meaning, what is
```

**Vertical: pet / supplement (G47)**

```
recipe, DIY, homemade, dosage, how much, how to give, side effects, overdose
vet near me, veterinarian, veterinary clinic
prescription, Rx, pharmacy
food                   (only if you sell supplements not food)
toxic, poisoning, dangerous
petco, chewy, amazon, flipkart    (skip if you run a marketplace strategy)
```

**Vertical: apparel / dropship (G48)**

```
review, vs, comparison, alternatives    (skip if value-discovery is desired)
return, refund, exchange policy
size chart, measurement guide, how to measure
```

**Hierarchy (G49–G51)**

- **G49** — **Account-level** (1,000 cap): "would never want to show, ever." Skip terms that
  might fit a future campaign (e.g. "free shipping" promo).
- **G50** — **Campaign-level** (PMax: 10,000 post-March 2025; Search lists: ~5,000): the
  primary control surface.
- **G51** — **Ad-group level**: nuance — e.g. cross-product cannibalisation prevention.

**Brand-bidding negatives (G52–G55)**

- **G52** — Add the **brand name + variants/misspellings** as negatives in non-brand Search to
  prevent overlap with the dedicated Brand defence campaign.
- **G53** — Add **competitor brands as negatives** in non-brand Search if bidding on
  competitors isn't wanted. Layer competitor terms into a separate competitor-conquest campaign
  if it is.
- **G54** — For PMax, a brand-exclusion list beats negative keywords for blocking own/competitor
  brand — it catches misspellings and other scripts. See G21.
- **G55** — Audit account-level negatives quarterly for over-exclusion — check for legitimate
  keywords that started getting blocked.

### VIII. Compliance + policy (2026)

**Healthcare / supplement (G56–G62)**

- **G56** — **Healthcare and Medicines policy** is the gating policy (updated June, July,
  October 2025). Animal supplements fall under it.
- **G57** — **Supportable claims only**: structure/function ("supports joint mobility"), not
  disease ("cures arthritis," "treats anxiety").
- **G58** — Disclaimers: include ingredients, usage, warnings, "not intended to
  diagnose/treat/cure" on the landing page.
- **G59** — Prescription animal medications: certified advertisers only. Non-prescription pet
  supplements are allowed but **subject to all healthcare-claims rules**. Dietary supplements
  with active pharma ingredients get disapproved.
- **G60** — **Personalised advertising is restricted on health categories.** Behavioural
  targeting around medical conditions (anxiety, joint pain) is disallowed; in-market audiences
  for a general category like "pet supplies" remain usable.
- **G61** — For markets with local supplement regulation (e.g. India's OTC/AYUSH regime):
  expect manual policy review on first ad submission; keep license + manufacturer documentation
  ready.
- **G62** — For markets requiring healthcare-advertiser identity verification (e.g. UAE):
  expect a **1–3 week typical approval cycle**; clearly disclose business name + license on the
  landing page.

**General + Shopping policy (G63–G65)**

- **G63** — Google has been ramping enforcement on Shopping eligibility for healthcare;
  subscription health offerings face extra scrutiny.
- **G64** — Animal cruelty content is disallowed; image moderation auto-checks apply — relevant
  to creative selection for ad assets.
- **G65** — Keep a compliance binder per brand: license docs, claim substantiation, disclaimer
  text. Re-verify quarterly.

### IX. Optimisation cadence

**First 7 days (G66–G68)**

- **G66** — Daily check: ads approved, impressions serving, daily spend pacing. Don't make major
  changes — no data yet.
- **G67** — Catch disapprovals, billing failures, tracking failures.
- **G68** — **Don't change bid strategy in week 1** — Smart Bidding learning takes 1–2 weeks.

**Days 7–30 (G69–G71)**

- **G69** — Days 7–14: aggressive search-term mining. Add 15–20 negatives.
- **G70** — Days 14–21: review RSA/asset performance — replace "Low" rated assets.
- **G71** — Days 21–30: if ≥15–30 conversions have accrued, consider switching from Manual CPC
  to Maximize Conversions. Allow 10–14 days for learning to complete after the switch. Stated:
  aggressive first-30-day optimisation correlates with **2.3× better performance in months 3–6**
  vs set-and-forget.

**Weekly checklist (G72)**

1. Search terms report — add negatives for waste; promote new winners to keywords.
2. RSA asset performance — replace Low-rated.
3. Budget pacing — any campaign with "lost impression share due to budget"? Reallocate.
4. Disapprovals + policy alerts.
5. Bid strategy health — tCPA/tROAS realised vs target.
6. PMax Insights tab — search themes, audience signals, asset rotation.
7. Bid adjustments where Manual CPC: high-CTR/low-conv keywords down, high-conv up.

**Quarterly checklist (G73–G75)**

- **G73** — Auction Insights — impression share + position vs competitors. Account structure
  review — fold campaigns generating <5 conv/quarter, split high-spend campaigns >60% IS.
- **G74** — Customer Match refresh (≥100 records, refresh within 540 days). Negative keyword
  audit. Conversion action audit (Enhanced Conversions still firing? GA4↔Ads gap >15%?). Feed
  audit (titles, GTIN, image quality).
- **G75** — Test allocation: **70% proven / 20% optimisation / 10% new tests** rule.

### X. Health Score categories (Google Ads audit)

For audit-tool parity with a Meta Health Score, compute a 0–100 Health Score with four 25-pt
categories, each driven by the check IDs above:

| Category | Weight | Driving checks |
|---|---|---|
| **Account structure** | 25% | G01–G05, G16–G17, G34 — right campaign type for budget, no two-PMax-on-tight-budget, brand defence present |
| **Bidding + budgets** | 25% | G06–G15, G73 — strategy matches conversion volume, no orphan ECPC, sane bid caps, no impression-share waste |
| **Tracking + measurement** | 25% | G36–G45 — native tag primary, Enhanced Conversions live, Consent Mode v2 in EEA, no auto-apply lobotomising negatives |
| **Negatives + compliance** | 25% | G46–G65 — universal + vertical negatives applied, brand exclusion on PMax, healthcare claims compliant, license docs filed |

Score bands: 80+ healthy · 60–79 needs work · <60 burning money. Each finding should cite a
`Gxx` check ID for week-over-week delta tracking.

---

## Part 2 — Keyword Research Method

A repeatable method for pulling and reading a keyword shortlist for a new market or product,
using `KeywordPlanIdeaService.GenerateKeywordIdeas` (or the Keyword Planner UI equivalent).
Refresh cadence: **quarterly** (per G75) or whenever a new hero SKU launches.

### Pull method

1. Seed with the storefront URL plus **5–6 product/category keyword seeds** covering the core
   category, a specific use-case, an ingredient/material, and a symptom/benefit phrase.
2. Pull per target market/language separately — search volume, competition, and bid ranges vary
   sharply by geography even for the same product.
3. Sort by average monthly searches; take the top ~30 as the working shortlist.
4. Cluster the shortlist into 3–5 **theme groups** (e.g. "joint health," "general supplements,"
   "calming") — this becomes the ad-group / search-theme structure once the non-brand campaign
   is enabled (see G02–G03).

### Reading the pull

- **High absolute volume + workable bid range** → the market supports both a brand-defence and
  a non-brand Search layer; size the non-brand daily budget off the combined cluster volume
  (e.g. a cluster totalling ~3,500 combined monthly searches at $0.05–$1.20 CPC comfortably
  supports tens of generic clicks/day).
- **Thin volume** (top non-brand term topping out at a couple hundred searches/mo) → Search
  can't spend a meaningful budget; the market's primary paid surface should be **PMax +
  Shopping** instead, since Shopping placements pull from the Merchant Center feed and don't
  require owning keyword inventory directly. Size Search (if run at all) very small (a few
  dollars/day) and delay non-brand until Search volume can support it.
- **"No bid signal" rows** (LOW competition, no bid range returned) are still useful for the
  negative-keyword list and for gauging demand shape, even though they won't carry paid spend.

### Compliance screening on the pull

Cross-check every suggested keyword against the healthcare/compliance rules in Part 1 (G56–G57)
before adding it to a shortlist. Google's suggestion algorithm will surface disease/treatment
claims (e.g. "arthritis," "pain relief," "anxiety") that the account is not allowed to bid on or
reference in ad copy for a supplement or health-adjacent product. Flag these out of the
shortlist and add them to the vertical negative-keyword list (G47) so the non-brand campaign
doesn't accidentally match them via broad/phrase.

### Deliverable shape

For each target market, produce:

1. A ranked keyword table (keyword, searches/mo, competition, bid range).
2. A one-line read on what the volume implies for campaign-type choice (Search-viable vs
   PMax/Shopping-primary).
3. Cluster groups mapped to a future ad-group/search-theme structure.
4. A compliance-flagged exclusion list, cross-referenced to the negative-keyword vertical list.
