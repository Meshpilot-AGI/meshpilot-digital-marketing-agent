-- A small encrypted store for values the agent MINTS at runtime (SEO-11).
--
-- Config that a human sets belongs in the environment. This is for the other kind: a credential the
-- agent creates for itself — the first being a Discord webhook URL it provisions, which cannot be in
-- the env because it does not exist until the agent makes it.
--
-- Encrypted at rest with the same Fernet key as `oauth_tokens`. Deliberately NOT that table:
-- `oauth_tokens` carries refresh semantics and NOT NULL client/endpoint columns, and shoehorning a
-- webhook into it would look like an OAuth grant to every later reader.
create table if not exists agent_secret (
  brand_id   text not null,
  name       text not null,
  value_enc  text not null,
  updated_at timestamptz not null default now(),
  primary key (brand_id, name)
);

alter table agent_secret enable row level security;

comment on table agent_secret is
  'Encrypted values the agent mints at runtime (e.g. a webhook it provisioned). Human-set config '
  'belongs in the environment, not here.';
