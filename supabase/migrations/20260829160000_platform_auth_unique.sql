-- Close the platform_auth upsert TOCTOU (#105): oauth/storage.py does SELECT-then-INSERT/UPDATE on
-- (brand_id, platform, account_identifier), so two concurrent connects could both insert. A unique
-- index makes the write atomic (the loser conflicts instead of duplicating). account_identifier is
-- nullable, and Postgres treats NULLs as distinct in a plain unique index, so key on
-- coalesce(account_identifier,'') to also dedup the null case.

create unique index if not exists platform_auth_brand_platform_acct_uidx
  on platform_auth (brand_id, platform, coalesce(account_identifier, ''));
