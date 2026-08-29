---
name: platform-changes
description: Recent Meta Ads platform, algorithm, and policy changes an operator must factor into any audit or performance read — Andromeda delivery engine, iOS/ATT + CAPI, Link Clicks redefinition, Offline Conversions API EOL, Threads ads, Advantage+ Shopping defaults, and expanded Aggregated Event Measurement. Use when auditing a Meta ad account, explaining a sudden metric shift, or citing a policy/algorithm change instead of guessing at a creative/targeting cause.
---

# Platform Changes — Meta Ads Operator Awareness

An audit must factor in algorithm and API changes that ship over time. Many "performance
dropped" reads are actually metric redefinitions or algorithm shifts, not creative or targeting
failures. Always cite the relevant change before recommending a structural fix — and update this
file whenever a new platform change lands that could be mistaken for a performance regression.

Last reviewed: 2026-04-25.

---

## Andromeda AI engine — October 2025

Meta replaced its delivery model with **Andromeda**, a new neural retrieval engine that uses
10,000× more complex models than the prior pipeline.

**What changed:**
- Creative retrieval now considers a **Similarity Score** across every active creative in an ad
  set.
- Pairs with similarity > 60% experience **retrieval suppression** — Andromeda picks one and
  starves the rest.
- 100 minor variations of one concept perform worse than 10 genuinely distinct concepts.

**Operator implication:**
- Stop iterating "5 colour variants of the same image" — Meta will collapse them.
- Distinct hooks / formats / personas matter more than raw creative volume.
- Flag any account exceeding the similarity threshold for cleanup.

**Audit action:** when an account has >5 active creatives in an ad set with avg similarity
>0.55, recommend "kill near-duplicates, keep 1 of each cluster."

---

## iOS 14.5 / ATT — ongoing impact

Apple's App Tracking Transparency cut Meta's deterministic attribution on iOS by 30–40%. Meta's
countermeasure is CAPI + dedup. Without both, ROAS appears systematically lower than reality on
every iOS-heavy account.

**Operator implication:**
- CAPI is **not optional** for any account with significant iOS traffic.
- Dedup rate < 90% means Meta is double-counting → over-reporting ROAS.
- Aggregated Event Measurement (AEM) replaces real-time event reporting for iOS — only the
  top-priority events get reported.

---

## Link Clicks metric redefinition — February 2025

In Feb 2025 Meta redefined "Link Clicks" to **exclude social engagement clicks** (likes,
comments, profile clicks). Previously these inflated the metric.

**Operator implication:**
- Many accounts saw a sudden 20–40% drop in CTR around Feb 2025 with no real performance change.
- Comparing CTR before/after Feb 2025 is invalid without a footnote.
- Use "outbound clicks" or "clicks-all" instead for trend continuity.

**Audit action:** when CTR shows a step-change drop near Feb 2025, surface this as a
metric-redefinition explanation BEFORE recommending creative changes.

---

## Offline Conversions API — End of Life May 2025

Meta retired the standalone Offline Conversions API in May 2025. Accounts still configured for
it are silently losing those events.

**Operator implication:**
- Migrate any "offline" purchase signal (call centre, in-store) into CAPI with
  `action_source = "physical_store"` or similar.
- Old workflows that pushed CSVs to OCAPI silently produce zero events now.

---

## Threads ads — General availability January 2026

Meta opened Threads as a paid placement in Jan 2026. Currently a small fraction of total Meta
spend industry-wide; CPMs run ~30% lower than Feed/Stories. Emerging channel.

**Operator implication:**
- Brands with an active Threads presence get an early-mover discount.
- For a brand with no organic Threads presence yet, this isn't actionable — treat as
  informational and monitor as the brand's organic Threads strategy evolves.

**Audit action:** track Threads placement adoption as informational — no fail condition.

---

## Advantage+ Shopping Campaigns — default for e-com

Advantage+ Shopping (ASC+) became the default conversion campaign type in late 2024. Pre-2024
manual prospecting campaigns now significantly underperform vs ASC+ on most D2C accounts.

**Operator implication:**
- Don't drill to ad level inside ASC+ — Meta shuffles creative internally; ad-level ROAS is
  noisy.
- Judge ASC+ at campaign level: total volume + CPA vs target.
- Keep one manual ABO campaign as the creative-testing surface.

**Audit action:** confirm campaign-carried-by-one-ad tracking is explicitly disabled inside
ASC+; judge at campaign level only.

---

## Aggregated Event Measurement v2 — 2025

AEM expanded from 8 to **16** events per domain, with better support for value sets and dynamic
prioritisation. Many accounts are still set up under the v1 8-event cap — leaving optimization
signal on the table.

**Operator implication:** audit Events Manager → Aggregated Event Measurement → ensure all 16
slots are used, prioritised correctly (highest-value conversion event, e.g. Purchase, ranked
#1).

---

## How to cite these in an audit

When an audit recommends an action tied to one of these changes, cite it explicitly:

> "Andromeda (Oct 2025): 14 of 17 active ASC+ creatives have >0.6 similarity. Kill 9
> near-duplicates; preserve the 5 distinct concepts."

vs. the lazy version:

> "Try more diverse creatives."

The first is auditable — it names the mechanism, the evidence, and the fix. The second is
fluff.
