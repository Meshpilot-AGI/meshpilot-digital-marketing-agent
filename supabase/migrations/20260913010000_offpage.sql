-- OFF-PAGE — the spine every off-page lever writes to (docs/plans/2026-09-12-offpage-seo.md § 3).
--
-- signal (signal_item, exists) → candidate (what we could say, where) → approval (the operator's
-- Discord reaction, read back into the candidate) → outcome (what happened). A lever — syndicate,
-- reply, haro — is a plug-in over these rows, so there is one approval UX and one ladder.
create table if not exists offpage_candidate (
  id             uuid primary key default gen_random_uuid(),
  brand_id       text not null,
  lever          text not null,             -- syndicate | reply | haro
  surface_kind   text not null,             -- x | linkedin | subreddit | haro
  surface        text not null,             -- handle / r/name / feed
  target_url     text,                      -- the thread / query answered; null for syndicate
  source_ref     text,                      -- seo_publication.slug or signal_item.id — provenance
  score          numeric,
  draft          text not null,
  draft_meta     jsonb not null default '{}'::jsonb,
  status         text not null default 'drafted',
    -- drafted | offered | approved | edited | rejected | posted_by_operator | posted_by_agent
    -- | expired | skipped
  discord_msg_id text,
  offered_at     timestamptz,
  decided_at     timestamptz,
  expires_at     timestamptz,
  created_at     timestamptz not null default now()
);
-- One candidate per (lever, surface, thread-or-post). target_url is null for syndication, and null
-- is never equal to null, so coalesce it — otherwise a post could be syndicated to X twice.
create unique index if not exists offpage_candidate_one_per_target
  on offpage_candidate (brand_id, lever, surface_kind, coalesce(target_url, ''), coalesce(source_ref, ''));
create index if not exists offpage_candidate_status on offpage_candidate (brand_id, lever, status);

create table if not exists offpage_outcome (
  candidate_id   uuid not null references offpage_candidate(id) on delete cascade,
  brand_id       text not null,
  lever          text not null,
  posted_url     text,
  error          text,
  measured_at    timestamptz not null default now(),
  metrics        jsonb not null default '{}'::jsonb,
  primary key (candidate_id, measured_at)
);

-- The evidence the reply ladder reads. One row per check; the stage is DERIVED from these rows and
-- the candidate history, never set.
create table if not exists offpage_standing (
  brand_id                 text not null,
  surface_kind             text not null,
  checked_at               timestamptz not null default now(),
  account_age_days         int,
  comment_karma            int,
  link_karma               int,
  approvals_30d            int,
  rejections_30d           int,
  posted_by_operator_30d   int,
  primary key (brand_id, surface_kind, checked_at)
);

alter table offpage_candidate enable row level security;
alter table offpage_outcome   enable row level security;
alter table offpage_standing  enable row level security;

comment on table offpage_candidate is 'Off-page spine: one row per thing the agent could say on a surface, with its approval state.';
comment on table offpage_outcome   is 'What happened to a candidate after it was posted: url, error, metrics over time.';
comment on table offpage_standing  is 'Account-standing evidence per surface kind; the reply ladder stage is derived from it.';
