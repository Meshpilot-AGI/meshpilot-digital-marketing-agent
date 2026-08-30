"""Per-brand document store (FILES lane) — the `brand_document` brand→file_id map.

Anthropic Files API `file_id`s are workspace-scoped, so tenant isolation is enforced HERE: every
query is scoped `WHERE brand_id = :brand`. The `read_brand_doc` tool + the admin endpoints only
ever obtain a file_id from this store for the active brand — never from tool/user input.

`engine` is injectable so this unit-tests with a fake engine (no DB), mirroring the memory store.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from glitch_signal.db.session import _engine

_INSERT = text("""
INSERT INTO brand_document (brand_id, file_id, filename, mime_type, size_bytes, kind)
VALUES (:brand, :file_id, :filename, :mime, :size, :kind)
RETURNING id, created_at
""")

_LIST = text("""
SELECT id, file_id, filename, mime_type, size_bytes, kind, created_at
FROM brand_document WHERE brand_id = :brand ORDER BY created_at DESC
""")

# Scoped by brand_id too: a doc_id from one brand can never delete another brand's row.
_DELETE = text("""
DELETE FROM brand_document WHERE brand_id = :brand AND id = :id RETURNING file_id
""")


async def add(brand_id: str, file_id: str, filename: str, *, mime_type: str | None = None,
              size_bytes: int | None = None, kind: str = "doc", engine: Any = None) -> dict:
    eng = engine or _engine()
    async with eng.begin() as conn:
        row = (await conn.execute(_INSERT, {
            "brand": brand_id, "file_id": file_id, "filename": filename,
            "mime": mime_type, "size": size_bytes, "kind": kind})).first()
    return {"id": str(row[0]), "brand_id": brand_id, "file_id": file_id, "filename": filename,
            "mime_type": mime_type, "size_bytes": size_bytes, "kind": kind, "created_at": row[1]}


async def list_for_brand(brand_id: str, *, engine: Any = None) -> list[dict]:
    eng = engine or _engine()
    async with eng.begin() as conn:
        rows = (await conn.execute(_LIST, {"brand": brand_id})).mappings().all()
    return [{**dict(r), "id": str(r["id"])} for r in rows]


async def delete(brand_id: str, doc_id: str, *, engine: Any = None) -> str | None:
    """Delete one doc (brand-scoped). Returns its file_id (for Anthropic deletion) or None."""
    eng = engine or _engine()
    async with eng.begin() as conn:
        row = (await conn.execute(_DELETE, {"brand": brand_id, "id": doc_id})).first()
    return row[0] if row else None
