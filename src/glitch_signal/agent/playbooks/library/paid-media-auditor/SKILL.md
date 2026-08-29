---
name: paid-media-auditor
description: Comprehensive paid media auditor for Google Ads, Meta, Microsoft, and Amazon accounts. Use when conducting account health checks, quarterly reviews, competitive audits, pre-scaling readiness assessments, or diagnosing performance drops. Triggered by mentions of account audit, wasted spend, tracking verification, or account takeover preparation.
---

# Paid Media Auditor

## When to Use This Skill

Use this skill when evaluating the brand's advertising accounts or advising on:

- Full account audit before taking over management of an existing account
- Quarterly health checks on managed accounts
- Competitive audit to demonstrate gaps in current management
- Post-performance-drop root cause analysis
- Pre-scaling readiness (is the account ready to absorb 2x budget?)
- Tracking and measurement validation before major campaign launches
- Compliance review for regulated verticals

## Audit Framework: The 8 Pillars

Every audit covers these pillars with severity scoring (Critical / High / Medium / Low):

### 1. Account Structure
- Campaign taxonomy and naming conventions
- Ad group granularity (5-20 keywords per ad group for Search)
- Label usage for segmentation and bulk operations
- Geographic targeting precision
- Device bid adjustments
- Dayparting settings aligned with conversion patterns

### 2. Tracking & Measurement
- Conversion action configuration (primary vs secondary)
- Attribution model selection (Data-Driven preferred for volume)
- GTM/GA4 implementation verification
- Enhanced conversions setup (web and leads)
- Offline conversion import pipeline health
- Cross-domain tracking completeness
- Meta Pixel + CAPI server-side deduplication

### 3. Bidding & Budget
- Bid strategy appropriateness for conversion volume
- Learning period violations (changes made before stabilization)
- Budget-constrained campaigns (limited by budget flag)
- Portfolio bid strategy configuration
- Shared budget usage vs campaign-level control

### 4. Keywords & Targeting
- Match type distribution (avoid over-reliance on broad match without smart bidding)
- Negative keyword coverage and shared list usage
- Keyword-to-ad relevance scores
- Quality Score distribution (target 70%+ spend on QS 7+)
- Audience targeting vs observation mode
- Demographic exclusions

### 5. Creative
- RSA pin strategy (headlines and descriptions pinned appropriately)
- Ad extension utilization (sitelinks, callouts, structured snippets, images)
- Asset performance ratings in PMax
- Creative testing cadence
- Approval status and policy violations

### 6. Shopping & Feed (ecom only)
- Product feed quality score
- Title optimization with search-query-matched terms
- Custom label strategy for campaign segmentation
- Supplemental feed usage
- Disapproval rates and resolution time
- Competitive pricing signals

### 7. Competitive Positioning
- Auction insights analysis (impression share, overlap rate, top-of-page rate)
- Competitor ad copy monitoring
- Market share estimation by segment
- Search lost IS (budget) vs Search lost IS (rank)

### 8. Landing Page Experience
- Page speed (LCP < 2.5s on mobile)
- Mobile experience score
- Message match between ad copy and landing page
- Conversion rate by landing page
- Redirect chains and broken links

## Audit Deliverable Template

```markdown
# Paid Media Audit: [Account Name] — [Platform]

## Executive Summary
- **Account Health Score**: [X]/100 ([Grade])
- **Critical Findings**: [N]
- **High-Priority Findings**: [N]
- **Estimated Efficiency Opportunity**: [X]% improvement in [ROAS/CPA]
- **Quick Wins (implement this week)**: [List]

## Pillar Scores
| Pillar | Score | Key Finding |
|--------|-------|-------------|
| Account Structure | [X]/100 | [One-line summary] |
| Tracking & Measurement | [X]/100 | [One-line summary] |
| Bidding & Budget | [X]/100 | [One-line summary] |
| Keywords & Targeting | [X]/100 | [One-line summary] |
| Creative | [X]/100 | [One-line summary] |
| Shopping & Feed | [X]/100 | [One-line summary] |
| Competitive Positioning | [X]/100 | [One-line summary] |
| Landing Page | [X]/100 | [One-line summary] |

## Top 5 Priority Fixes
| Priority | Finding | Severity | Business Impact | Fix Complexity | Recommended Action |
|----------|---------|----------|-----------------|----------------|--------------------|
| 1 | [Finding] | Critical | [$X/mo waste] | Low | [Specific fix] |
| 2 | [Finding] | High | [$X/mo missed] | Medium | [Specific fix] |
| ... | ... | ... | ... | ... | ... |

## Tracking Verification Checklist
- [ ] Google Ads conversion actions firing correctly
- [ ] GA4 events matching Google Ads conversions (<3% discrepancy)
- [ ] Meta Pixel + CAPI deduplication working
- [ ] Enhanced conversions match rate >70%
- [ ] Offline conversion imports succeeding
```

## Impact Estimation Methodology

For each finding, estimate impact using:

1. **Baseline**: Current metric value (e.g., CPA = $45)
2. **Benchmark**: Industry average or account historical best (e.g., CPA = $32)
3. **Volume**: Monthly conversions affected (e.g., 500/month)
4. **Projected monthly impact**: (Baseline - Benchmark) × Volume

Example: "Quality Score improvement from 5 to 7 on $12K monthly spend → estimated 15% CPC reduction → $1,800/mo savings or reinvestment opportunity."

## Applying This Playbook

Pull audit data programmatically from the brand's ad platform API clients
(Google Ads, Meta Marketing API, TikTok Ads, Amazon Ads, etc.) wherever the
agent has those integrations wired up.

When building audit features into the agent:
- Store audit checkpoints for historical comparison
- Reuse existing reporting/analytics infrastructure rather than building parallel plumbing
- Surface audit results wherever the brand's operators review agent output

## Success Metrics

- **Audit Completeness**: All 8 pillars evaluated, zero categories skipped
- **Finding Actionability**: 100% of findings include specific fix instructions
- **Revenue Impact**: Audits typically identify 15-30% efficiency improvement opportunities
- **Implementation Rate**: 80%+ of critical/high findings implemented within 30 days
- **Post-Audit Performance Lift**: Measurable improvement within 60 days
