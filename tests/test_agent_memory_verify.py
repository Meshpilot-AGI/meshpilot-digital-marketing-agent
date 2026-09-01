"""Operator verification (AGENT-MEM) — list/verify/unverify write path + brand-scoping (#95).

`store.py`'s VERIFIED_SOURCES gate is deliberate: the agent's own tools (source=agent_loop /
curator) must never be able to self-certify a fact. These tests cover the write path that
DOES confer operator-verified provenance: list_memories() (the review queue), set_verified()
(grant), and unset_verified() (revoke) — plus that all three are brand-scoped so one brand's
call can never read or mutate another brand's rows.
"""
from __future__ import annotations

import pytest

from glitch_signal.agent.memory import store
from glitch_signal.agent.memory.spec import Memory


# ── fakes (mirrors tests/test_agent_memory.py) ─────────────────────────
class _Result:
    def __init__(self, rows=None, rowcount=0):
        self._rows = rows or []
        self.rowcount = rowcount

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _Row:
    """Mimics a SQLAlchemy Row with ._mapping."""
    def __init__(self, mapping):
        self._mapping = mapping


class _Conn:
    def __init__(self, engine):
        self.engine = engine

    async def execute(self, stmt, params=None):
        self.engine.calls.append((str(stmt), params or {}))
        return self.engine._results.pop(0) if self.engine._results else _Result()

    async def commit(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeEngine:
    def __init__(self):
        self.calls = []
        self._results = []

    def queue(self, res):
        self._results.append(res)

    def begin(self):
        return _Conn(self)

    def connect(self):
        return _Conn(self)


def _mem_row(id_, *, source=None, metadata=None):
    return _Row({
        "id": id_, "brand_id": "glitch_executor", "kind": "fact", "key": "audience",
        "content": "GE audience = prop traders", "metadata": metadata or {}, "importance": 0.9,
        "source": source, "created_at": None, "last_used_at": None,
    })


# ── list_memories ───────────────────────────────────────────────────────
async def test_list_memories_scopes_by_brand_and_kind():
    eng = FakeEngine()
    eng.queue(_Result(rows=[_mem_row("m1")]))
    mems = await store.list_memories("glitch_executor", kind="fact", engine=eng)
    assert len(mems) == 1 and isinstance(mems[0], Memory) and mems[0].id == "m1"
    sql, params = eng.calls[0]
    assert "WHERE brand_id = :brand" in sql and "kind = :kind" in sql
    assert params["brand"] == "glitch_executor" and params["kind"] == "fact"


async def test_list_memories_rejects_bad_kind():
    with pytest.raises(ValueError, match="kind must be"):
        await store.list_memories("glitch_executor", kind="bogus", engine=FakeEngine())


async def test_list_memories_caps_limit():
    eng = FakeEngine()
    eng.queue(_Result(rows=[]))
    await store.list_memories("glitch_executor", limit=999999, engine=eng)
    _, params = eng.calls[0]
    assert params["limit"] == store._MEM_LIST_LIMIT


# ── set_verified ─────────────────────────────────────────────────────────
async def test_set_verified_sets_the_flag():
    eng = FakeEngine()
    eng.queue(_Result(rows=[("m1",)]))
    ids = await store.set_verified("glitch_executor", ["m1"], engine=eng)
    assert ids == ["m1"]
    sql, params = eng.calls[0]
    assert "verified" in sql and "verified_by" in sql and "verified_at" in sql and "original_source" in sql
    assert params["brand"] == "glitch_executor" and params["ids_csv"] == "m1"
    assert params["verified_by"] == "operator"
    # the fact this fact is now trusted is verifiable through the same gate recall() uses:
    assert store.is_verified_provenance("agent_loop", {"verified": True}) is True


async def test_set_verified_empty_ids_is_a_noop():
    eng = FakeEngine()
    assert await store.set_verified("glitch_executor", [], engine=eng) == []
    assert eng.calls == []  # never touches the DB for an empty request


# ── unset_verified ───────────────────────────────────────────────────────
async def test_unset_verified_clears_the_flag():
    eng = FakeEngine()
    eng.queue(_Result(rows=[("m1",)]))
    ids = await store.unset_verified("glitch_executor", ["m1"], engine=eng)
    assert ids == ["m1"]
    sql, params = eng.calls[0]
    assert "- 'verified'" in sql and "revoked_by" in sql and "revoked_at" in sql
    assert params["brand"] == "glitch_executor" and params["ids_csv"] == "m1"
    # post-revoke, the gate must no longer consider it verified (mirrors the real UPDATE's effect)
    assert store.is_verified_provenance("agent_loop", {"revoked_by": "operator"}) is False


async def test_unset_verified_empty_ids_is_a_noop():
    eng = FakeEngine()
    assert await store.unset_verified("glitch_executor", [], engine=eng) == []
    assert eng.calls == []


# ── brand scoping (#95) ───────────────────────────────────────────────────
async def test_set_verified_is_brand_scoped_in_the_query():
    """The UPDATE's WHERE clause must filter on brand_id, not just id — this is what stops brand
    A's operator call from verifying brand B's memory, mirroring agent/cron/store.py's _BRAND_PRED
    fix for #95."""
    eng = FakeEngine()
    eng.queue(_Result(rows=[("m1",)]))
    await store.set_verified("glitch_executor", ["m1"], engine=eng)
    sql, params = eng.calls[0]
    assert "WHERE brand_id = :brand AND id = ANY" in sql
    assert params["brand"] == "glitch_executor"


async def test_set_verified_cross_brand_id_is_excluded():
    """Simulates the real DB behavior: an id belonging to another brand is filtered out by the
    brand-scoped WHERE clause, so it never comes back in RETURNING — set_verified must report it
    as not-updated rather than assuming success."""
    eng = FakeEngine()
    # Two ids requested ("m1" owned by glitch_executor, "m2" owned by another brand) — the DB
    # only returns "m1" because the WHERE brand_id=:brand clause excluded "m2".
    eng.queue(_Result(rows=[("m1",)]))
    updated = await store.set_verified("glitch_executor", ["m1", "m2"], engine=eng)
    assert updated == ["m1"]
    assert "m2" not in updated
    _, params = eng.calls[0]
    assert params["ids_csv"] == "m1,m2"  # both requested, but the brand predicate does the filtering


async def test_unset_verified_cross_brand_id_is_excluded():
    eng = FakeEngine()
    eng.queue(_Result(rows=[("m1",)]))
    updated = await store.unset_verified("brand_a", ["m1", "m2-owned-by-brand-b"], engine=eng)
    assert updated == ["m1"]
    sql, params = eng.calls[0]
    assert "WHERE brand_id = :brand AND id = ANY" in sql
    assert params["brand"] == "brand_a"
