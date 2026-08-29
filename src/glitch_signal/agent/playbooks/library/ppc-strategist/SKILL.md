---
name: ppc-strategist
description: Senior paid media strategist for Google Ads, Meta, Amazon, and TikTok campaign architecture. Use when designing account structures, bidding strategies, budget allocation, or diagnosing performance issues in the ads platform. Triggered by mentions of campaign builds, bid strategies, ROAS/CPA targets, account restructuring, or scaling ad spend.
---

# PPC Campaign Strategist

## When to Use This Skill

Use this skill when working on the brand's ads accounts or advising on:

- Campaign structure design for new platforms or business units
- Bidding strategy selection (tCPA, tROAS, Max Conversions, Max Conversion Value)
- Budget allocation across campaigns, platforms, or business units
- Performance diagnosis (CPC changes, conversion rate drops, impression share loss)
- Scaling spend while maintaining efficiency targets
- Cross-platform strategy (Google/Meta/Amazon/TikTok) avoiding cannibalization
- Account restructuring or migration planning

## Core Frameworks

### Account Architecture Principles

Build campaigns that scale from current spend to 10x without structural rewrites:

**Tiered Campaign Isolation**
- **Brand**: Protect branded queries, 90%+ impression share target
- **Non-brand / Category**: Core prospecting, primary growth lever
- **Competitor**: Conquest terms, isolated budget and bids
- **Retargeting / Remarketing**: RLSA, custom audiences, lower-funnel

**Naming Convention** (enables automated reporting and bulk operations)
```
[Brand]_[CampaignType]_[Objective]_[Geo]_[Device]_[Date]
Acme_Search_NB_Category_US_Mobile_2026Q2
```

### Bidding Strategy Selection Matrix

| Conversion Volume / Month | Recommended Strategy | Rationale |
|---------------------------|----------------------|-----------|
| < 30 | Max Clicks or Manual CPC | Insufficient data for automated bidding |
| 30-100 | tCPA | Algorithm has enough signals to optimize |
| 100-500 | tROAS or Max Conversion Value | Volume supports value-based optimization |
| 500+ | Portfolio tROAS | Cross-campaign learning, efficiency at scale |

**Transition Rule**: Never switch bid strategies during a performance anomaly or within 2 weeks of a major account change. Automated bidding needs 1-2 learning periods (typically 7-14 days) to stabilize.

### Budget Allocation Framework

Use diminishing returns analysis rather than equal splits:

1. **Pull 30-day performance by campaign** (ROAS or CPA, conversion volume, impression share)
2. **Calculate marginal efficiency** — the ROAS/CPA of the last 20% of spend in each campaign
3. **Reallocate from low-marginal to high-marginal** campaigns until marginal efficiency equalizes
4. **Reserve 10-15% for testing** — new audiences, creatives, or campaign types

## Platform-Specific Tactics

### Google Ads
- **Performance Max**: Use for broad reach with strong feed + audience signals. Always pair with standard Shopping or Search to maintain query control.
- **Search**: Maintain exact match isolation for top performers; use broad match + smart bidding for discovery.
- **Shopping**: Feed quality is 70% of performance. Optimize titles with search-query-matched keywords before bidding changes.

### Meta Ads
- **Advantage+ Shopping**: Best for catalog-heavy ecom with 50+ conversion events/week.
- **Campaign Budget Optimization (CBO)**: Let the algorithm distribute budget across ad sets, but cap individual ad sets if one consistently underperforms.
- **Creative testing**: Test 3-5 creatives per ad set, kill underperformers at 1,000 impressions or $20 spend.

### Amazon Ads
- **Sponsored Products**: Bid on auto-targeting first to discover converting queries, then migrate winners to manual.
- **Sponsored Brands**: Use for brand defense and category conquest with video creative.
- **DSP**: Only viable at $50K+ monthly; use for audience retargeting and lookalikes.

### TikTok Ads
- **Spark Ads**: Leverage organic content; typically 1.5-2x better CPA than standard In-Feed.
- **Creative refresh cadence**: TikTok ad fatigue is faster than Meta — refresh every 7-14 days.

## Performance Diagnosis Workflow

When a performance drop is reported, follow this sequence:

1. **External factors first**: Check auction insights (competition), seasonality, and platform algorithm changes
2. **Tracking verification**: Confirm conversion tracking hasn't broken (GTM, pixel, CAPI)
3. **Structural changes**: Review change history for bid strategy switches, budget cuts, or targeting changes
4. **Creative fatigue**: Check frequency and CTR trends by creative
5. **Audience decay**: Review audience size and overlap; refresh lookalikes every 30-60 days

## Applying This Playbook

- Prefer API-driven changes (Google Ads API, Meta Marketing API, etc.) for scale
- Use the agent's existing reporting/data tables for performance baselines
- Respect any metered API call caps configured for the brand's ad platform integrations

## Success Metrics

- **ROAS / CPA**: Hitting target efficiency within 2 standard deviations
- **Impression Share**: 90%+ brand, 40-60% non-brand (budget permitting)
- **Budget Utilization**: 95-100% daily pacing with <5% waste
- **Conversion Volume Growth**: 15-25% QoQ at stable efficiency
- **Testing Velocity**: 2-4 structured tests running per month per account
