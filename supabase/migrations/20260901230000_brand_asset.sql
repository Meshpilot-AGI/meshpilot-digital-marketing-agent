-- BRAND ASSET LIBRARY — real image files the creative pipeline composites in.
--
-- Why the pipeline needs this rather than generating everything: an image model cannot render a
-- third-party mark. Asked for the FTMO or MT5 logo it produces a mangled approximation, which looks
-- worse than no logo AND misrepresents a real trademark. Logos have to be REAL FILES placed by code
-- — which is also why the composite route (generated backdrop + code-drawn layer) is the only one
-- that can carry a post like "FTMO vs Apex daily drawdown".
--
-- `owner_brand` is the tenant whose library this is; `slug`/`name` identify the depicted brand,
-- which may be a third party (a prop firm or trading platform we integrate with).
create table if not exists brand_asset (
  id           uuid primary key default gen_random_uuid(),
  owner_brand  text not null,
  kind         text not null,            -- logo | product_shot | icon | backdrop
  slug         text not null,            -- stable id of the depicted brand/subject
  name         text not null,            -- display name, e.g. "FTMO"
  url          text not null,
  width        int,
  height       int,
  accent       text,                     -- the depicted brand's colour hint, when known
  usage_note   text,                     -- e.g. "affiliate partner; factual comparison use"
  created_at   timestamptz not null default now(),
  unique (owner_brand, kind, slug)
);

create index if not exists brand_asset_owner_kind on brand_asset (owner_brand, kind);
alter table brand_asset enable row level security;

comment on table brand_asset is
  'Real image files (logos, product shots) the creative pipeline composites — never generated.';
