# Design Spec — Agent Brain (memory + agent capabilities)

**Date:** 2026-08-29 · **Status:** Core 4 increments DONE (AGENT-MEM + LOOP + POLICY + LEARN) + AGENT-MCP increment 1 (MCP client) DONE · **Method:** brainstorming → spec → build

## AGENT-MCP — the loop as an MCP client (increment 1 done)

The brain loop can connect to external tools' **MCP servers**, discover their tools at runtime,
and call them — every call through the policy gate, every result untrusted. `agent/mcp/client.py`
(`MCPManager`, streamable-HTTP via the `mcp` SDK, network isolated behind an injectable
connector). Per-brand config `brand_env("MCP_SERVERS")` = JSON `[{name,url,headers}]`. Discovered
tools are namespaced `mcp__<server>__<tool>` and merged into the loop's tool set (`runner.run`
auto-connects on the production path). Policy: side-effect-looking MCP tool names
(`publish|send|delete|pay|…`) are denied unless per-brand allowlisted or publishing is on; read/gen
tools pass. Introspect via `GET /internal/agent/mcp/tools?brand=`. Wiring a real server (e.g.
HeyGen's MCP with `X-Api-Key`) is config, not code.

## LLM routing (who uses which model)

- **Agent BRAIN (runtime): Claude.** The ReAct loop and the curator use `agent/loop/llm.py`
  (Anthropic Messages API, synchronous) — they need a fast multi-step reasoner. `complete()`
  for the loop/curator; `complete_messages()` (OpenAI-style + multimodal converter) for vision.
- **Content pipeline: MUapi.** All text/caption generation (nodes, media, sheet_posting,
  influencer) goes through `agent/llm.py` → `chat()` → MUapi text-to-text (one `MUAPI_API_KEY`,
  same gateway as image/video). The old multi-provider LiteLLM router is retired.
- **One exception — vision QC on Claude:** `nodes/quality_check.py` analyzes base64 video frames,
  which MUapi text-to-text can't do, so it calls `brain_llm.complete_messages()` (Claude vision).
- `nodes/caption_writer._generate_via_vision` uses `google-genai` directly (video modality).

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
2. **AGENT-LOOP** ✅ DONE — ReAct loop (`src/glitch_signal/agent/loop/`): seed-recall →
   plan → call capability-tools → verify → write episode. **LLM = Claude Messages API**
   (`llm.py`, default `claude-haiku-4-5-20251001`, env `ANTHROPIC_API_KEY` — must be an
   inference key, not `sk-ant-admin`). muapi's text endpoint (submit→poll) was too slow for
   a loop and caused CF 524s; NVIDIA chat was tried, Claude chosen (synchronous, reliable).
   The `POST /internal/agent/run` endpoint is **backgrounded** (returns `{run_id, status}`,
   runs under `asyncio.create_task`; poll `GET /internal/agent/run/{run_id}`) so a multi-step
   loop isn't bound by the edge ~100s request timeout. Embeddings stay on NVIDIA.
   *Future opt (not now):* if the loop goes high-volume or system+tools grow ≥1024 tokens,
   add prompt caching on the stable system/tools block, then verify with cache-diagnostics.
3. **AGENT-POLICY** ✅ DONE (`policy.py`): deterministic `Policy.check()` gate run before every
   tool exec (OpenClaw trusted-gateway pattern). Rules: (1) per-brand tool deny, (2) publish
   kill-switch — all PUBLISH_TOOLS denied unless `agent_publish_enabled` (config, default False),
   (3) per-run media budget `agent_max_media_per_run` (default 3) for cost control; runner tracks
   executed-tool counts and feeds them in. `allow()` kept as a back-compat wrapper.
4. **AGENT-LEARN** ✅ DONE (`agent/learn/curator.py`): Hermes-style curator distills uncurated
   episodes → a few DURABLE lessons via Claude, stored as `kind='fact'` upserted by a stable
   `lesson:<slug>` key (dedup on re-run), then marks those episodes `curated` in metadata
   (idempotent; recall favors the distilled facts). Endpoint `POST /internal/agent/curate`
   {brand?, limit?}. Closes the learning loop — lessons surface via seed-recall next run. Verified
   live: 12 episodes → 3 lessons (incl. a self-observed "avoid duplicate remember" heuristic).
   `llm.py` now retries transient 5xx/429 (surfaced by a real 503 during curator bring-up).

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

**Operator-verified provenance (security contract).** The conscience critic treats a `kind=fact` as
authoritative *ground truth* only when it carries operator-verified provenance — set **exclusively** by
the trusted operator workflow (the jobs-auth `POST /internal/agent/remember`), never inferrable from
arbitrary `source` text. A fact is verified iff **`metadata.verified` is `true`** (preferred, typed) **or
its `source` is an exact reserved token** in `store.VERIFIED_SOURCES` = `{operator_verified,
operator-verified}` (case-insensitive). The agent's own writes use `source=agent_loop` / `curator`, so
self-authored or prompt-injected "facts" can never pass as verified. Matching is **exact, not substring**
— `unverified`, `self-verified`, or free text like `"producthunt (verified)"` are NOT trusted. The
provenance filter is applied **in the recall query** (`recall(..., verified_only=True)`) so `LIMIT`
bounds the already-filtered set (a verified fact ranked past the row cap isn't lost), with a
defense-in-depth `is_verified_provenance()` re-check in `conscience.brand_facts()`.
⚠️ Migration note: this **supersedes** the earlier PR-179 convention (`source` *containing* "verified").
Operators marking a fact verified must now use `metadata={"verified": true}` or `source=operator_verified`.

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
  `async recall(brand_id, query, *, k=8, kinds=None, verified_only=False) -> list[Memory]` (hybrid;
  `verified_only` filters to operator-verified provenance in the query so `LIMIT` bounds the filtered
  set); `is_verified_provenance(source, metadata)`; `update`, `forget`. asyncpg via the app's DSN.
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
