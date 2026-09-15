-- JOBS-1 — the job-application spine (docs/plans/2026-09-15-job-application-agent.md § 8).
--
-- listing (what exists, from any source) → evaluation (what we think of it, two-pass) →
-- application (what we did about it, gated on the operator's Discord reaction). One row per
-- posting per brand; a source is a plug-in over these rows, so there is one approval UX.
create table if not exists job_listing (
  id                  uuid primary key default gen_random_uuid(),
  brand_id            text not null,
  source              text not null,            -- jobbank_ca | greenhouse | lever | ashby | workday | apify_indeed | linkedin_alert
  canonical_url       text not null,            -- tracking params stripped, host lowercased, no fragment
  company             text,
  title               text,
  location            text,
  posted_at           timestamptz,
  jd_text             text,                     -- archived verbatim; a live URL rots once the posting closes
  first_seen_at       timestamptz not null default now(),
  liveness_checked_at timestamptz
);
-- The deterministic dedup key. The SAME posting reaches us from several sources (a Greenhouse board
-- AND a LinkedIn alert email AND Job Bank), so dedup on the normalized URL, not on company+title:
-- two genuinely different reqs at one company often share a title.
create unique index if not exists job_listing_one_per_url
  on job_listing (brand_id, canonical_url);
create index if not exists job_listing_source on job_listing (brand_id, source, first_seen_at desc);

create table if not exists job_evaluation (
  id            uuid primary key default gen_random_uuid(),
  listing_id    uuid not null references job_listing(id) on delete cascade,
  brand_id      text not null,
  score         numeric,                        -- 0-5; the 4.0 floor is applied by the caller, not here
  score_parts   jsonb not null default '{}'::jsonb,
  work_auth     text,                           -- sponsors | not_needed | unstated | no_sponsorship
  report_md     text,                           -- the A-H report
  model         text,
  evaluated_at  timestamptz not null default now()
);
-- Re-evaluation is allowed (a reposted JD, a changed profile), so this is NOT unique on listing_id;
-- the latest row by evaluated_at wins.
create index if not exists job_evaluation_listing on job_evaluation (listing_id, evaluated_at desc);

create table if not exists job_application (
  id               uuid primary key default gen_random_uuid(),
  listing_id       uuid not null references job_listing(id) on delete cascade,
  brand_id         text not null,
  status           text not null default 'discovered',
    -- discovered | scored | drafted | awaiting_approval | approved | submitted
    -- | skipped | manual_required | blocked_captcha | expired
  tailored_cv_path text,
  answers          jsonb not null default '{}'::jsonb,
  discord_msg_id   text,
  approved_by      text,
  offered_at       timestamptz,
  approved_at      timestamptz,
  submitted_at     timestamptz,
  expires_at       timestamptz,
  evidence         jsonb not null default '{}'::jsonb,   -- confirmation text + screenshot ref
  failure_reason   text,
  created_at       timestamptz not null default now()
);
-- Submitting twice to one req is worse than not submitting at all. One application per listing,
-- enforced in the DB rather than trusted to the caller.
create unique index if not exists job_application_one_per_listing
  on job_application (listing_id);
create index if not exists job_application_status on job_application (brand_id, status, created_at desc);
-- Drives the 3/day cap (design § 11 decision 1) without a table scan.
create index if not exists job_application_submitted_day
  on job_application (brand_id, submitted_at)
  where submitted_at is not null;

-- The operator-authored answer bank. Decision 4 (design § 11): the agent NEVER composes a free-text
-- screening answer. A form question is answered only by an EXACT match here; anything else becomes
-- manual_required. Matching is on the normalized question string — never an LLM deciding two
-- questions "mean the same thing", because a confident near-match is how a wrong answer ships.
create table if not exists job_answer_bank (
  id           uuid primary key default gen_random_uuid(),
  brand_id     text not null,
  question     text not null,          -- normalized: lowercased, collapsed whitespace, stripped punctuation
  answer       text not null,
  created_at   timestamptz not null default now()
);
create unique index if not exists job_answer_bank_one_per_question
  on job_answer_bank (brand_id, question);
