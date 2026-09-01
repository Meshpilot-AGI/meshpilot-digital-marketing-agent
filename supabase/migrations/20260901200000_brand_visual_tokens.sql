-- Machine-readable design tokens alongside the prose positioning doc.
--
-- The prose section carries art direction for anything an LLM writes (image briefs, future
-- generative paths). The deterministic card renderer needs the same intent as VALUES — exact hex,
-- format, wordmark — and deriving those by parsing markdown would be fragile and would drift.
-- One row, one source of truth, two shapes: `content` for models, `visual` for code.
alter table brand_positioning add column if not exists visual jsonb not null default '{}'::jsonb;

comment on column brand_positioning.visual is
  'Design tokens for the deterministic card renderer: bg/fg/muted/accent hex, wordmark, format.';
