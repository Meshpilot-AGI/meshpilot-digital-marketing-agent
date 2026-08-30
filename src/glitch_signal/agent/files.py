"""Anthropic Files API client (FILES lane) — upload/delete brand documents.

Thin httpx client, same posture as `agent/loop/llm.py` (reads `ANTHROPIC_API_KEY`,
`anthropic-version: 2023-06-01`; Files API is GA, no beta header). Uploads/deletes are free —
only *using* a file in a Messages call bills as input tokens. Files are workspace-scoped, so the
caller (the `documents` store, keyed by brand) is what enforces tenant isolation.
"""
from __future__ import annotations

import os

import httpx

_DEFAULT_BASE = "https://api.anthropic.com"
_ANTHROPIC_VERSION = "2023-06-01"


def _key() -> str:
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set — required for the Files API")
    return key


def _base() -> str:
    return (os.environ.get("AGENT_LLM_BASE") or _DEFAULT_BASE).rstrip("/")


def _headers() -> dict:
    return {"x-api-key": _key(), "anthropic-version": _ANTHROPIC_VERSION}


async def upload_file(data: bytes, filename: str, mime: str, *, timeout_s: int = 60,
                      client: httpx.AsyncClient | None = None) -> dict:
    """Upload bytes to /v1/files → the file record {id, type, filename, mime_type, size_bytes}."""
    owns = client is None
    client = client or httpx.AsyncClient(timeout=timeout_s)
    try:
        r = await client.post(f"{_base()}/v1/files", headers=_headers(),
                              files={"file": (filename, data, mime)})
    finally:
        if owns:
            await client.aclose()
    if r.status_code >= 400:
        raise RuntimeError(f"anthropic files upload -> {r.status_code}: {r.text[:200]}")
    return r.json()


async def delete_file(file_id: str, *, timeout_s: int = 30,
                      client: httpx.AsyncClient | None = None) -> bool:
    """Delete a file by id. Returns True on success (best-effort; never raises)."""
    owns = client is None
    client = client or httpx.AsyncClient(timeout=timeout_s)
    try:
        r = await client.delete(f"{_base()}/v1/files/{file_id}", headers=_headers())
    except Exception:  # noqa: BLE001 — deletion is best-effort cleanup
        return False
    finally:
        if owns:
            await client.aclose()
    return r.status_code < 400
