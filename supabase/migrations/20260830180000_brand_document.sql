-- Brand documents (FILES lane): a brand's uploaded docs (style guide / brief / deck), referenced
-- by their Anthropic Files API `file_id` in Messages document blocks. Files are workspace-scoped,
-- so tenant isolation is enforced by the APP (every query is `WHERE brand_id = …`) — this table is
-- the brand→file_id map. Uploaded via POST /internal/brand/{brand_id}/documents (jobs-auth).

create table if not exists brand_document (
  id          uuid primary key default gen_random_uuid(),
  brand_id    text not null,
  file_id     text not null,               -- Anthropic Files API id (file_…)
  filename    text not null,
  mime_type   text,
  size_bytes  bigint,
  kind        text not null default 'doc', -- doc | style_guide | brief | deck | …
  created_at  timestamptz not null default now()
);

create index if not exists brand_document_brand_idx on brand_document (brand_id);
create unique index if not exists brand_document_file_uidx on brand_document (file_id);

alter table brand_document enable row level security;  -- service-role only (writes go through the API)
