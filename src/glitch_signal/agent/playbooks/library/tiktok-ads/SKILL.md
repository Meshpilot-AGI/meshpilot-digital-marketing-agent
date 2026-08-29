---
name: tiktok-ads
description: TikTok Ads audit checklist and best-practice catalog covering tracking (Pixel/Events API), creative (hook rate, native format, UGC, refresh cadence), structure/bid, and audience — with a weighted Health Score formula and archetype filtering. Use when auditing a TikTok ad account or deciding whether a brand archetype should be running TikTok paid at all.
---

# TikTok Ads Audit Checklist

Targets the archetypes that actually run TikTok paid: D2C e-commerce, subscription consumer,
creator/media, and mobile-app. B2B SaaS and lead-gen financial brands almost never see ROI on
TikTok — filter every check out for them; that's correct behavior, not a gap in the catalog.

TikTok's leverage is **creative-first**: the algorithm rewards hook-quality and completion-rate
more than any other paid surface. A TikTok account with bad creatives loses regardless of bid or
structure tuning. Health Score weights reflect this: **Creative 40% · Tracking 25% · Structure
20% · Audience 15%.**

Sources distilled in the field: TikTok's own Smart Creative Solutions playbook, Spark Ads
best-practices guides, official TikTok Pixel + Events API docs, Foxwell Digital, Common Thread
Collective, Triple Whale on TikTok attribution, Andrew Faris, TikTok Creator Marketplace + UGC
platform research.

## Schema

Each check carries:

- `id` — `T01`+ stable identifier, never reused.
- `applies_to_archetypes` — defaults to `[d2c_ecom, subscription_consumer, creator_media,
  mobile_app]`; some checks tighten further (subscription-only, app-only, creator-only).
- `primary_metric_kind` — resolves per archetype: `cost_per_purchase` for D2C,
  `cost_per_subscriber` for creator, `cost_per_install_d7_retained` for mobile_app.

Critical checks (severity 5.0×) cap their category sub-score at 50 on FAIL.

---

## Category A — Tracking (25% weight)

### T01 · TikTok Pixel installed + base PageView firing
- weight: 10 · severity: **critical** · fix_effort: low
- applies_to_archetypes: [d2c_ecom, subscription_consumer, creator_media, mobile_app]
- pass: TikTok Pixel base code installed; PageView fires on every page; confirmed via TikTok
  Events Manager → "Active"
- warning: PageView fires <90% of pages OR pixel ID mismatch
- fail: pixel inactive OR not installed
- fix: install via TikTok Business Center → Pixel → manual or partner (Shopify / Webflow / Wix
  have native connectors)

### T02 · Events API (server-side) active
- weight: 9 · severity: **critical** · fix_effort: medium
- applies_to_archetypes: [d2c_ecom, subscription_consumer, creator_media]
- pass: server-side Events API mirroring ≥0.7× of pixel events for the primary conversion;
  events share `event_id` for dedup
- warning: partial (0.4–0.7× ratio) OR no dedup ID
- fail: no server-side events while ad delivery is present
- rationale: TikTok's iOS / cookie-blocker loss is comparable to Meta's; Events API is the
  recovery path
- fix: enable via TikTok Events Manager → Events API; or use a Shopify / Stape.io / RudderStack
  connector

### T03 · Standard events present
- weight: 6 · severity: high · fix_effort: low
- applies_to_archetypes: [d2c_ecom, subscription_consumer]
- primary_metric_kind: cost_per_purchase
- pass: ViewContent + AddToCart + InitiateCheckout + CompletePayment firing in 7d (TikTok's
  funnel parallel to Meta)
- warning: 3 of 4
- fail: ≤2
- fix: enable in the Shopify / WooCommerce TikTok connector

### T04 · App-event SDK + measurement partner integrated
- weight: 9 · severity: **critical** · fix_effort: high
- applies_to_archetypes: [mobile_app]
- primary_metric_kind: cost_per_install_d7_retained
- pass: AppsFlyer / Adjust / Singular / Branch integrated; TikTok configured as a partner;
  install + post-install events forwarding
- warning: install forwarding works but no post-install events (D1 / D7 retention / IAP)
- fail: no MMP integration — TikTok cannot optimize app campaigns past raw CPI
- rationale: a mobile app needs an MMP for SKAN + iOS install attribution; without it, TikTok
  mobile-app campaigns are flying blind
- fix: pick an MMP, connect TikTok via the MMP's TikTok adapter

### T05 · UTM template populated
- weight: 4 · severity: medium · fix_effort: low
- applies_to_archetypes: [d2c_ecom, subscription_consumer, creator_media]
- pass: account-level URL parameters set — `utm_source=tiktok`, `utm_medium=paid`,
  `utm_campaign={{campaign_id}}`, `utm_content={{ad_id}}`
- warning: present but campaign or creative variable missing
- fail: no template — clicks reach the site without analytics-stack attribution
- fix: TikTok Ads Manager → Account settings → URL tagging template

---

## Category B — Creative (40% weight)

### T20 · Native-format creative (not repurposed assets from other platforms)
- weight: 10 · severity: **critical** · fix_effort: high
- applies_to_archetypes: [d2c_ecom, subscription_consumer, creator_media, mobile_app]
- pass: ≥80% of active spend on creatives shot vertical 9:16 with on-platform aesthetics
  (handheld, voice-over, sound-on, native text overlays / TikTok captions)
- warning: 50–80% native; 20–50% repurposed
- fail: <50% native — repurposed feed/TVC creatives carry the account; CPM inflates 2–4× and CVR
  collapses
- rationale: TikTok's algorithm penalizes "made for TV" creatives; the platform is built around
  skin-in-the-game native content
- fix: brief native shoots; convert winners from other platforms only if a native re-cut tests
  positive

### T21 · 3-second hook strength
- weight: 9 · severity: **critical** · fix_effort: medium
- applies_to_archetypes: [d2c_ecom, subscription_consumer, creator_media, mobile_app]
- pass: top-spend creatives hit ≥50% 3-second view rate (TikTok's "Hook Rate")
- warning: 30–50%
- fail: <30% — feed-scroll kills delivery within 24h regardless of back-half quality
- rationale: the algorithm's first scoring decision is whether to serve the second 3 seconds;
  under-30% Hook Rate caps reach
- fix: open with motion / pattern-interrupt / direct address; cut the first 3 seconds
  aggressively; test 4–6 hooks per concept

### T22 · 6-second View Rate (Show Rate) gate
- weight: 7 · severity: high · fix_effort: medium
- applies_to_archetypes: [d2c_ecom, subscription_consumer, creator_media, mobile_app]
- pass: top-spend creatives hit ≥25% 6-second view rate
- warning: 15–25%
- fail: <15% — story collapses past the hook
- fix: trim mid-section; deliver the value prop by 5s

### T23 · UGC / creator-style creative tested
- weight: 8 · severity: high · fix_effort: high
- applies_to_archetypes: [d2c_ecom, subscription_consumer, creator_media, mobile_app]
- pass: ≥40% of active creatives are UGC or creator-style (not studio-shot brand content); ≥1
  Spark Ad active (boosting organic / creator content)
- warning: UGC tested but <20% of spend
- fail: 0 UGC / Spark — studio creatives consistently underperform UGC on TikTok at 2–3× the CPM
- rationale: TikTok-native UGC + creator content outperforms studio on every metric; the
  platform is creator-driven
- fix: brief 5+ UGC variants per concept via TikTok Creator Marketplace or Backstage / Insense /
  Trend.io

### T24 · Music + sound-on design
- weight: 4 · severity: medium · fix_effort: medium
- applies_to_archetypes: [d2c_ecom, subscription_consumer, creator_media, mobile_app]
- pass: every active creative carries trending or licensed music; voice-over present in ≥50% of
  variants
- warning: music present but stock / generic on >50% of spend
- fail: silent creatives — TikTok's 90%+ sound-on rate makes silent ads invisible
- fix: pull from TikTok Commercial Music Library; refresh trending tracks weekly

### T25 · Creative refresh cadence (every 7d)
- weight: 7 · severity: high · fix_effort: high
- applies_to_archetypes: [d2c_ecom, subscription_consumer, creator_media, mobile_app]
- pass: at least one new creative every 7d on each top-spend campaign (TikTok fatigue is 2×
  faster than Meta)
- warning: 7–14d gap
- fail: >14d gap — TikTok's creative-fatigue curve is steep; CPM inflates fast
- fix: weekly creator-deliverable cadence; expect 3–5× the creative velocity a Meta account
  demands

### T26 · Carousel / Collection / TopView mix
- weight: 4 · severity: medium · fix_effort: high
- applies_to_archetypes: [d2c_ecom, subscription_consumer]
- primary_metric_kind: cost_per_purchase
- pass: ≥2 active formats including at least one Carousel/Collection/Catalog Sales for e-com
  brands
- warning: single-format video only
- fail: only one creative active in the entire account
- fix: enable Catalog Sales (TikTok's dynamic product ads equivalent); test carousel for top-3
  SKUs

---

## Category C — Structure & Bid (20% weight)

### T40 · Campaign objective matches funnel intent
- weight: 6 · severity: medium · fix_effort: low
- applies_to_archetypes: [d2c_ecom, subscription_consumer, creator_media, mobile_app]
- pass: TOFU campaigns on Reach / Video Views; MOFU on Traffic / Engagement; BOFU on Conversions
  or Catalog Sales; app-install campaigns on App Promotion
- warning: 1–2 mismatched
- fail: all campaigns on Conversions regardless of funnel stage — pays a premium CPM for
  top-funnel impressions
- fix: re-objective by stage

### T41 · Smart Performance Campaigns / Maximum Delivery considered for prospecting
- weight: 5 · severity: medium · fix_effort: low
- applies_to_archetypes: [d2c_ecom, subscription_consumer, mobile_app]
- pass: ≥1 Smart Performance Campaign (SPC) active for prospecting (TikTok's Advantage+-style
  equivalent); SPC vs manual split documented
- warning: 100% manual (no algorithm leverage)
- fail: 100% SPC (no testing surface for manual ABO experiments)
- fix: keep ≥1 manual prospecting campaign for creative R&D

### T42 · Daily budget ≥ 50× target primary metric
- weight: 6 · severity: high · fix_effort: low
- applies_to_archetypes: [d2c_ecom, subscription_consumer, creator_media, mobile_app]
- pass: every active conversion campaign has daily budget ≥ 50× the brand's primary-metric
  target (TikTok's floor for Conversion objectives is roughly 50 events / 7-day window — higher
  than Meta's ≈30)
- warning: 20–50×
- fail: <20× — campaign cannot exit learning, CPM stays inflated
- fix: raise budget or consolidate ad groups

### T43 · ≥ 5 active creatives per ad group
- weight: 4 · severity: medium · fix_effort: medium
- applies_to_archetypes: [d2c_ecom, subscription_consumer, creator_media, mobile_app]
- pass: ≥5 active creatives per ad group (TikTok's algorithm needs variation to optimize)
- warning: 3–4
- fail: ≤2 — algorithm has no signal to compare
- fix: rotate hooks + variations; duplicate winners with new openings

---

## Category D — Audience (15% weight)

### T60 · Broad audiences default (lean on the algorithm)
- weight: 6 · severity: medium · fix_effort: low
- applies_to_archetypes: [d2c_ecom, subscription_consumer, mobile_app]
- pass: prospecting ad groups use broad targeting (age + geo only, no interest stack); TikTok's
  algorithm prefers broad and out-performs narrow interest-stacking
- warning: 1–2 interest layers
- fail: 3+ interest layers (under-delivers, narrows the algorithm's optimization surface)
- rationale: TikTok's algorithm is more aggressive than Meta's at finding intent within broad
  pools; over-targeting limits scale
- fix: strip interest layers; let the algorithm prospect

### T61 · Custom Audiences + Lookalikes from Pixel + customer list
- weight: 5 · severity: medium · fix_effort: low
- applies_to_archetypes: [d2c_ecom, subscription_consumer, creator_media]
- pass: ≥3 Custom Audiences (pixel visitors 7/30d, customer list, video viewers 25%+) + ≥2
  lookalikes (1% + 3%) tested for retargeting and warm prospecting
- warning: 1–2 of either
- fail: 0
- fix: build Custom Audiences via TikTok Events Manager; upload hashed customer email list
  (Shopify export)

### T62 · Exclusion of existing customers from prospecting
- weight: 4 · severity: medium · fix_effort: low
- applies_to_archetypes: [d2c_ecom, subscription_consumer]
- primary_metric_kind: cost_per_purchase
- pass: customer-list audience excluded from every prospecting campaign
- warning: customers excluded on some, not all
- fail: no exclusion — paying TikTok CPM to reach existing customers
- fix: layer exclusion on every prospecting ad group

---

## Critical-checks list (severity multiplier 5.0×)

ALWAYS surface in audit output, even when they pass. A FAIL on any critical caps that category's
sub-score at 50:

- T01 — TikTok Pixel installed + firing
- T02 — Events API active (web-conversion archetypes only)
- T04 — MMP integration (mobile_app only)
- T20 — Native-format creative
- T21 — 3-second hook strength

---

## Health-score formula

Per category: `sub_score = sum(check_score × check_weight × W_sev) / sum(100 × check_weight ×
W_sev)` over fired checks (`check_score ∈ {0, 50, 100}` for fail / warning / pass; N/A excluded;
`W_sev = {critical 5.0, high 3.0, medium 1.5, low 0.5}`).

Final:
```
health = 0.40 · creative_score
       + 0.25 · tracking_score
       + 0.20 · structure_score
       + 0.15 · audience_score
```

Grade letters: 90–100 A · 80–89 B · 70–79 C · 60–69 D · <60 F. A critical FAIL caps that
category's sub-score at 50.

---

## Archetype filtering at audit time

Drop checks that don't apply to the brand's archetype. B2B SaaS, local_service,
lead_gen_financial, and marketplace brands typically see 0 TikTok checks — correct, they
shouldn't be running TikTok paid. D2C + subscription + creator + app brands see the full catalog.

`primary_metric_kind` resolves per archetype at audit time. For TikTok this is typically
`cost_per_purchase` (D2C / subscription), `cost_per_subscriber` (creator), or
`cost_per_install_d7_retained` (app).

---

## What's NOT in this catalog (and why)

- **TikTok Shop checks** — TikTok Shop is its own surface (commerce inside the app, GMV
  attributed differently). Belongs in a separate catalog if a brand actually scales TikTok Shop.
- **Spark Ads engagement-rate optimization** — covered in T23 only; deeper Spark /
  creator-partnership checks belong in a separate influencer-collab playbook.
- **TikTok Creator Marketplace operations** — outside paid; creator sourcing / brief workflow is
  not an audit-grade check.
- **Branded effects / hashtag challenges / TopView** — top-of-funnel brand surfaces priced very
  differently; worth a separate brand-audit catalog if/when a brand runs these.
