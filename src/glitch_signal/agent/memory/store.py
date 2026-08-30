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
    the already-filtered set (verified facts outside an arbitrary top-N window aren't lost)."""
    qvec = await _embed_or_none(query, "query", embed_fn)
    # :qvec bound as text (String) so asyncpg can type it; text -> halfvec via CAST.
    sem = "(CASE WHEN embedding IS NULL OR :qvec IS NULL THEN 0 ELSE 1 - (embedding <=> CAST(:qvec AS halfvec)) END)"
    lex = "ts_rank(to_tsvector('english', content), plainto_tsquery('english', :q))"
    kind_clause = ""
    params: dict[str, Any] = {"brand": brand_id, "qvec": qvec, "q": query, "k": k,
                              "w_sem": W_SEM, "w_lex": W_LEX}
    if kinds:
        valid = [k2 for k2 in kinds if k2 in ("fact", "episode")]
        kind_clause = "AND kind = ANY(string_to_array(:kinds_csv, ',')::text[])"
        params["kinds_csv"] = ",".join(valid)
    verified_clause = ""
    if verified_only:                     # mirror is_verified_provenance() in SQL (typed flag OR exact source)
        verified_clause = ("AND (lower(coalesce(source, '')) = ANY(string_to_array(:vsrc_csv, ',')::text[]) "
                           "OR lower(coalesce(metadata->>'verified', '')) IN ('true', '1', 'yes'))")
        params["vsrc_csv"] = ",".join(sorted(VERIFIED_SOURCES))
    sql = text(f"""
        SELECT id, brand_id, kind, key, content, metadata, importance, source,
               created_at, last_used_at,
               {sem} AS semantic, {lex} AS lexical,
               (:w_sem * {sem} + :w_lex * {lex}) AS score
        FROM agent_memory
        WHERE brand_id = :brand {kind_clause} {verified_clause}
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
