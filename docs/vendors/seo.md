# SEO publishing — where it runs, and why not in the cloud

The agent authors blog posts and ships them into the **site's own repo** as a code change:
a typed object appended to `src/data/blog.ts`, the site's own gates run, a PR opened. CF Pages
builds on merge.

## The constraint that shapes everything here

Publishing needs three things the API's runtime does not have:

| Needs | FastAPI Cloud |
|---|---|
| a git checkout of the site repo | ✗ |
| the site's npm toolchain (`typecheck`, `lint`, `schemas:validate`, `links:audit`) | ✗ |
| a `gh` credential that can open a PR | ✗ |

So `seo_publish` is **schedulable but not cloud-runnable**. Scheduled in the agent's own cron it
returns `no_repo` before touching anything — a job that looks healthy and does nothing, which is
worse than no job at all. It runs from a host that has the checkout; on this Mac that is a launchd
job, `deploy/com.meshpilot.seo-cycle.plist`, driving `scripts/run_seo_cycle.py`.

`seo_settle` has the same requirement for a different reason: it asks `gh pr view` what happened to
each open PR.

## The cycle

**Settle runs before publish, every time.** `publish()` reads the stage from the track record, so a
cycle that published first would author at a stale stage — wasteful at S0, and at S1 it would mean
self-merging on evidence that has since been contradicted.

```
uv run python scripts/run_seo_cycle.py               # settle, then publish
uv run python scripts/run_seo_cycle.py --dry-run     # author only; repo untouched
uv run python scripts/run_seo_cycle.py --settle-only # record outcomes; publish nothing
```

A refusal is a normal outcome — disabled, no repo, no sitemap, no topic, duplicate slug — and the
script exits 0 on all of them, so a scheduler does not mail about routine quiet days.

## Configuration

Global kill-switch `AGENT_SEO_ENABLED` (default **false**) — while false the cycle still settles,
which is useful on its own, and declines to publish. Per-brand, via the brand's env prefix:

| Key | Meaning |
|---|---|
| `<PREFIX>_SEO_REPO_PATH` | checkout of the site repo. No checkout → `no_repo`. |
| `<PREFIX>_SEO_SITEMAP` | default `public/sitemap-en.xml` — the site's **real** URL vocabulary. |
| `<PREFIX>_SEO_BLOG_FILE` | default `src/data/blog.ts` |
| `<PREFIX>_SEO_AUDIENCE` | who the post is for |
| `<PREFIX>_SEO_AUTHOR` | byline slug — a real person's attribution, never model-chosen |
| `<PREFIX>_SEO_BRAND_TERMS` | csv of names that mean *us* (e.g. `Glitch Executor`). Empty disables the product-claim check — no declaration, no protection. |
| `<PREFIX>_SEO_CAPABILITIES` | csv of what the product actually does. A sentence about us that matches none of these is rejected. |
| `<PREFIX>_SEO_AGENT_LOGINS` | csv of the agent's own GitHub logins. **Commits by anyone else count as human edits**, which is what gates promotion out of S0 — get this wrong and the agent either never earns autonomy or earns it falsely. |

⚠️ **Without a readable sitemap the cycle refuses rather than authoring.** With no URL vocabulary the
model invents plausible internal paths: the first live generation wrote `/tools/drawdown-calculator`
when the real page is `/tools/firm-drawdown-calculator`. An invented link is the same class of error
as an invented figure.

## Autonomy

Stage is **derived from the track record, never configured** — see `agent/seo/track.py`. S0 opens a
PR for a human; S1 (five consecutive posts merged with zero human edits) self-merges; S2 after ten
clean self-merges. Gates run at every stage including S2: autonomy removes the human, not the checks.

## Headless auth — the trap this actually hit

`gh` authenticates from **`GITHUB_TOKEN` or `GH_TOKEN`**, and **either one overrides its own keyring
login.** So loading `.env` into the process environment silently replaced a working `gh` auth with a
PAT that could not open PRs. The armed cycle authored a real post, passed all four site gates, pushed
the branch — and died on `gh pr create` with *"not all refs are readable"*, leaving an orphan branch
and no PR.

`scripts/run_seo_cycle.py` therefore **skips both keys** when loading `.env`, unless
`SEO_USE_GITHUB_TOKEN=true`. `settings.github_token` still reads the value through pydantic, so
Scout is unaffected.

A fine-grained PAT for this job needs **Contents: read/write** and **Pull requests: read/write** on
the target repo. ⚠️ Repo-level `"admin": true` in the REST response is **not** the same thing and is
not sufficient — the REST repo read returns 200 with admin permissions while `gh pr create` still
fails.

## Known rough edge

If `gh pr create` fails after the push, the branch stays on the remote with no PR and no
`seo_publication` row. The failure is named in the result, but nothing cleans up — deleting a pushed
branch automatically is riskier than leaving one for a human.

## What the generator checks, and why each one exists

Every check below was added because something got past the ones before it.

| Check | Catches | Added after |
|---|---|---|
| editorial contract | structure — lede length, H2 count, FAQ count, links across clusters | designed up front |
| `unsupported_figures` | a percentage that appears in no verified fact | first live generation |
| `unsupported_links` | an internal path the sitemap does not have | `/tools/drawdown-calculator` |
| **`unsupported_generalisations`** | an invented *consensus* — "most firms", "almost every" | a post claiming most challenges require minimum trading days, when 2 of 6 live firms do |
| **`unverified_product_claims`** | a claim about **our own product** that we have not declared | a post saying the engine blocks orders on a weekend cutoff; it does not |
| **`dead_sources`** | a citation that 404s | a CFTC URL that looks authoritative and does not resolve |

⚠️ **The product-claim check is the one nothing else could do.** Figure-grounding checks numbers, the
contract checks structure, and no external source can confirm what our own code does. A brand
declares its capabilities; a sentence about the brand that matches none of them is rejected rather
than published. It costs a declaration to maintain, and that is the price of the guarantee.

⚠️ **Grounding a rule-topic post uses a different query than grounding a firm post.**
`publishable` governs whether a threshold may be QUOTED — the sentinel zeros are unpublishable
because "0 minimum profitable days" reads as a threshold rather than an absence. But when the
question is *how common* a rule is, those zeros are the fact. `rules_for_distribution()` therefore
reads past `publishable` and renders an absence as "no requirement". Counting only the publishable
rows reports "2 of 2 firms have one" — grounding that is worse than silence.

## GE's declared capabilities (2026-09-03)

Derived from the code, not from the marketing site. Each was checked against what actually runs.

```
records each firm's published rules,dated source for every firm rule,compares firms side by side,calculates drawdown against a firm's rules,tracks account equity,daily-loss and drawdown evaluation,trade journal,replay,alerts,backtest,strategy builder,connects to cTrader,connects to DXtrade,connects to MetaApi
```

**Deliberately left out, with the reason — this half is the more useful half:**

| Not claimable | Why |
|---|---|
| routes orders to your broker | `TRADE_EXEC_BROKER_ROUTING_ENABLED=false` in `infra/prod/ecs.tf`. The router persists the gate decision and returns `broker_routing_not_configured` — it never POSTs. `TRADE_EXEC_DEMO_ONLY=true` would restrict it to demo accounts even if switched on. |
| blocks your order before it reaches the broker | Same reason. The gate evaluates and records, but nothing is armed in prod (`armed=0 evaluated=0 emitted=0 routed=0`), so no order is being stopped for anyone today. |
| enforces a weekend cutoff | `hold_over_weekend` is catalogue data, never read as a condition. This is the claim that started all of this. |
| enforces a news blackout | `block_minutes_around_news` is the **same trap**: stored per firm, served to the UI, never emitted as a gate rule. Found while writing this list — nobody had noticed. |
| any pass/profit outcome | The program forbids outcome promises, and the vertical is YMYL-adjacent. |

⚠️ **Two of the five were found by writing the allowlist, not by review.** Declaring what a product
does forces someone to check, and checking turned up a second dormant field of exactly the shape of
the first. Keep this table current: a capability that ships should be added here in the same change,
and a capability that is switched off should be removed here in the same change.

**When routing is armed, this list changes.** The first two rows become claimable and the note
should move rather than being deleted, so a future reader can see the claim was gated on evidence
rather than never considered.
