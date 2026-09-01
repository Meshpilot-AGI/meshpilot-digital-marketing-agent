"""Per-brand agent memory store (AGENT-MEM).

`remember` embeds content (passage) and upserts a fact (by key) or appends an episode.
`recall` embeds the query (query) and returns top-k memories by a fused score:
    score = w_sem * cosine_similarity + w_lex * ts_rank
tie-broken by importance then recency; the winners' `last_used_at` is bumped.

Embedding failures never block a write (row stored with NULL embedding, still lexically
searchable) or a read (falls back to lexical-only). Both the SQLAlchemy `engine` and the
`embed_fn` are injectable so this unit-tests without a DB or network.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Sequence

import structlog
from sqlalchemy import String, bindparam, text

from glitch_signal.agent.memory import embeddings as emb
from glitch_signal.agent.memory.spec import Memory
from glitch_signal.db.session import _engine

log = structlog.get_logger(__name__)

# Fusion weights (semantic favored). Tunable later via config.
W_SEM = 0.7
W_LEX = 0.3

# recall() candidate-pool sizing (#101): each stage (semantic <=> order, lexical ts_rank order)
# pulls this many rows before the two are unioned and re-ranked by the fused score.
CANDIDATE_POOL_MULTIPLIER = 8
CANDIDATE_POOL_MIN = 40

# Operator-verified provenance. Trust is conferred ONLY by the trusted verification workflow — never by
# arbitrary `source` text (an agent- or curator-written "fact" must not be able to pass as verified). A
# fact is authoritative iff its metadata carries a typed `verified` flag OR its `source` is one of these
# reserved, EXACT tokens. The agent's own tools write source=agent_loop / curator, never these; exact
# matching also stops negated/unrelated values (e.g. "unverified", "self-verified") from slipping through.
VERIFIED_SOURCES = frozenset({"operator_verified", "operator-verified"})


def is_verified_provenance(source: str | None, metadata: dict[str, Any] | None = None) -> bool:
    """True iff this memory carries operator-verified provenance (typed metadata flag or exact source)."""
    if metadata and str(metadata.get("verified", "")).strip().lower() in ("true", "1", "yes"):
        return True
    return (source or "").strip().lower() in VERIFIED_SOURCES

EmbedFn = Callable[..., Awaitable[list[list[float]]]]

_MAX_CONTENT_LEN = 4000  # cap on a stored fact/episode (poisoning + bloat guard, #100)


async def _embed_or_none(text_value: str, input_type: str, embed_fn: EmbedFn | None) -> str | None:
    fn = embed_fn or emb.embed
    try:
        vecs = await fn([text_value], input_type=input_type)
        return emb.to_halfvec_literal(vecs[0]) if vecs else None
    except Exception as exc:  # noqa: BLE001 — degrade to lexical, never block
        log.warning("agent.memory.embed_failed", input_type=input_type, error=str(exc)[:200])
        return None


def _or_tsquery(query: str) -> str:
    """Turn free text into an OR `to_tsquery` string: 'a b c' -> 'a | b | c'.

    `to_tsquery` parses operator syntax, so raw user text would raise on `&`, `!`, `:` or a stray
    quote. Reduce to alphanumeric word tokens and join with `|`. Returns '' when nothing survives,
    which callers must treat as "no lexical filter" rather than passing an empty tsquery.
    """
    import re as _re

    words = [w for w in _re.findall(r"[A-Za-z0-9]+", query or "") if len(w) > 1]
    return " | ".join(words[:32])


def _row_to_memory(r: Any) -> Memory:
    m = r._mapping
    meta = m["metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    return Memory(
        id=str(m["id"]),
        brand_id=m["brand_id"],
        kind=m["kind"],
        content=m["content"],
        key=m.get("key"),
        metadata=meta or {},
        importance=float(m["importance"]),
        source=m.get("source"),
        created_at=m.get("created_at"),
        last_used_at=m.get("last_used_at"),
        score=float(m["score"]) if "score" in m and m["score"] is not None else None,
        semantic=float(m["semantic"]) if "semantic" in m and m["semantic"] is not None else None,
        lexical=float(m["lexical"]) if "lexical" in m and m["lexical"] is not None else None,
    )


_UPSERT_FACT = text("""
INSERT INTO agent_memory (brand_id, kind, key, content, metadata, embedding, importance, source)
VALUES (:brand, :kind, :key, :content, CAST(:metadata AS jsonb), CAST(:emb AS halfvec), :importance, :source)
ON CONFLICT (brand_id, key) WHERE key IS NOT NULL
DO UPDATE SET content = EXCLUDED.content, metadata = EXCLUDED.metadata,
              embedding = EXCLUDED.embedding, importance = EXCLUDED.importance,
              source = EXCLUDED.source, updated_at = now()
RETURNING id, created_at
""")

_INSERT_MEM = text("""
INSERT INTO agent_memory (brand_id, kind, key, content, metadata, embedding, importance, source)
VALUES (:brand, :kind, :key, :content, CAST(:metadata AS jsonb), CAST(:emb AS halfvec), :importance, :source)
RETURNING id, created_at
""")


async def remember(
    brand_id: str,
    kind: str,
    content: str,
    *,
    key: str | None = None,
    metadata: dict[str, Any] | None = None,
    importance: float = 0.5,
    source: str | None = None,
    embed_fn: EmbedFn | None = None,
    engine: Any = None,
) -> Memory:
    """Store a fact (upsert by key) or episode. Returns the stored Memory."""
    if kind not in ("fact", "episode"):
        raise ValueError(f"kind must be 'fact' or 'episode', got {kind!r}")
    # Bound durable-memory content at the single write choke point (#100): a curated fact is recalled
    # into every future prompt, so an over-long (poisoning/bloat) payload is truncated. Provenance is
    # already recorded via `source`.
    if len(content) > _MAX_CONTENT_LEN:
        content = content[:_MAX_CONTENT_LEN] + " …[truncated]"
    emb_literal = await _embed_or_none(content, "passage", embed_fn)
    params = {
        "brand": brand_id, "kind": kind, "key": key, "content": content,
        "metadata": json.dumps(metadata or {}), "emb": emb_literal,
        "importance": importance, "source": source,
    }
    stmt = _UPSERT_FACT if (kind == "fact" and key is not None) else _INSERT_MEM
    eng = engine or _engine()
    async with eng.begin() as conn:
        row = (await conn.execute(stmt, params)).first()
    return Memory(
        id=str(row[0]), brand_id=brand_id, kind=kind, content=content, key=key,
        metadata=metadata or {}, importance=importance, source=source, created_at=row[1],
    )


async def recall(
    brand_id: str,
    query: str,
    *,
    k: int = 8,
    kinds: Sequence[str] | None = None,
    verified_only: bool = False,
    embed_fn: EmbedFn | None = None,
    engine: Any = None,
) -> list[Memory]:
    """Return top-k memories for a brand by fused semantic + lexical relevance.

    `verified_only` restricts to operator-verified provenance IN THE QUERY, so `LIMIT :k` is applied to
    the already-filtered set (verified facts outside an arbitrary top-N window aren't lost).

    Two-stage retrieval (#101): fusing `w_sem*cosine + w_lex*ts_rank` directly in a single
    `ORDER BY` over the whole brand partition stops Postgres from using the `<=>` HNSW index —
    it becomes an O(n) exact-distance recompute per call as memory grows. Instead, pull a
    candidate pool via two INDEX-ELIGIBLE ORDER BYs (raw `<=>` distance, and `ts_rank` separately),
    union their ids, and only fuse/re-rank that small candidate set."""
    qvec = await _embed_or_none(query, "query", embed_fn)
    # :qvec bound as text (String) so asyncpg can type it; text -> halfvec via CAST.
    sem = "(CASE WHEN embedding IS NULL OR :qvec IS NULL THEN 0 ELSE 1 - (embedding <=> CAST(:qvec AS halfvec)) END)"
    # OR-semantics, not plainto_tsquery's AND. `plainto_tsquery('brand identity product pricing')`
    # requires a row to contain EVERY term, which almost nothing does — and because the lexical CTE
    # uses this as a hard `@@` filter for index eligibility, an AND query makes it return nothing.
    # That silently defeats the documented "degrade to lexical, never block" fallback whenever the
    # embedding fails: recall returns ZERO memories, and the caller sees empty grounding rather than
    # an error. Empty grounding is precisely what let the agent invent its own brand positioning.
    lex_expr_src = "ts_rank(to_tsvector('english', content), to_tsquery('english', :qts))"
    kind_clause = ""
    cand_k = max(k * CANDIDATE_POOL_MULTIPLIER, CANDIDATE_POOL_MIN)
    qts = _or_tsquery(query)
    # An empty tsquery is a SYNTAX ERROR in Postgres, not an empty match — so a query that reduces to
    # no usable tokens must drop the lexical filter entirely and fall back to recency. Combined with
    # the OR semantics above, this makes "no candidates at all" unreachable: callers always get some
    # grounding to work from, which is the invariant that failed here.
    lex = lex_expr_src if qts else "0"
    lex_filter = "AND to_tsvector('english', content) @@ to_tsquery('english', :qts)" if qts else ""
    lex_order = ("ts_rank(to_tsvector('english', content), to_tsquery('english', :qts)) DESC"
                 if qts else "importance DESC, created_at DESC")
    params: dict[str, Any] = {"brand": brand_id, "qvec": qvec, "q": query, "k": k, "qts": qts,
                              "w_sem": W_SEM, "w_lex": W_LEX, "cand_k": cand_k}
    if kinds:
        valid = [k2 for k2 in kinds if k2 in ("fact", "episode")]
        kind_clause = "AND kind = ANY(string_to_array(:kinds_csv, ',')::text[])"
        params["kinds_csv"] = ",".join(valid)
    verified_clause = ""
    if verified_only:                     # mirror is_verified_provenance() in SQL (typed flag OR exact source)
        verified_clause = ("AND (lower(coalesce(source, '')) = ANY(string_to_array(:vsrc_csv, ',')::text[]) "
                           "OR lower(coalesce(metadata->>'verified', '')) IN ('true', '1', 'yes'))")
        params["vsrc_csv"] = ",".join(sorted(VERIFIED_SOURCES))
    # Semantic candidates: ORDER BY the raw `<=>` operator (index-eligible) — skipped entirely when
    # embedding the query failed (:qvec IS NULL), since ordering by distance-to-NULL is meaningless.
    sem_cand = "" if qvec is None else f"""
        sem_cand AS (
            SELECT id FROM agent_memory
            WHERE brand_id = :brand AND embedding IS NOT NULL {kind_clause} {verified_clause}
            ORDER BY embedding <=> CAST(:qvec AS halfvec)
            LIMIT :cand_k
        ),
    """
    candidates_union = "SELECT id FROM lex_cand" if qvec is None else "SELECT id FROM sem_cand UNION SELECT id FROM lex_cand"
    sql = text(f"""
        WITH {sem_cand}
        lex_cand AS (
            SELECT id FROM agent_memory
            WHERE brand_id = :brand {lex_filter} {kind_clause} {verified_clause}
            ORDER BY {lex_order}
            LIMIT :cand_k
        ),
        candidates AS ({candidates_union})
        SELECT m.id, m.brand_id, m.kind, m.key, m.content, m.metadata, m.importance, m.source,
               m.created_at, m.last_used_at,
               {sem} AS semantic, {lex} AS lexical,
               (:w_sem * {sem} + :w_lex * {lex}) AS score
        FROM agent_memory m
        JOIN candidates c ON c.id = m.id
        ORDER BY score DESC, importance DESC, created_at DESC
        LIMIT :k
    """).bindparams(bindparam("qvec", type_=String))
    eng = engine or _engine()
    async with eng.connect() as conn:
        rows = (await conn.execute(sql, params)).fetchall()
        mems = [_row_to_memory(r) for r in rows]
        if mems:
            await conn.execute(
                text("UPDATE agent_memory SET last_used_at = now() "
                     "WHERE id = ANY(string_to_array(:ids_csv, ',')::uuid[])")
                .bindparams(bindparam("ids_csv", type_=String)),
                {"ids_csv": ",".join(m.id for m in mems)},
            )
            await conn.commit()
    return mems


async def forget(memory_id: str, *, engine: Any = None) -> bool:
    eng = engine or _engine()
    async with eng.begin() as conn:
        res = await conn.execute(text("DELETE FROM agent_memory WHERE id = :id"), {"id": memory_id})
    return res.rowcount > 0


# ── Operator verification (the only write path allowed to confer verified provenance) ─────────
#
# `recall(verified_only=True)` and `is_verified_provenance()` above deliberately trust nothing the
# agent itself writes (source=agent_loop / curator). These three functions are THE key to that
# lock: they are meant to be called only from an operator-authenticated /internal route (never from
# agent tools), and every write is brand-scoped so one brand's operator call can never read or
# mutate another brand's rows (mirrors the `_BRAND_PRED` IDOR fix, #95, in agent/cron/store.py).

_MEM_LIST_LIMIT = 500  # bound operator review-queue listing, same guard as cron's _LIST_LIMIT (#105)


async def list_memories(
    brand_id: str,
    *,
    kind: str | None = None,
    limit: int = 100,
    engine: Any = None,
) -> list[Memory]:
    """List a brand's memories (operator review queue) — brand-scoped, never another brand's rows.

    Callers determine pass/fail of the verified gate themselves via `is_verified_provenance(m.source,
    m.metadata)`; this function does no filtering on that dimension so the operator can see what is
    currently un-trusted (the whole point of a review queue) alongside what already qualifies.
    """
    if kind is not None and kind not in ("fact", "episode"):
        raise ValueError(f"kind must be 'fact' or 'episode', got {kind!r}")
    limit = max(1, min(int(limit), _MEM_LIST_LIMIT))
    kind_clause = "AND kind = :kind" if kind else ""
    sql = text(f"""
        SELECT id, brand_id, kind, key, content, metadata, importance, source, created_at, last_used_at
        FROM agent_memory
        WHERE brand_id = :brand {kind_clause}
        ORDER BY created_at DESC
        LIMIT :limit
    """)
    params: dict[str, Any] = {"brand": brand_id, "limit": limit}
    if kind:
        params["kind"] = kind
    eng = engine or _engine()
    async with eng.connect() as conn:
        rows = (await conn.execute(sql, params)).fetchall()
    return [_row_to_memory(r) for r in rows]


# `original_source` preserves the pre-verification `source` value (jsonb_build_object reads the row's
# own `source` column) so we never lose provenance history when an operator overrides it.
_VERIFY_MEMORIES = text("""
    UPDATE agent_memory
    SET metadata = coalesce(metadata, '{}'::jsonb) || jsonb_build_object(
            'verified', true,
            'verified_by', :verified_by,
            'verified_at', :verified_at,
            'original_source', source
        ),
        updated_at = now()
    WHERE brand_id = :brand AND id = ANY(string_to_array(:ids_csv, ',')::uuid[])
    RETURNING id
""").bindparams(bindparam("ids_csv", type_=String))

# Revoke: drop the verification breadcrumbs (so `metadata->>'verified'` no longer reads true) and
# stamp who/when took trust back. `original_source`/`verified_by`/`verified_at` are removed rather
# than left stale; a fresh revoke breadcrumb replaces them.
_UNVERIFY_MEMORIES = text("""
    UPDATE agent_memory
    SET metadata = (coalesce(metadata, '{}'::jsonb) - 'verified' - 'verified_by' - 'verified_at' - 'original_source')
                   || jsonb_build_object('revoked_by', :revoked_by, 'revoked_at', :revoked_at),
        updated_at = now()
    WHERE brand_id = :brand AND id = ANY(string_to_array(:ids_csv, ',')::uuid[])
    RETURNING id
""").bindparams(bindparam("ids_csv", type_=String))


async def set_verified(
    brand_id: str,
    memory_ids: Sequence[str],
    *,
    verified_by: str = "operator",
    engine: Any = None,
) -> list[str]:
    """Grant operator-verified provenance to the given memory ids for ONE brand.

    This is the write path the recall(verified_only=True) gate exists to require — the agent's own
    tools never call it. Brand-scoped: `WHERE brand_id = :brand AND id = ANY(...)` means an id that
    belongs to a different brand is silently excluded from the result rather than acted on (#95).
    Returns the ids actually updated (a subset of `memory_ids` when some don't exist or belong to
    another brand).
    """
    if not memory_ids:
        return []
    eng = engine or _engine()
    async with eng.begin() as conn:
        rows = (await conn.execute(_VERIFY_MEMORIES, {
            "brand": brand_id,
            "ids_csv": ",".join(memory_ids),
            "verified_by": verified_by,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        })).fetchall()
    return [str(r[0]) for r in rows]


async def unset_verified(
    brand_id: str,
    memory_ids: Sequence[str],
    *,
    revoked_by: str = "operator",
    engine: Any = None,
) -> list[str]:
    """Revoke operator-verified provenance from the given memory ids for ONE brand (the operator
    taking trust back). Brand-scoped the same way as `set_verified` (#95). Returns the ids actually
    updated."""
    if not memory_ids:
        return []
    eng = engine or _engine()
    async with eng.begin() as conn:
        rows = (await conn.execute(_UNVERIFY_MEMORIES, {
            "brand": brand_id,
            "ids_csv": ",".join(memory_ids),
            "revoked_by": revoked_by,
            "revoked_at": datetime.now(timezone.utc).isoformat(),
        })).fetchall()
    return [str(r[0]) for r in rows]
