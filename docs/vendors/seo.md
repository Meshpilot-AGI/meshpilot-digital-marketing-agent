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

Derived from the code, then corrected by the operator. Kept current in `deploy/com.meshpilot.seo-cycle.plist`.

**Live routing is on as of 2026-09-03.** Verified on the running revision `ge-prod-trade-api:14`:
`TRADE_EXEC_BROKER_ROUTING_ENABLED=true`, `TRADE_EXEC_FEATURE_FLAG=true`, `TRADE_EXEC_DEMO_ONLY=false`.

**The qualifier changed rather than disappeared.** `router.py` guard (ii) still requires PER-ACCOUNT
`exec_live_opt_in` — a live account must be explicitly opted in "even once the global flag lifts" —
plus per-account risk caps. So the declared capabilities are *"on demo accounts"* AND *"on live
accounts you opt in"*. Both are true; an unqualified *"routes your orders to your broker"* is not,
for a reader who has done neither.

⚠️ **EVERY entry must carry its qualifier, because the list's weakest entry sets the bar.** A bare
`order routing` entry — left over from when routing looked fully claimable — was silently making
"routes your orders straight through to your broker" pass, right next to the carefully qualified
entries. One unqualified capability voids every qualifier in the list. The shipped list now has none,
and a test asserts it.

⚠️ **Enabled is not the same as happening.** The execution runtime still logs
`execution.runtime.tick armed=0 evaluated=0 emitted=0 routed=0` every cycle, with no order routed in
24h. The path is on and functional; nothing is armed on it. A post may say the product places orders
on accounts you opt in — it may not imply anyone's orders are being placed today.

### How a claim is matched

Every content word of a declared capability must appear in the sentence, matched as a **prefix** of
one of its words.

Three attempts, and the first two both rejected TRUE claims:

1. **substring on the whole phrase** — "routes orders to your broker" missed "routes your orders
   straight through to your broker"
2. **symmetric stemming** — failed on its own inconsistency: "places" trimmed to "plac" while
   "place" stayed "place", so the two never met
3. **reduce only the declared word, prefix-match the sentence** — "place" is a prefix of "place",
   "places" and "placed" alike

Requiring **all** content words rather than a fraction is deliberate: a partial match would let
"enforces a weekend cutoff tied to the firm rule" through on the strength of sharing "firm" with
"records each firm's published rules". Declaring every inflection would also have worked, and would
have grown a list nobody could maintain.
