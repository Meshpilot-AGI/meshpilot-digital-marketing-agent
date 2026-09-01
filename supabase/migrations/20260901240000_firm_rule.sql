-- FIRM RULE knowledge base — verified prop-firm thresholds the agent may state in public content.
--
-- Why a dedicated, structured table rather than free-text facts: a rule is a precise, dated,
-- attributable claim about a THIRD PARTY's product, published under an affiliate relationship.
-- Getting one wrong is a factual misstatement about a partner, and the conscience critic will not
-- catch it — its prohibitions cover OUR invented figures, and a competitor's threshold reads to it
-- like a legitimate fact. So the numbers cannot come from a model; they come from here or the post
-- does not state them.
--
-- `publishable` is the load-bearing column. The upstream engine table contains values that are
-- CORRECT for backtesting and WRONG as public claims:
--   * synthetic gates (FundingPips Zero has no real profit target; 2% is an engine pass-condition)
--   * sentinel zeros (minProfitableDays = 0 means "this firm has no such rule", not "zero days")
--   * historical rules for a firm that is not currently selling (MyForexFunds, pending relaunch)
-- Each of those is a plausible-sounding sentence that would be false in public.
create table if not exists firm_rule (
  id          uuid primary key default gen_random_uuid(),
  firm_id     text not null,
  firm_name   text not null,
  rule_key    text not null,        -- profit_target | daily_loss | max_drawdown | ...
  value_num   numeric,              -- decimal fraction (0.05 = 5%)
  value_text  text not null,        -- the human phrasing the agent may quote
  stage       text not null default 'eval',   -- eval | funded — rules differ per stage
  firm_status text not null default 'live',
  publishable boolean not null default false,
  caveat      text,                 -- why it is not publishable, or how it must be qualified
  source      text not null,
  as_of       date not null,
  created_at  timestamptz not null default now(),
  unique (firm_id, rule_key, stage)
);

create index if not exists firm_rule_publishable on firm_rule (firm_id) where publishable;
alter table firm_rule enable row level security;

comment on table firm_rule is
  'Verified prop-firm thresholds. Only publishable=true rows may appear in public content.';
