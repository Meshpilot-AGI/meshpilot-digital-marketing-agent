# Job Application Agent — design

> **Operator goal (2026-09-15):** "MeshPilot should be applying for jobs for me."
>
> Status: DESIGN. Nothing built yet. Lane `JOBS-0` cuts this doc; `JOBS-1..6` build it.
> Everything ships GATED OFF, per `docs/VISION.md` § Principles.

## 1. Why this fits MeshPilot (and is not scope creep)

`docs/VISION.md` defines two independent axes: **Projects** (tenants/brands) ×
**Capabilities** (what the agent can do). A job search is a new **Project**
(`tejas`) plus a new **Capability family** (`jobs`). It needs no new architecture:

| Need | Already exists |
|---|---|
| Per-tenant isolation, no global credentials | `<ENV_PREFIX>_<KEY>`; brand configs in the nested private repo |
| Bound the agent to a job's toolset | `agent/loop/scopes.py` — capability → tool sets |
| "Never submit unless I flip a switch" | `agent/loop/policy.py` — allowlist-by-default + per-capability kill-switches |
| Human approval on Discord, one tap | `agent/offpage/approvals.py` — REST polling, reaction precedence, TTL |
| Run 24/7 unattended | `agent/cron/` — exactly-once via `FOR UPDATE SKIP LOCKED` |
| Learn what worked | `agent/learn/` curator — episodes → durable lessons |
| Per-brand memory + hybrid recall | `agent/memory/` — pgvector + FTS |

The one genuinely new thing is **outward submission into a third-party form**.
Everything else is wiring existing parts to a new capability.

## 2. Prior art — borrow the logic, not the shape

`career-ops` (MIT, `career-ops-hq/career-ops`, installed at `~/dev/career-ops`)
has already solved discovery, scoring and CV tailoring well, and is in use by the
operator as of 2026-09-14. Treat it the way we treat the v1 monorepo: **pull its
proven logic, never inherit its shape.**

Worth stealing outright:

- **The A–H report + 1–5 score** — a structured evaluation, not a vibe.
- **Two-pass rule** — fill requirement/importance from the JD *before* reading the
  CV, so the model can't anchor importance on what the candidate happens to have.
- **Source-of-Truth Boundary** — generated content may come only from the
  candidate's own files plus their direct statements. *"Keywords get reformulated,
  never fabricated."* This is the single most important rule to port.
- **Story provenance** — a quantified claim that originates in a derived file must
  trace to a primary file or carry an explicit provenance marker, or it is
  `derived-unverified` and never stated as fact.
- **Work-authorization gate** — only an explicit "we will not sponsor" on a role
  outside `authorized_in` is a hard stop; silence is neutral.

What career-ops deliberately refuses to do — submit — is exactly the part this
lane adds. The split is clean and not duplicated effort:

| career-ops (local, on demand) | MeshPilot (cloud, 24/7) |
|---|---|
| Operator-driven evaluation | Unattended discovery + scoring on cron |
| Tailors a CV when asked | Tailors, then *asks for approval*, then submits |
| Never submits, by design | Submits — gated, approved, audited |

## 3. Shape

```
discover → dedupe → score → (score ≥ threshold?) → tailor CV + answers
        → Discord approval card → (approved?) → submit → track → learn
```

One pipeline, `job_hunt`, registered in `agent/loop/pipelines.py`. Every arrow is
a tool call subject to the scope (what's offered) and the policy gate (what's
allowed) — the same two independent layers everything else uses.

## 4. Sources (discovery)

Ordered by cost and risk. **The operator's LinkedIn account is not an acceptable
thing to risk** — a ban costs more than the postings are worth.

| Source | Route | Cost | ToS |
|---|---|---|---|
| Job Bank Canada | public ATOM feed (`jobbankca` provider pattern) | free | public service, `Crawl-delay: 5` honored |
| Greenhouse / Lever / Ashby / Workday | public board APIs | free | public, documented |
| Indeed | Apify actor (`misceres/indeed-scraper`) | metered | Apify carries the scraping |
| LinkedIn | **job-alert emails**, parsed from Gmail | free | LinkedIn *sends* them — no scraping |

⚠️ **`APIFY_KEY` is already held and completely unwired** (recorded in the
TARGETING lane on the board). This lane is a legitimate first consumer of it.

**Rejected:** direct authenticated scraping of LinkedIn or Indeed from our own IP.
Against their ToS, and it stakes the operator's account on it. Not in scope; do
not add it later without an explicit operator decision recorded here.

## 5. The fact base (anti-fabrication)

A tailored CV that invents a number is worse than no CV — it is a lie told in the
operator's name, to a hiring manager, at scale. Mirror career-ops' boundary:

- **Primary (full trust):** `brand/configs/tejas.json` (profile), a `cv.md`
  equivalent stored per-brand, and the operator's direct statements in chat.
- **Derived (narrative trust only):** past tailored CVs, cover letters, episodes.
  A number appearing only here is `derived-unverified` and must never be restated
  as established fact.
- Reorder, reframe, emphasise. Never invent. If a claim isn't backed, ask — and if
  unanswered, ship without it. Silence is fine; manufactured detail is not.
- **Authorship claims are non-negotiable** — never claim the operator built
  something not attributed to them in the fact base.

`verify_cv_facts` runs on every generated document and **fails closed**: a
document with an unsupported metric never reaches an approval card.

## 6. Approval gate (the core safety property)

Reuse `agent/offpage/approvals.py` wholesale — same Discord REST polling, same
reaction precedence, same TTL semantics, a separate channel.

```
✅  apply — send it as drafted
✏️  apply with my edits — operator edits the draft in-thread first
❌  skip
⏸️  hold — keep in queue, re-surface tomorrow
```

Precedence: an action beats an intention, a no beats a yes — `❌`, `⏸️`, `✏️`, `✅`.
Only ids in `jobs.approvers` count; bot legend reactions never do. **Expiry is not
an approval** — a card that ages out is skipped, never auto-sent.

The card shows: role, company, location, score + the score's parts, work-auth
verdict, the tailored CV diff vs. master, and every free-text answer that would be
submitted. Nothing is submitted that the operator has not seen in full.

## 7. Submission — the honest hard part

This is the only genuinely new and genuinely fragile component. Stage it LAST
(`JOBS-5`), behind its own kill-switch, and be honest about the failure modes:

- **ATS variety** — Greenhouse/Lever/Ashby/Workday each differ; Workday is the
  worst. Start with Greenhouse + Lever (simplest, best-documented DOM), and treat
  anything else as `manual_required` rather than guessing at a form.
- **CAPTCHA** — on encounter, mark `blocked_captcha` and hand back to the
  operator. **Do not integrate a CAPTCHA solver.** Bypassing bot-detection is out
  of bounds regardless of convenience.
- **Account creation** — many ATSes require an account. The agent must never
  create accounts or enter passwords; those stay operator actions. Pre-existing
  sessions only.
- **Idempotency** — submitting twice to one req is worse than not submitting. A
  unique constraint on `(brand_id, canonical_url)` plus a submitted-at guard, and
  the same `FOR UPDATE SKIP LOCKED` discipline the cron uses.
- **Evidence** — screenshot + confirmation text stored per submission. A claimed
  submission with no artifact is treated as NOT submitted.

**Expect a meaningful share of applications to need a human.** A design that
pretends otherwise will silently drop applications the operator believes were
sent. `manual_required` is a first-class outcome, surfaced in Discord, not a
failure to hide.

## 8. Schema (additive, Supabase-native)

```
job_listing      (id, brand_id, source, canonical_url UNIQUE, company, title,
                  location, posted_at, jd_text, first_seen_at, liveness_checked_at)
job_evaluation   (id, listing_id, score numeric, score_parts jsonb, work_auth,
                  report_md, model, evaluated_at)
job_application  (id, listing_id, status, tailored_cv_path, answers jsonb,
                  approval_msg_id, approved_by, approved_at, submitted_at,
                  evidence jsonb, failure_reason)
                  UNIQUE (brand_id, canonical_url)
```

`status`: `discovered → scored → drafted → awaiting_approval → approved →
submitted | skipped | manual_required | blocked_captcha | expired`.

Additive migrations land **before** the code that reads them.

## 9. Kill-switches (all default FALSE)

| Flag | Gates |
|---|---|
| `agent_jobs_enabled` | the whole capability |
| `agent_job_discovery_enabled` | outbound source pulls (metered: Apify) |
| `agent_job_tailor_enabled` | LLM CV generation |
| `agent_job_apply_enabled` | **submission** — the one that spends the operator's reputation |

`job_apply` joins `PUBLISH_TOOLS` so it inherits the existing publish kill-switch
semantics for free. Per-run caps: max applications/day, max/company.

## 10. Sub-lanes

| Lane | Scope | Acceptance |
|---|---|---|
| `JOBS-0` | this doc | doc merged, lane board updated |
| `JOBS-1` | schema + `tejas` brand config + `jobs` scope/capability | migration in prod; `chat` scope still cannot reach any job tool |
| `JOBS-2` | discovery: Job Bank + ATS boards + Apify(Indeed) + LinkedIn alert emails | ≥1 real listing per source in `job_listing`, deduped |
| `JOBS-3` | scoring: two-pass A–H report + work-auth gate | 10 real listings scored; operator agrees with the ranking |
| `JOBS-4` | tailoring + `verify_cv_facts` fail-closed | a generated CV with a planted unsupported metric is REJECTED |
| `JOBS-5` | Discord approval cards | a card posted, all four reactions read back correctly, expiry ≠ approval |
| `JOBS-6` | submission (Greenhouse + Lever only) + evidence | one real application submitted with a stored confirmation artifact |

Each lane ships live before the next starts — the OFFPAGE discipline.

## 11. Open operator decisions

1. **Daily application cap?** Volume vs. precision. Recommend starting at 3/day.
2. **Auto-apply floor** — career-ops uses 4.0/5. Same here, or higher?
3. **Approve-per-application, or approve-a-batch once a day?** Per-application is
   safer; batch is less work for the operator.
4. **Does the agent ever answer free-text screening questions unattended**, or is
   any question outside a known-answer bank always `manual_required`?
