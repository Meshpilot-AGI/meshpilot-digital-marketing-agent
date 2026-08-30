# FILES — brand documents via the Anthropic Files API

**Status:** design (awaiting build)  ·  **Opened:** 2026-08-30  ·  **Owner:** Claude
**Follows:** WEB-TOOLS + the standard-org move (Files API is unblocked on the standard org).
See `docs/vendors/anthropic.md`.

## Why

The agent should ground its work in a brand's **actual documents** (style guide, brief, deck),
not just prose brand facts in memory. The Files API lets us upload a brand PDF/text once and
reference it by `file_id` in Messages so Claude reads the real guide.

## Probe-confirmed shape (live, Sonnet 5, 2026-08-30, standard org, no beta header)

- **Upload:** `POST /v1/files` multipart (`file=(filename, bytes, mime)`) → `{id:"file_…", type,
  filename, mime_type, size_bytes}`.
- **Reference:** a Messages content block `{"type":"document","source":{"type":"file","file_id":"file_…"}}`
  (+ a text block with the question) — Claude read the doc and answered correctly.
- **Delete:** `DELETE /v1/files/{id}` → 200.
- Files are **workspace-scoped, NOT tenant-scoped** → we MUST enforce brand isolation ourselves.

## Decision (operator): **admin-endpoint ingestion only** (agent self-ingest is a later follow-up).

## What changes (~4 pieces + tests)

### 1. `agent/files.py` — thin Files API client
httpx, same pattern as `llm.py` (reads `ANTHROPIC_API_KEY`, `anthropic-version: 2023-06-01`,
retry on 5xx/429). `async upload_file(data: bytes, filename: str, mime: str) -> dict` (returns the
file record) and `async delete_file(file_id) -> bool`. Uploads/deletes are free; only *use* in a
Messages call bills as input tokens.

### 2. Storage — `brand_document` table
A dedicated table (we need to *list* a brand's docs and enforce isolation):
`brand_document(id, brand_id, file_id, filename, mime_type, size_bytes, kind, created_at)` with an
index on `brand_id`. Supabase SQL migration (RLS deny-all like the rest; app uses the service
path). Store helpers in `agent/documents.py`: `add(brand_id, rec, kind)`, `list_for_brand(brand_id)`,
`delete(brand_id, doc_id)` — **every query is scoped `WHERE brand_id = …`** (the isolation guard).

### 3. Ingestion — admin endpoint
`POST /internal/brand/{brand_id}/documents` (jobs-auth via `Depends(_require_jobs_auth)`, matching
the existing `/internal/*` routes). Accepts a multipart `UploadFile` (+ optional `kind` form field);
size/type guard (PDF or text/plain; ≤ a sane cap, e.g. 25MB to stay under the 32MB Messages limit);
uploads to the Files API; stores the `brand_document` row; returns `{doc_id, file_id, filename}`.
`GET /internal/brand/{brand_id}/documents` lists them; `DELETE …/{doc_id}` removes the row + the
Anthropic file.

### 4. Usage — `read_brand_doc(query)` loop tool
New entry in `tools.py::TOOLS` (input_schema `{query}`, strict). It: `list_for_brand(brand_id)` →
build document blocks from the file_ids → one bounded `complete_messages()` call with those blocks
+ the query (+ a short system line) → return the answer (or "no brand documents uploaded" if none).
Keeps the main loop lean (the PDF isn't in every turn's context). Optionally set
`citations:{enabled:true}` on the document blocks to ground claims (note: **incompatible with
structured outputs** — fine here, we return text).

## Verification
- Unit: `files.py` (mock httpx: upload/delete shapes); `documents.py` store isolation (a brand
  never sees another brand's rows); `read_brand_doc` returns the "no docs" message when empty and
  builds correct document blocks when present; endpoint auth (401 without token).
- **Live (real Sonnet 5, standard org)**: upload a brand guide via the endpoint → run the real loop
  with a goal that needs it → the agent calls `read_brand_doc` and answers from the doc → delete.

## Risks / mitigations
- **Cross-brand file leak** — the whole point of the dedicated table + `WHERE brand_id` guard;
  tested explicitly. `file_id`s are never taken from agent/tool input, only from the brand's store.
- **Cost** — `read_brand_doc` is one bounded sub-call; the doc is input tokens (~1.5–3k/page). Cap
  the doc size on upload and the tool's `max_tokens`.
- **Orphaned Anthropic files** — deleting a `brand_document` row also deletes the Anthropic file;
  document that a dropped row without file delete leaves an orphan (cleanup sweep = future).

## Out of scope (later)
Agent self-ingest tool (`ingest_brand_doc(url)`); auto-injecting the brand doc into the caption
pipeline; images via Files API; multi-file dedup; big-deck page-limit handling; orphan-file sweep.

## Write-back
`docs/vendors/anthropic.md` (Files API → adopted), `control-plane/ACTIVE_LANE_BOARD.md`,
`control-plane/ENGINEERING_SUPERVISOR.md`, and `docs/vendors/README.md` if a capability line fits.
