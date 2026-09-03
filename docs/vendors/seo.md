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

## Two failure modes the schedule had, and how they are closed

**One post in flight.** Every post is inserted at the same anchor — the top of the `blog` array — so
two open PRs always conflict with each other. #558 and #559 both landed on it, and #559 could not be
rebased at all; its content had to be re-applied onto `main` by hand. `run_publish` now refuses with
`post_in_flight` while any post is unsettled. That removes the conflict class rather than teaching
the publisher to resolve it, and costs nothing real: waiting on review is the normal state at S0, and
the cadence is one post a day against a review loop measured in days.

**Every cycle leaves a row.** `seo_cycle` records each run — refusals included — so a failure is a
query rather than a log grep:

```sql
select ran_at, ok, outcome, detail from seo_cycle
where brand_id = 'glitch_executor' order by ran_at desc limit 10;
```

or `track.recent_cycles(brand_id)`. **The alarm is the GAP between rows**, not any single bad one: a
refusal is normal and `ok=false` means the cycle itself broke. Before this, the only output was a log
file on one machine that nothing read, so a silent failure at 06:40 and a quiet day were
indistinguishable — both produce no PR. That is the same "looks healthy, does nothing" shape the
cloud schedule was rejected for, and it had been reintroduced on the Mac.

## Alerting on the gap (SEO-9)

`seo_cycle` made a failure queryable; nobody queries it. `seo_heartbeat` turns "you could have
noticed" into "you were told".

**The thing being watched is silence, not an error.** A cycle that crashes leaves a row with
`ok=false`; a cycle that never runs — laptop asleep, launchd unloaded, plist broken, Mac off —
leaves nothing, and nothing is exactly what a healthy quiet day looks like. So the signal is the
**age of the newest row**, and no row at all is the loudest case rather than a missing one. A
*refusal* still counts as a heartbeat: the cycle ran and declined, which means the machine is alive.

⚠️ **It runs in the CLOUD, not on the Mac.** A watcher living on the machine it watches dies with it
and reports nothing at exactly the moment there is something to report. It needs only the database,
so the agent's own cron hosts it — scheduled `daily-seo-heartbeat`, 12:00 ET, about five hours after
the 06:40 cycle.

⚠️ **It never writes to `seo_cycle`.** Recording its own run there would refresh the newest-row
timestamp and mask the very gap it exists to measure — the watcher would permanently reassure itself.
A test asserts this.

| Setting | Meaning |
|---|---|
| `<PREFIX>_SEO_ALERT_WEBHOOK` | **Discord webhook URL — the preferred channel.** A webhook needs no bot, no gateway and no inbound plumbing, and the alert lands where the operator already watches |
| `<PREFIX>_SEO_ALERT_EMAIL` | second channel, tried when Discord does not deliver |
| `<PREFIX>_RESEND_FROM` or `RESEND_FROM` | the From address `send_email` requires (email path only) |
| `RESEND_API_KEY` | Resend credential (email path only) |
| `max_gap_hours` job arg | default 30 — a day plus slack, so a late run is not a page |

Email is a **second** channel, not an alternative: the point is that the message arrives, so a
failure in one must not consume the alert. A *delivered* Discord post skips email — an alert that
arrives twice trains the reader to ignore one of them.

With neither configured the check still runs, still logs `seo.heartbeat_stale`, and still returns
`stale: true` onto its `scheduled_runs` row — visible, just not pushed.

⚠️ **The webhook URL is a credential.** Anyone holding it can post as that channel, so it is never
logged, never echoed into a result dict, and never included in an error message — failures report the
HTTP status, never the target. A placeholder value reads as *not configured* rather than as a broken
channel, so a half-finished setup degrades to "logged only" instead of failing every run.

### Setting up the Discord alerts channel

1. In the MeshPilot control-plane server, create a private channel — e.g. `#alerts`.
2. Channel settings → **Integrations → Webhooks → New Webhook**, name it `MeshPilot`, copy the URL.
3. Set `GE_SEO_ALERT_WEBHOOK` to that URL in the **FastAPI Cloud** env (the heartbeat runs in the
   cloud, not on the Mac). `env set` is create-only — delete and recreate to change it.

The gateway in `gateway/` is deliberately **not** involved: it is the inbound direction (chat →
agent), and an alert must not depend on the thing it might be alerting about.

It alerts **once per 12h per brand** (a `SharedWindowLimiter` over `rate_counters`). The watcher runs
on its own schedule, so without that a single stale cycle would page on every firing, and an alert
that repeats is an alert people filter.
