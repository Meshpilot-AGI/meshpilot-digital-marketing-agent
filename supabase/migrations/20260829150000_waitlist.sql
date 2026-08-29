-- Waitlist signups from the marketing site (#99). The static site (Cloudflare Pages, output:export)
-- has no server, so the form POSTs to the FastAPI API which persists here. Email is unique so a
-- repeated signup is idempotent, not a duplicate lead.

create table if not exists waitlist (
  id          uuid primary key default gen_random_uuid(),
  email       text not null,
  source      text,                        -- which CTA / page sent it
  user_agent  text,
  created_at  timestamptz not null default now()
);

create unique index if not exists waitlist_email_uidx on waitlist (lower(email));

alter table waitlist enable row level security;  -- service-role only (writes go through the API)
