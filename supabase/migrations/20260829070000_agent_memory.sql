-- AGENT-MEM: per-brand agent memory (facts + episodes) with hybrid recall.
-- Idempotent (safe no-op on prod, builds fresh shadow/CI DBs). Embedding =
-- NVIDIA nemotron-3-embed-1b (2048-dim) → halfvec so HNSW works past 2000 dims.
create extension if not exists vector;

create table if not exists agent_memory (
  id           uuid primary key default gen_random_uuid(),
  brand_id     text not null,
  kind         text not null check (kind in ('fact', 'episode')),
  key          text,
  content      text not null,
  metadata     jsonb not null default '{}',
  embedding    halfvec(2048),
  importance   real not null default 0.5,
  source       text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  last_used_at timestamptz
);

create index if not exists agent_memory_embedding_idx
  on agent_memory using hnsw (embedding halfvec_cosine_ops);
create index if not exists agent_memory_content_fts_idx
  on agent_memory using gin (to_tsvector('english', content));
create index if not exists agent_memory_brand_kind_idx
  on agent_memory (brand_id, kind);
create unique index if not exists agent_memory_brand_key_uk
  on agent_memory (brand_id, key) where key is not null;

alter table agent_memory enable row level security;
