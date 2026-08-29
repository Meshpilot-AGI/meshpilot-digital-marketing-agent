-- Durable OAuth tokens for MCP servers the agent connects to (e.g. HeyGen).
-- Some providers issue short-lived access tokens with ROTATING refresh tokens (HeyGen: ~1h access,
-- a new refresh token on every refresh). A static env secret can't survive that — the rotated
-- refresh token must be persisted atomically. This table is the single source of truth; the MCP
-- client reads it (refreshing if near expiry, under a row lock) instead of a hardcoded bearer.

create table if not exists oauth_tokens (
  provider       text primary key,          -- e.g. 'heygen'
  access_token   text not null,
  refresh_token  text,
  expires_at     timestamptz not null,      -- when access_token expires
  client_id      text not null,
  token_endpoint text not null,
  resource       text,                       -- RFC 8707 resource indicator, if the provider needs it
  updated_at     timestamptz not null default now()
);

alter table oauth_tokens enable row level security;  -- service-role only
