---
name: seo-audit
description: SEO audit checklist covering technical health, on-page, structured data / schema, authority, and tracking. Use when running a site SEO health check, a pre-launch or quarterly SEO review, diagnosing an organic-traffic drop, or scoring a brand's SEO readiness before scaling content or paid spend.
---

# SEO Audit

## When to Use This Skill

Use this skill when evaluating a brand's website/organic-search health, or advising on:

- A full SEO audit before a content push, replatform, or paid-scaling decision
- Quarterly SEO health checks
- Root-cause analysis after an organic-traffic or ranking drop
- Pre-launch technical SEO review for a new site or major redesign
- Structured-data / Schema.org coverage review (rich results, AI Overviews, LLM-answer citability)
- Backlink-profile / authority health checks (toxic-link risk, manual-action risk)

This checklist is universal — every business with a website should be graded against it. What
counts as the "primary metric" varies by business model: service/B2B businesses grade against
organic qualified-lead volume, D2C/ecommerce against organic revenue + conversion rate,
marketplaces against organic two-sided supply/demand acquisition, and content/creator sites
against organic subscriber or audience growth. Substitute the brand's own target metric wherever
this doc says "primary metric."

## Audit Framework: 34 Checks Across 5 Categories

Each check below has a **pass / warning / fail** bar, a **weight** (relative importance within its
category, 1-10), a **severity** (critical / high / medium / low — severity multiplies into the
health-score math below), and a **fix_effort** (low <15min, medium 1-2h, high >2h or a new asset).

Two checks are **critical**: a FAIL on either caps that category's sub-score at 50 and should
always be surfaced in audit output, even when passing.

Category weights: **Technical 25% · On-Page 25% · Schema 20% · Authority 15% · Tracking 15%.**

Most checks apply universally. A handful (marked below) are ecommerce/subscription-specific
(Product schema, Merchant Center) or non-ecommerce-specific (Action schema) — skip the ones that
don't fit the brand's business model, or run the full catalog if unsure.

---

### Category A — Technical SEO (25% weight)

**A1 · Site indexable (robots.txt + Search Console)** — CRITICAL, weight 10, fix low
- Pass: Search Console reports the site indexed; `robots.txt` isn't blocking critical paths; no
  manual action; coverage report shows ≥95% of submitted pages indexed.
- Warning: 70-95% indexed, or `noindex` headers on a few critical pages.
- Fail: <70% indexed, or site-wide `noindex` / robots `Disallow: /`.
- Why it matters: every other SEO check is invalidated if the site isn't indexed.
- Fix: remove `noindex`; submit sitemap; request indexing for critical pages.

**A2 · Core Web Vitals — LCP / INP / CLS green on top-100 pages** — high, weight 8, fix high
- Pass: 75th-percentile field data (CrUX) is green on each of the top-100 most-trafficked URLs —
  LCP <2.5s, INP <200ms, CLS <0.1.
- Warning: amber on one metric (LCP 2.5-4.0s / INP 200-500ms / CLS 0.1-0.25).
- Fail: red on any metric, or no CrUX data (site too small to have field data).
- Why it matters: Google uses CWV as a ranking tiebreaker; a slow site forfeits CTR and
  organic-conversion rate even when it ranks well.
- Fix: image optimization (next-gen formats, responsive sizes); defer non-critical JS; preload
  above-the-fold assets.

**A3 · Mobile-friendly (Mobile-First Indexing)** — high, weight 7, fix medium
- Pass: Search Console Mobile Usability shows 0 issues; every critical page has a viewport meta
  tag, readable font size, and adequate tap-target spacing.
- Warning: 1-5 pages flagged.
- Fail: >5 pages flagged, or the site uses adaptive serving without mobile parity.
- Why it matters: Google indexes the mobile version of the page; desktop-only excellence is
  invisible to the crawler that matters.
- Fix: responsive CSS, viewport tag, test via PageSpeed Insights.

**A4 · HTTPS + valid certificates + canonical URLs** — medium, weight 5, fix low
- Pass: HTTPS site-wide, certs not expiring within 30 days; correct `<link rel=canonical>` on
  every page (no cross-origin pointer).
- Warning: certs expiring within 30 days, or self-canonical missing on some pages.
- Fail: HTTP serving, expired cert, or canonical pointing at a 404.
- Fix: cert auto-renewal; audit canonicals with a crawler (Screaming Frog or equivalent).

**A5 · XML sitemap + Search Console submission** — medium, weight 4, fix low
- Pass: XML sitemap exists at `/sitemap.xml`, submitted to Search Console, ≥95% of URLs in the
  sitemap are also indexed.
- Warning: sitemap present but stale (>30 days since last update), or a submission gap.
- Fail: no sitemap submitted.
- Fix: generate at build time; submit in Search Console → Sitemaps.

---

### Category B — On-Page SEO (25% weight)

**B1 · Title + meta description on every page** — high, weight 7, fix low
- Pass: every indexable page has a unique title (≤60 chars) and unique meta description
  (≤155 chars); ≥95% pass via a site-crawl tool.
- Warning: 80-95% pass, or duplicates on <10% of pages.
- Fail: <80% pass, or >20% duplicates.
- Why it matters: title + meta directly drive SERP click-through rate; missing or duplicated
  tags kill both ranking signal and CTR.
- Fix: bulk-template via CMS; auto-generate from page content for programmatic pages.

**B2 · H1 per page, semantic heading structure** — medium, weight 5, fix medium
- Pass: every page has exactly one H1; H2/H3 nest semantically.
- Warning: 2+ H1s on some pages, or skipped heading levels.
- Fail: no H1, or heading levels jump around incoherently (H4 straight to H1).
- Fix: refactor templates to enforce one H1 per page.

**B3 · Internal linking — zero orphan pages** — high, weight 6, fix medium
- Pass: every indexable page has ≥3 internal incoming links; 0 orphan pages.
- Warning: 1-2 incoming links on some pages, or ≤5 orphans.
- Fail: >5 orphan pages — Google won't reliably crawl them and internal authority can't flow to
  them.
- Fix: contextual links from cluster/hub pages; navigation and breadcrumb links.

**B4 · Image alt-text + descriptive filenames** — low, weight 3, fix medium
- Pass: ≥90% of images have descriptive alt text; filenames are human-readable (not
  `IMG_001.jpg`).
- Warning: 70-90% alt coverage.
- Fail: <70% coverage.
- Fix: bulk-update via CMS; auto-generate alt text for product images from product name.

**B5 · Content depth — top-50 pages ≥800 words or intent-matched length** — medium, weight 5, fix high
- Pass: top-50-by-traffic pages have ≥800 words, or intent-matched length (transactional pages
  can legitimately be shorter).
- Warning: 50-80% of the top-50 fall below the threshold.
- Fail: <50% meet it — thin content.
- Why it matters: Helpful Content / E-E-A-T signals reward depth on informational pages;
  transactional pages should be graded on intent match, not raw word count.
- Fix: expand thin pages with FAQ, comparison, or use-case sections.

**B6 · No keyword cannibalization** — medium, weight 4, fix medium
- Pass: no two pages target the same primary keyword (check via a rank tracker's top-pages
  report, or Search Console's query/page report).
- Warning: 1-3 cannibalization pairs.
- Fail: ≥5 pairs — Google can't decide which page to rank and both lose.
- Fix: merge, 301-redirect, or re-target the secondary page.

---

### Category C — Schema / Structured Data (20% weight)

**C1 · Organization schema on homepage + about page** — high, weight 6, fix low
- Pass: `Organization` (or `LocalBusiness` for a local-service business) schema with `name`,
  `url`, `logo`, `sameAs` (social profiles), and `contactPoint` rendered on the homepage and
  About page.
- Warning: present but missing 2+ required properties.
- Fail: not present — the brand is ineligible for a Knowledge Panel.
- Why it matters: drives the Knowledge Panel and brand-mention recognition in AI Overviews and
  LLM answer engines.
- Fix: add JSON-LD via CMS or a shared SEO-head component/template.

**C2 · Product schema on every product page** (ecommerce / subscription only) — high, weight 8, fix medium
- Pass: every product detail page carries `Product` schema with `name`, `image`, `description`,
  `sku`, `brand`, `offers{price, priceCurrency, availability}`, `aggregateRating` (if reviews
  exist), and a `review` array (top 5).
- Warning: present but `aggregateRating`/`review` missing.
- Fail: not present — Merchant Center listings and rich-result eligibility are blocked.
- Fix: render JSON-LD from product data; validate via Google's Rich Results Test.

**C3 · Action schema for non-ecommerce archetypes** — medium, weight 6, fix medium
- Pass: archetype-correct Schema.org Action on the relevant page — `RegisterAction` for sign-up
  flows (SaaS), `ContactAction`/`ReserveAction` for local-service, `SubscribeAction` for
  creator/media, `BookAction` for marketplace booking, `InstallAction` for a mobile app.
- Warning: present but missing target URL or completion criteria.
- Fail: not present — LLM answer engines can't disambiguate the brand's intended next step.
- Why it matters: AI Overviews and conversational answer engines increasingly cite structured
  data; missing Action schema reduces the brand's "correct next step" surface in LLM responses.
- Fix: add per-template JSON-LD blocks.

**C4 · FAQ schema on FAQ + support pages** — low, weight 4, fix low
- Pass: `FAQPage` schema renders on every FAQ, support, or pricing-questions page.
- Warning: present on some pages, not all.
- Fail: not present, despite the site having clear FAQ pages.
- Why it matters: FAQ rich results and AI Overview citations both draw on `FAQPage` schema; the
  implementation cost is near-zero and the SERP real-estate gain is meaningful.
- Fix: render from existing FAQ content via a shared template.

**C5 · BreadcrumbList schema** — low, weight 3, fix low
- Pass: every page deeper than the homepage has `BreadcrumbList` JSON-LD matching the visible
  breadcrumb trail.
- Warning: present on some pages, not all.
- Fail: not present, and the site is deeper than 2 levels.
- Fix: generate from the URL path.

---

### Category D — Authority & Off-Page (15% weight)

**D1 · Domain authority trend tracked** — medium, weight 5, fix low
- Pass: Domain Rating/Authority (via any SEO tool) is tracked monthly; trend flat or up over the
  trailing 6 months.
- Warning: declining authority with no recent link-cleanup effort.
- Fail: not tracked, or authority halved in 6 months without explanation.
- Fix: schedule a monthly snapshot; investigate any drop within 30 days (algorithm update, link
  loss, broken redirect chain).

**D2 · No toxic backlink profile (manual-penalty risk)** — high, weight 6, fix medium
- Pass: <5% of incoming links flagged toxic; no manual action in Search Console.
- Warning: 5-15% toxic, or private-blog-network signals present.
- Fail: >15% toxic, or an active manual action.
- Fix: file a disavow if needed; investigate the source (negative-SEO attack vs. a prior agency
  that bought links).

**D3 · Brand mentions / unlinked citations tracked** — medium, weight 4, fix medium
- Pass: unlinked brand mentions are monitored, and a reclamation-outreach process exists to turn
  mentions into links.
- Warning: tracked but no reclamation flow.
- Fail: not tracked.
- Why it matters: brand mentions feed AI Overview entity recognition even without a link.
- Fix: set up brand monitoring; run a weekly reclamation-outreach batch.

---

### Category E — Tracking / Search Console & Analytics (15% weight)

**E1 · Search Console verified + property correct** — CRITICAL, weight 8, fix low
- Pass: the domain property (not URL-prefix) is verified; all variant hostnames (www, http,
  https) are consolidated under the domain property.
- Warning: URL-prefix property only (misses subdomain traffic).
- Fail: not verified.
- Why it matters: without Search Console there's no organic-keyword data, no coverage reports,
  and no manual-action visibility.
- Fix: verify via DNS TXT record; consolidate properties.

**E2 · Analytics with goal events firing on conversion** — high, weight 7, fix medium
- Pass: web analytics (GA4 or equivalent) is active with the archetype-correct primary event
  firing (`purchase` for D2C, `generate_lead` for service, `subscribe` for creator,
  `app_install` for mobile app), and channel grouping captures organic search separately.
- Warning: analytics active but no goal events configured.
- Fail: analytics not installed, or event naming is non-standard.
- Fix: install via tag manager; standardize event names against a documented event taxonomy.

**E3 · Tag-manager container audit clean** — medium, weight 4, fix low
- Pass: the tag-manager container has ≥1 firing analytics tag, no orphan tags, and no duplicate
  Purchase/Lead emitters (dedup hygiene).
- Warning: one issue from the above.
- Fail: no tag manager, or multiple Purchase emitters (dedup already broken before it reaches
  the ad platform's pixel).
- Fix: audit the container; consolidate duplicate emitters.

**E4 · Merchant feed healthy** (ecommerce / subscription only) — medium, weight 5, fix medium
- Pass: the product feed (Google Merchant Center or equivalent) has <5% disapprovals, all
  top-50 SKUs by spend are approved, and review snippets are enabled.
- Warning: 5-15% disapprovals.
- Fail: feed disapproved or not connected.
- Fix: resolve disapprovals via the feed's diagnostics tool; align Product schema values with
  the feed.

---

## Health-Score Formula

Per category:
```
sub_score = sum(check_score × check_weight × W_sev) / sum(100 × check_weight × W_sev)
```
over the checks that fired, where `check_score ∈ {0, 50, 100}` for fail/warning/pass (N/A checks
excluded), and `W_sev = {critical: 5.0, high: 3.0, medium: 1.5, low: 0.5}`.

Final score:
```
health = 0.25·technical + 0.25·on_page + 0.20·schema + 0.15·authority + 0.15·tracking
```

Grade letters: 90-100 A · 80-89 B · 70-79 C · 60-69 D · <60 F.

A critical FAIL (site not indexable, or Search Console not verified) caps that category's
sub-score at 50, regardless of how the other checks in the category score.

## Audit Deliverable Template

```markdown
# SEO Audit: [Site Name]

## Executive Summary
- **SEO Health Score**: [X]/100 ([Grade])
- **Critical Findings**: [N]
- **High-Priority Findings**: [N]
- **Quick Wins (implement this week)**: [List]

## Category Scores
| Category | Score | Key Finding |
|----------|-------|-------------|
| Technical | [X]/100 | [One-line summary] |
| On-Page | [X]/100 | [One-line summary] |
| Schema | [X]/100 | [One-line summary] |
| Authority | [X]/100 | [One-line summary] |
| Tracking | [X]/100 | [One-line summary] |

## Top Priority Fixes
| Priority | Finding | Severity | Fix Effort | Recommended Action |
|----------|---------|----------|-----------|---------------------|
| 1 | [Finding] | Critical | Low | [Specific fix] |
| ... | ... | ... | ... | ... |
```

## What's Deliberately Out of Scope Here

- **Local SEO / Google Business Profile** — for local-service businesses, run a dedicated local
  SEO pass (GBP reviews, NAP consistency, citation building, Q&A management) alongside this one.
- **International SEO / hreflang** — only relevant once a brand goes multi-language; treat as a
  separate pass.
- **Programmatic SEO at scale** — the failure modes of large programmatic sites go beyond B3/B5/B6
  above; run a dedicated review once a brand runs programmatic SEO at real scale.
- **AI-search visibility** (Perplexity / ChatGPT / Claude / SearchGPT rankings specifically) — an
  emerging surface; today it's already partially captured by Schema (C1-C5), brand mentions (D3),
  and content depth (B5). Worth a standalone pass once better measurement tools exist.

## Applying This Playbook

Run the checks programmatically wherever the agent has API/crawler access (Search Console API,
a site-crawl tool, CrUX API, an SEO-data provider); fall back to manual spot-checks otherwise.
Score each check pass/warning/fail per the bars above, roll up per category, and apply the
health-score formula. Store audit results for period-over-period comparison, and surface findings
wherever the brand's operators review agent output.
