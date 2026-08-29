# Design Spec — Agent Brain (memory + agent capabilities)

**Date:** 2026-08-29 · **Status:** AGENT-MEM DONE (verified live) · increments 2–4 pending · **Method:** brainstorming → spec → build

## Goal

Turn the current agent from a **fixed LangGraph video pipeline** (scout → script →
storyboard → video → publish; deterministic nodes, no reasoning, no memory) into a
**memory-backed, LLM-driven agent** that recalls context, decides actions, uses the
capabilities it already has (media generation, storage, publishing — all as tools),
and learns from experience. Per-brand throughout; runs on the deployed app.

Prior art studied: **Hermes** (NousResearch — memory-first + self-improving SKILL.md
skills + curator + context compression) and **OpenClaw** (trusted-gateway / untrusted-
execution / deterministic-policy). Both are local personal-assistant CLIs, so we adopt
their *patterns* on our cloud/multi-brand stack rather than wrap either.

## Decomposition (build order — one increment at a time)

1. **AGENT-MEM** ← this spec. Per-brand memory in Supabase (facts + episodes + hybrid recall).
2. **AGENT-LOOP** — muapi-LLM loop: assemble context (memory + skills) → plan → call
   capability-tools → verify → write episode.
3. **AGENT-POLICY** — OpenClaw-style gate: allow/deny each action before execution
   (posting stays gated until explicitly enabled).
4. **AGENT-LEARN** — Hermes-style curator: distill episodes → durable facts + new/updated
   skills; consolidate + archive.

Each increment gets its own plan + PR + verification. Everything below is **AGENT-MEM only.**

---

## AGENT-MEM — per-brand memory

### Memory kinds
- **fact** — durable, human-readable brand knowledge, editable ("GE audience = prop-firm
  traders", "hook style X performs", product truth, voice rules). The `MEMORY.md` analog,
  as per-brand rows.
- **episode** — append-only log of what the agent did + the outcome ("generated logo via
  muapi → stored ge-media → (later) engagement N").

### Retrieval — hybrid
`recall(brand_id, query, k)` fuses two signals (Hermes uses FTS5 + LLM summarize; we use):
- **semantic**: pgvector cosine over the embedding (NVIDIA nemotron-3-embed-1b, `input_type=query`).
- **lexical**: Postgres full-text / `pg_trgm` over `content` (cheap, exact-term recall).
Fuse by normalized score (semantic weighted higher), tie-break by `importance` then recency;
bump `last_used_at` on the winners. `kinds=` filters fact/episode.

### Schema — one new `supabase/migrations/<ts>_agent_memory.sql`
```
create extension if not exists vector;          -- pgvector 0.8.2 (available)
create table if not exists agent_memory (
  id           uuid primary key default gen_random_uuid(),
  brand_id     text not null,
  kind         text not null check (kind in ('fact','episode')),
  key          text,                              -- optional dedupe/lookup key for facts
  content      text not null,
  metadata     jsonb not null default '{}',
  embedding    halfvec(2048),                     -- nemotron-3-embed-1b; halfvec → HNSW ok (>2000 dims)
  importance   real not null default 0.5,
  source       text,                              -- who wrote it (loop node, curator, operator)
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  last_used_at timestamptz
);
create index on agent_memory using hnsw (embedding halfvec_cosine_ops);
create index on agent_memory using gin (to_tsvector('english', content));
create index on agent_memory (brand_id, kind);
create unique index on agent_memory (brand_id, key) where key is not null;  -- facts upsert by key
alter table agent_memory enable row level security;
```
Idempotent (matches the SUPA-MIGRATE convention). Applies via the Supabase GitHub integration;
CI `db` job validates it from scratch.

### Embeddings — NVIDIA NIM
- Endpoint: `POST https://integrate.api.nvidia.com/v1/embeddings` (OpenAI-compatible),
  model `nvidia/nemotron-3-embed-1b` (2048-dim, verified live 2026-08-29), `input_type`
  `passage` (store) / `query` (recall), `encoding_format=float`. httpx from the app —
  the same pattern as muapi/Meta/Buffer.
- Key: **`NVIDIA_API_KEY`** — a **global infra** key (embeddings are a shared capability,
  not a brand identity), set as a cloud secret. Overridable model via `NVIDIA_EMBED_MODEL`.
- Rationale over Supabase gte-small: gte-small is good (384-dim, ≈OpenAI-small) but runs
  ONLY in a Supabase Edge Function → an edge hop our app-centric design doesn't otherwise
  use. NVIDIA is a direct httpx call that fits, with a stronger multilingual model.

### Code — `src/glitch_signal/agent/memory/`
- `embeddings.py` — `async embed(texts, input_type) -> list[list[float]]` (NVIDIA httpx;
  batch; injectable for tests). Raises on missing key.
- `store.py` — `async remember(brand_id, kind, content, *, key=None, metadata=None,
  importance=0.5, source=None) -> Memory` (embed passage → upsert; facts upsert on key);
  `async recall(brand_id, query, *, k=8, kinds=None) -> list[Memory]` (hybrid); `update`,
  `forget`. asyncpg via the app's DSN.
- `spec.py` — `Memory` dataclass.
- `__init__.py` — `remember`, `recall`.

### Endpoints (jobs-auth, x-jobs-token)
- `POST /internal/agent/remember` — {brand?, kind, content, key?, metadata?, importance?}.
- `POST /internal/agent/recall` — {brand?, query, k?, kinds?} → ranked memories.
(For AGENT-LOOP to use + for live verification. Supersedes `brain.py`'s external mirror,
which becomes a no-op / removed in a later increment.)

### Per-brand
Every row is `brand_id`-scoped; `recall`/`remember` always take a brand. No global memory
(matches the per-brand-keys principle; embeddings key is infra, not brand identity).

### Testing
- Unit (no network): recall ranking with an **injected fake embedder** + a small in-memory
  or transaction-rolled-back set — hybrid fusion, kind filter, importance/recency tie-break,
  fact upsert-by-key. Embeddings module tested against a stubbed httpx.
- Migration: CI `db` job applies it from scratch (halfvec + HNSW build).
- Live (verification): `POST /internal/agent/remember` two GE facts → `POST /internal/agent/
  recall` a paraphrase → the semantically-matching fact ranks first. Confirm on the deployed app.

### Out of scope (AGENT-MEM)
The LLM loop, the policy gate, and the curator/learning are increments 2–4. This increment
ships the memory substrate + read/write API only.

## Open items / risks
- **Embedding drift on model change**: `NVIDIA_EMBED_MODEL` + dims are pinned; changing the
  model needs a re-embed (note in the runbook). halfvec(2048) is sized to nemotron-3-embed-1b.
- **NVIDIA free tier**: 1000 starter credits + rate limits; fine for build/verify. If it
  throttles at scale, the embedder is injectable — swap providers without touching store/recall.
- **Recall quality tuning** (semantic/lexical weights, k) is a config, iterated after live data.
