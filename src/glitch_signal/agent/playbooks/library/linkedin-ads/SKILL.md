---
name: linkedin-ads
description: LinkedIn Ads audit checklist and best-practice catalog covering tracking (Insight Tag, Conversions API, pipeline-stage events), audience/ABM targeting, creative format mix, and structure/bid — with a weighted Health Score formula and archetype filtering for B2B SaaS, professional services, and lead-gen brands. Use when auditing a LinkedIn ad account or deciding whether a brand archetype should be running LinkedIn paid at all.
---

# LinkedIn Ads Audit Checklist

Targets the brands that actually run LinkedIn paid: B2B SaaS, high-ACV professional services,
lead-gen, and marketplaces with B2B supply-side acquisition. D2C / creator / mobile-app brands
typically should NOT run LinkedIn; this catalog won't apply to them after archetype filtering.

Sources distilled in the field: LinkedIn's own Conversions API playbook, Refine Labs (Chris
Walker), the Pavilion exec community, Influ2 / DemandBase ABM frameworks, Goldcast / Hatch
ABM-content loops, WebMechanix's B2B Ads playbook, and pipeline-stage attribution practice.

Health Score weight mix favors **Tracking 30% · Audience 30% · Creative 20% · Structure 20%**
because LinkedIn's leverage is overwhelmingly audience quality + correct conversion signal — not
creative variation or campaign-count tuning the way Meta is.

## Schema

Each check carries:

- `id` — `L01`+ stable identifier, never reused.
- `applies_to_archetypes` — almost all are `[b2b_saas]` or `[b2b_saas, local_service]` (where
  local_service = high-ACV professional services like agencies, consultancies, law firms); some
  are `[b2b_saas, marketplace]` for supply-side B2B acquisition.
- `primary_metric_kind` — defaults to `cost_per_sql` for B2B SaaS, `cost_per_qualified_lead` for
  service / lead-gen.

Critical checks (severity 5.0×) cap their category sub-score at 50 on FAIL.

---

## Category A — Tracking & Conversions (30% weight)

### L01 · Insight Tag installed + firing
- weight: 10 · severity: **critical** · fix_effort: low
- applies_to_archetypes: [b2b_saas, local_service, lead_gen_financial, marketplace]
- pass: LinkedIn Insight Tag fires on every page (site-wide PageView) AND on the conversion
  event(s); confirmed via Campaign Manager → Insight Tag → "Active" status with last fire <24h
- warning: tag fires but missing on conversion page (matched-audience retargeting impossible)
- fail: tag inactive OR not installed
- rationale: every other LinkedIn check needs the Insight Tag; no matched audiences, no
  conversions, no funnel analysis without it
- fix: install via GTM (LinkedIn Insight Tag template) or hardcode into `<head>`; verify in
  Campaign Manager

### L02 · Conversions API (LCAPI) active
- weight: 10 · severity: **critical** · fix_effort: medium
- applies_to_archetypes: [b2b_saas, local_service, lead_gen_financial]
- pass: server-side LCAPI mirroring ≥0.7× of pixel-side conversions for the primary event;
  LinkedIn-reported "Server EMQ" score ≥6
- warning: LCAPI live but partial (0.4–0.7× ratio)
- fail: no LCAPI — relying on browser pixel alone (loses 30–50% on iOS / blockers)
- rationale: LinkedIn's parallel to Meta CAPI; without it, the optimizer is making bid decisions
  on a 50–70% signal sample
- fix: wire via Zapier / native HubSpot / Salesforce / Stripe LCAPI integration; map every
  conversion event with `event_id` for dedup

### L03 · Conversion categories correctly mapped
- weight: 7 · severity: high · fix_effort: low
- applies_to_archetypes: [b2b_saas, local_service, lead_gen_financial]
- pass: each conversion event uses a SPECIFIC LinkedIn category (`LEAD`, `SIGN_UP`, `PURCHASE`,
  `BOOK_APPOINTMENT`, `ADD_TO_CART`, etc.) — not `OTHER`
- warning: ≥1 primary conversion uses `OTHER`
- fail: all primary conversions use `OTHER` — optimizer gets no semantic signal
- rationale: LinkedIn's automated optimization (Maximum Delivery, Target Cost) reads the
  category enum; `OTHER` defaults to a catch-all model with weaker performance
- fix: rename each conversion event with the correct category in Campaign Manager → Account
  assets → Conversions

### L04 · Pipeline-stage events uploading (MQL/SQL/Opp/Won)
- weight: 9 · severity: **critical** · fix_effort: high
- applies_to_archetypes: [b2b_saas]
- primary_metric_kind: cost_per_sql
- pass: CRM (HubSpot / Salesforce / Pipedrive) uploads `MQL`, `SQL`, `Opportunity`,
  `Closed-Won` stage transitions to LinkedIn via LCAPI offline conversions with `value` =
  opportunity ARR
- warning: only `Lead` uploads — the raw-form-fill trap
- fail: no pipeline-stage upload → optimizer buys low-fit MQLs that never convert
- rationale: the gap between cost_per_lead and cost_per_sql is the single biggest leak in B2B
  paid; without pipeline-stage data, LinkedIn's algorithm scales the wrong thing
- fix: wire CRM → LinkedIn LCAPI with stage-tagged events; this is the highest-ROI work for any
  B2B account

### L05 · 90-day attribution window enabled
- weight: 6 · severity: high · fix_effort: low
- applies_to_archetypes: [b2b_saas, marketplace]
- primary_metric_kind: cost_per_sql
- pass: account-level attribution = 90-day click; reports default to same window
- warning: 30-day click set but reports default to 7-day (under-reports)
- fail: 7-day default — sales-cycle conversions outside the window are invisible
- rationale: B2B sales cycles run 30–90 days; default 7-day attribution hides 60–80% of
  paid-influenced revenue
- fix: Campaign Manager → Account → Conversions → Attribution settings

### L06 · UTM + LinkedIn-specific parameters set
- weight: 4 · severity: medium · fix_effort: low
- applies_to_archetypes: [b2b_saas, local_service, lead_gen_financial, marketplace]
- pass: account-level URL tracking template populates `utm_source=linkedin`, `utm_medium=cpc`,
  `utm_campaign={li_campaign_id}`, `utm_content={li_creative_id}`, `utm_term={li_ad_format}`
- warning: present but missing campaign-id or creative-id
- fail: no template — every campaign carries default LinkedIn click-IDs only, no
  analytics-stack join key
- fix: paste the template in Campaign Manager → Settings → URL parameters

---

## Category B — Audience & Targeting (30% weight)

### L20 · Matched Audiences from CRM lists
- weight: 9 · severity: **critical** · fix_effort: medium
- applies_to_archetypes: [b2b_saas, local_service, lead_gen_financial]
- pass: ≥3 active Matched Audiences uploaded from CRM (customers, closed-won opportunities,
  lost opportunities), refreshed weekly, each ≥300 matched members (LinkedIn's audience-size
  floor)
- warning: 1–2 lists OR last refresh >30d
- fail: 0 — running on demographic targeting only (no first-party signal)
- rationale: first-party matched audiences are LinkedIn's strongest targeting signal — exclude
  existing customers from prospecting, retarget engaged prospects, look-alike off won-deal lists
- fix: CSV export from CRM → Campaign Manager → Audiences → Upload Contact List; wire daily sync
  via Zapier / native HubSpot integration

### L21 · ABM / Company List targeting (high-ACV only)
- weight: 7 · severity: high · fix_effort: medium
- applies_to_archetypes: [b2b_saas]
- primary_metric_kind: cost_per_sql
- pass: if ACV ≥ $25k, an account-list-target campaign exists with the brand's target-account
  list (1k–10k accounts) + buying-committee job-title filter; ≥30% of LinkedIn spend on it
- warning: list exists but no buying-committee filter (just "anyone at the account")
- fail: ACV ≥$25k but no ABM campaign — paying LinkedIn premium CPM for non-target accounts is
  the most expensive way to spray
- rationale: above $25k ACV, the CAC math only works on ABM; below $25k, broader prospecting can
  work
- fix: build a target-account list in Sales Navigator → upload to Campaign Manager as a Matched
  Audience (company-match)

### L22 · Exclusion hygiene
- weight: 6 · severity: high · fix_effort: low
- applies_to_archetypes: [b2b_saas, local_service, lead_gen_financial]
- pass: existing customers + closed-won + closed-lost-recent excluded from every prospecting
  campaign; competitor employees excluded account-wide
- warning: customers excluded but no competitor exclusion
- fail: no exclusions — paying LinkedIn premium CPM for customers and competitors
- fix: build the 3 exclusion audiences once; apply to every prospecting campaign in the
  campaign-group template

### L23 · Audience size in the 50k–400k sweet spot
- weight: 5 · severity: medium · fix_effort: low
- applies_to_archetypes: [b2b_saas, local_service, lead_gen_financial]
- pass: every active prospecting audience sits between 50k and 400k estimated members
  (LinkedIn's published sweet spot)
- warning: 1–2 audiences outside the band
- fail: any active audience <20k (under-deliver) or >2M (low signal)
- rationale: <50k = LinkedIn flags "narrow" and slow-delivers; >400k = the algorithm has
  nothing to optimize toward
- fix: tighten with seniority + job-function + company-size filters; loosen with broader
  job-function combinations

### L24 · Audience Network expansion deliberately set
- weight: 3 · severity: low · fix_effort: low
- applies_to_archetypes: [b2b_saas, local_service, lead_gen_financial, marketplace]
- pass: every campaign has Audience Network expansion EXPLICITLY toggled (on for brand
  awareness, off for lead-gen — never default)
- warning: default-on across the account (LinkedIn turns this on by default; the expanded
  network has 3–5× cheaper impressions but conversion quality drops sharply for lead-gen)
- fail: any conversion-objective campaign with Audience Network ON
- fix: toggle off in every conversion campaign; keep on for awareness if the budget allows

### L25 · Lookalike (Audience Expansion) tested
- weight: 4 · severity: medium · fix_effort: low
- applies_to_archetypes: [b2b_saas, local_service, lead_gen_financial]
- pass: at least one campaign running with LinkedIn's "Audience Expansion" (lookalike
  equivalent) seeded from a won-deal Matched Audience
- warning: tested but paused
- fail: never tested — leaving the algorithm's best prospecting tool on the shelf
- fix: duplicate a top-performing prospecting campaign, enable Audience Expansion, compare CPL
  over 30 days

---

## Category C — Creative & Format (20% weight)

### L40 · Format diversity (≥3 active formats)
- weight: 6 · severity: medium · fix_effort: high
- applies_to_archetypes: [b2b_saas, local_service, lead_gen_financial, marketplace]
- pass: ≥3 active formats from {single-image, video, document, carousel, conversation ad,
  thought-leader ad}
- warning: 2 formats
- fail: 1 format only — LinkedIn's algorithm optimizes per-format independently; single-format
  accounts cap their own ceiling
- fix: prioritize document ads (highest CTR for SaaS, 2× single-image on average) and
  thought-leader ads (lowest CPL when the founder has personal brand)

### L41 · Lead Gen Forms used over external LP
- weight: 7 · severity: high · fix_effort: low
- applies_to_archetypes: [b2b_saas, local_service, lead_gen_financial]
- primary_metric_kind: cost_per_lead
- pass: lead-objective campaigns use LinkedIn Lead Gen Forms (pre-filled with member profile
  data); LGF-to-external-LP split documented per campaign
- warning: LGF on some campaigns, external LP on others without a test (no controlled
  comparison)
- fail: 100% external LP for lead capture (typical CPL is 2–4× higher than LGF for B2B)
- rationale: LGF removes the form-filling friction; member data pre-populates from LinkedIn
  profile; conversion lift 2–3×
- fix: convert lead-objective campaigns to LGF; wire LGF → CRM via native HubSpot / Salesforce /
  Marketo integration

### L42 · Thought-leader ads tested
- weight: 5 · severity: medium · fix_effort: high
- applies_to_archetypes: [b2b_saas]
- pass: ≥1 thought-leader ad active in the last 30d, sponsored from a founder / executive / SME's
  personal profile (not the company page)
- warning: tested but paused
- fail: never tested — high-ACV SaaS leaves the cheapest CPL surface on the table
- rationale: thought-leader ads consistently produce 30–50% lower CPL than company-page ads for
  B2B; the personal-brand signal cuts through the LinkedIn-ad-blindness most users have
- fix: pick a founder / VP of Marketing post that resonated organically; sponsor it from their
  profile via Campaign Manager → Sponsor a post

### L43 · Ad text within LinkedIn limits + scannable
- weight: 3 · severity: low · fix_effort: low
- applies_to_archetypes: [b2b_saas, local_service, lead_gen_financial, marketplace]
- pass: intro text <150 chars (the mobile-feed cutoff); headline <70 chars; description (if
  applicable) <100 chars; CTA matches the conversion intent
- warning: 150–600 / 70–150 / 100–200 — wall-of-text feed cards
- fail: >600 / >150 / >200 — feed-card truncation kills clarity
- fix: trim copy; lead with the value prop in the first 80 chars

### L44 · Creative refresh cadence (every 14d top-spend)
- weight: 4 · severity: medium · fix_effort: high
- applies_to_archetypes: [b2b_saas, local_service, lead_gen_financial]
- pass: at least one new creative every 14d on each top-spend campaign
- warning: 14–28d gap
- fail: >28d gap — frequency caps + audience fatigue in narrow audiences are amplified
- fix: weekly creative ops cadence; LinkedIn's narrower audiences feel fatigue sooner than
  Meta's

---

## Category D — Structure & Bid (20% weight)

### L60 · Conversion objective per campaign matches funnel stage
- weight: 6 · severity: medium · fix_effort: low
- applies_to_archetypes: [b2b_saas, local_service, lead_gen_financial]
- pass: TOFU = Brand Awareness or Reach; MOFU = Website Visits or Engagement; BOFU = Website
  Conversions or Lead Generation; each conversion campaign's objective matches the conversion
  stage it optimizes for
- warning: mismatch on one or two campaigns (e.g. Brand Awareness campaign trying to drive demo
  requests)
- fail: blanket "Website Conversions" for the entire funnel — pays premium CPM for top-funnel
  impressions
- fix: re-objective per stage; LinkedIn's pricing changes 5–10× by objective

### L61 · Daily budget ≥ 5× target primary metric
- weight: 5 · severity: medium · fix_effort: low
- applies_to_archetypes: [b2b_saas, local_service, lead_gen_financial]
- pass: every active conversion campaign has daily budget ≥ 5× the brand's primary-metric
  target (LinkedIn floors at $10/day for most objectives; ABM with $200 CPL targets needs
  $1000/day to exit learning)
- warning: 2–5×
- fail: <2× — LinkedIn's optimizer cannot exit learning; campaign stays in "Limited" state and
  over-pays per conversion
- fix: raise budget or merge campaigns; LinkedIn's floor is much higher than Meta's

### L62 · Bid strategy chosen, not defaulted
- weight: 4 · severity: medium · fix_effort: low
- applies_to_archetypes: [b2b_saas, local_service, lead_gen_financial, marketplace]
- pass: bid strategy explicitly set — `Maximum Delivery` (autobid, default; OK for new
  campaigns), `Target Cost` (soft CPA cap; use after 30 conversions), or `Manual CPC` (bid
  floor; use only when capping a runaway campaign)
- warning: default Maximum Delivery on every campaign post-learning (no Target Cost gate)
- fail: Manual CPC across the account when LinkedIn has CVR data (under-bidding the algorithm's
  preferred strategy)
- fix: switch each campaign to Target Cost once it crosses 30 conversions in 30 days

### L63 · Campaign group structure matches funnel
- weight: 3 · severity: low · fix_effort: medium
- applies_to_archetypes: [b2b_saas, local_service, lead_gen_financial]
- pass: campaign groups organized by funnel stage (Awareness / Demand-Gen / Retargeting / ABM)
  with budget pooled at the group level
- warning: groups organized by quarter or campaign name (no funnel structure)
- fail: no campaign groups at all (every campaign in the default group) — no budget pooling, no
  funnel-level optimization
- fix: re-group campaigns; group-level budget enables campaign-level experimentation without
  spend-cap shocks

### L64 · LinkedIn-specific UTMs flow into CRM
- weight: 4 · severity: medium · fix_effort: medium
- applies_to_archetypes: [b2b_saas, local_service, lead_gen_financial]
- primary_metric_kind: cost_per_sql
- pass: HubSpot / Salesforce / Pipedrive captures `utm_source=linkedin` + `utm_campaign` +
  `utm_content` on every lead's first-touch + last-touch; revenue attribution reports can roll
  up to campaign + creative
- warning: source captured but campaign/creative not (no creative-level pipeline ROI)
- fail: UTMs not captured — pipeline reports cannot reach LinkedIn campaign-level
- fix: configure CRM to capture all 5 standard UTMs to lead + contact + deal records; first- +
  last-touch wired

---

## Critical-checks list (severity multiplier 5.0×)

These ALWAYS surface in audit output, even when they pass. A FAIL on any critical caps that
category's sub-score at 50:

- L01 — Insight Tag installed + firing
- L02 — Conversions API (LCAPI) active
- L04 — Pipeline-stage events uploading (when applicable)
- L20 — Matched Audiences from CRM lists

---

## Health-score formula

Per category: `sub_score = sum(check_score × check_weight × W_sev) / sum(100 × check_weight ×
W_sev)` over fired checks (`check_score ∈ {0, 50, 100}` for fail / warning / pass; N/A excluded;
`W_sev = {critical 5.0, high 3.0, medium 1.5, low 0.5}`).

Final:
```
health = 0.30 · tracking_score
       + 0.30 · audience_score
       + 0.20 · creative_score
       + 0.20 · structure_score
```

Grade letters: 90–100 A · 80–89 B · 70–79 C · 60–69 D · <60 F. A critical FAIL caps that
category's sub-score at 50.

---

## Archetype filtering at audit time

Drop checks that don't apply to the brand's archetype. Almost all LinkedIn checks here are
tagged `[b2b_saas]` or with `local_service` / `lead_gen_financial` / `marketplace` (supply-side)
added where the archetype rationally uses LinkedIn paid. D2C / subscription_consumer /
creator_media / mobile_app brands will see zero LinkedIn checks after filtering — correct
behavior, since those archetypes shouldn't be running LinkedIn paid.

`primary_metric_kind` resolves to `cost_per_sql` for b2b_saas, `cost_per_qualified_lead` for
local_service / lead_gen_financial, and `cost_per_first_transaction` for marketplace.

---

## What's NOT in this catalog (and why)

- **Sales Navigator / Recruiter checks** — different product surface; would need its own audit
  catalog if needed.
- **LinkedIn Live / Events** — organic; out of scope.
- **InMail / Message Ads** — covered in L40 format diversity but no separate hygiene checks; the
  format has well-documented best practices but most failure modes are deliverability (open
  rate) rather than something a static checklist can grade. Defer until a brand actually scales
  InMail spend.
- **LinkedIn Audience Network (off-platform inventory)** — covered in L24 only; not its own
  category. The fail modes are documented but the leverage is small.
