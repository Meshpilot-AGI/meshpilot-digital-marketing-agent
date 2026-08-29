"""DB URL normalization: Supabase DATABASE_URL → asyncpg driver + connect args.

Pure-logic tests (no live database). Covers driver normalization, SSL and
pgbouncer-pooler handling, and the SIGNAL_DB_URL vs DATABASE_URL precedence.
"""
from glitch_signal.config import (
    _LOCAL_DB_DEFAULT,
    Settings,
    _asyncpg_connect_args,
    _to_asyncpg_url,
)


def test_scheme_normalized_to_asyncpg():
    assert _to_asyncpg_url("postgres://u:p@h:5432/db").startswith("postgresql+asyncpg://")
    assert _to_asyncpg_url("postgresql://u:p@h:5432/db").startswith("postgresql+asyncpg://")
    # already-qualified stays put (no double prefix)
    already = "postgresql+asyncpg://u:p@h:5432/db"
    assert _to_asyncpg_url(already) == already


def test_supabase_direct_strips_sslmode_and_requires_ssl():
    url = "postgresql://postgres:pw@db.abcxyz.supabase.co:5432/postgres?sslmode=require"
    clean, args = _asyncpg_connect_args(_to_asyncpg_url(url))
    assert "sslmode" not in clean  # asyncpg rejects the libpq param
    assert args["ssl"] is True
    assert "statement_cache_size" not in args  # 5432 direct = prepared stmts OK


def test_supabase_transaction_pooler_disables_stmt_cache():
    url = "postgresql://postgres.abcxyz:pw@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
    clean, args = _asyncpg_connect_args(_to_asyncpg_url(url))
    assert args["ssl"] is True
    assert args["statement_cache_size"] == 0  # pgbouncer transaction mode


def test_local_default_needs_no_ssl():
    clean, args = _asyncpg_connect_args(_to_asyncpg_url(_LOCAL_DB_DEFAULT))
    assert args == {}


def test_precedence_database_url_used_when_signal_unset():
    s = Settings(
        _env_file=None,
        database_url="postgresql://postgres:pw@db.x.supabase.co:5432/postgres?sslmode=require",
    )
    assert s.resolved_db_url().startswith("postgresql+asyncpg://")
    assert "db.x.supabase.co" in s.resolved_db_url()
    assert s.db_connect_args()["ssl"] is True


def test_precedence_explicit_signal_url_wins():
    explicit = "postgresql+asyncpg://me:secret@myhost:5432/mine"
    s = Settings(
        _env_file=None,
        signal_db_url=explicit,
        database_url="postgresql://postgres:pw@db.x.supabase.co:5432/postgres",
    )
    assert s.resolved_db_url() == explicit
