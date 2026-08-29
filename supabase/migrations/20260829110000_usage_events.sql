-- Per-brand cost/usage accounting across every vendor (COST-METER INC-1).
-- Vendors bill at the ACCOUNT level (most have no per-tenant tagging), so we self-meter every
-- model/media call at our own choke points, attributing it to the brand that triggered it and
-- computing an estimated cost from a maintained price book. This table is the single source of
-- truth; balance-delta reconciliation (INC-2) validates it against each vendor's aggregate.

create table if not exists usage_events (
  id           uuid primary key default gen_random_uuid(),
  brand_id     text not null,
  vendor       text not null,               -- 'anthropic' | 'higgsfield' | 'muapi' | 'heygen' | 'nvidia'
  operation    text not null,               -- 'chat' | 'embed' | 'image.generate' | 'video.generate' | …
  model        text,                         -- vendor model / application slug
  units        jsonb not null default '{}',  -- {input_tokens, output_tokens, cache_*, credits, images, …}
  cost_usd     numeric(12,6) not null default 0,  -- estimated USD from the price book
  estimated    boolean not null default true,     -- false once reconciled against the vendor bill
  request_id   text,                         -- vendor request id, for reconciliation/dedup
  created_at   timestamptz not null default now()
);

create index if not exists usage_events_brand_created_idx on usage_events (brand_id, created_at desc);
create index if not exists usage_events_vendor_created_idx on usage_events (vendor, created_at desc);

alter table usage_events enable row level security;  -- service-role only
