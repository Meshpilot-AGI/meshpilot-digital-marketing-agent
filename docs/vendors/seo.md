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
| `<PREFIX>_SEO_AGENT_LOGINS` | csv of the agent's own GitHub logins. **Commits by anyone else count as human edits**, which is what gates promotion out of S0 — get this wrong and the agent either never earns autonomy or earns it falsely. |

⚠️ **Without a readable sitemap the cycle refuses rather than authoring.** With no URL vocabulary the
model invents plausible internal paths: the first live generation wrote `/tools/drawdown-calculator`
when the real page is `/tools/firm-drawdown-calculator`. An invented link is the same class of error
as an invented figure.

## Autonomy

Stage is **derived from the track record, never configured** — see `agent/seo/track.py`. S0 opens a
PR for a human; S1 (five consecutive posts merged with zero human edits) self-merges; S2 after ten
clean self-merges. Gates run at every stage including S2: autonomy removes the human, not the checks.
