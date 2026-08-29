"""Text embeddings for agent memory — NVIDIA NIM (OpenAI-compatible).

`nvidia/nemotron-3-embed-1b` → 2048-dim vectors. Asymmetric retrieval: store facts/
episodes with `input_type="passage"`, embed the recall query with `input_type="query"`.
A direct httpx call — the same pattern as muapi/Meta/Buffer. The embedder is injectable
(pass `client`) so store/recall unit-test with no network, and the provider can be
swapped without touching the store.

Keys/config (global infra — embeddings are a shared capability, not brand identity):
    NVIDIA_API_KEY        the nvapi-... key (required)
    NVIDIA_EMBED_MODEL    override the model (default nvidia/nemotron-3-embed-1b)
    NVIDIA_EMBED_BASE     override the base URL
"""
from __future__ import annotations

import os

import httpx
import structlog

log = structlog.get_logger(__name__)

_DEFAULT_BASE = "https://integrate.api.nvidia.com/v1"
_DEFAULT_MODEL = "nvidia/nemotron-3-embed-1b"
EMBED_DIM = 2048  # nemotron-3-embed-1b; keep in sync with the halfvec(N) column


class EmbeddingError(RuntimeError):
    """Non-retryable embedding failure (missing key, bad request)."""


def _key() -> str:
    key = (os.environ.get("NVIDIA_API_KEY") or "").strip()
    if not key:
        raise EmbeddingError("NVIDIA_API_KEY not set — required for agent memory embeddings")
    return key


def _model() -> str:
    return os.environ.get("NVIDIA_EMBED_MODEL", _DEFAULT_MODEL)


def _base() -> str:
    return (os.environ.get("NVIDIA_EMBED_BASE") or _DEFAULT_BASE).rstrip("/")


async def embed(
    texts: list[str],
    *,
    input_type: str = "passage",  # "passage" to store, "query" to recall
    client: httpx.AsyncClient | None = None,
) -> list[list[float]]:
    """Embed a batch of texts. Returns one vector per input, in order."""
    if not texts:
        return []
    payload = {
        "input": texts,
        "model": _model(),
        "input_type": input_type,
        "encoding_format": "float",
    }
    headers = {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"}
    owns = client is None
    client = client or httpx.AsyncClient(timeout=60)
    try:
        resp = await client.post(f"{_base()}/embeddings", headers=headers, json=payload)
    finally:
        if owns:
            await client.aclose()
    if resp.status_code >= 400:
        raise EmbeddingError(f"nvidia embed -> {resp.status_code}: {resp.text[:300]}")
    data = resp.json().get("data") or []
    # Order by index so the vectors line up with `texts`.
    data = sorted(data, key=lambda d: d.get("index", 0))
    vectors = [d["embedding"] for d in data]
    if len(vectors) != len(texts):
        raise EmbeddingError(f"nvidia embed: got {len(vectors)} vectors for {len(texts)} texts")
    return vectors


async def embed_one(text: str, *, input_type: str = "passage", client: httpx.AsyncClient | None = None) -> list[float]:
    return (await embed([text], input_type=input_type, client=client))[0]


def to_halfvec_literal(vec: list[float]) -> str:
    """Postgres halfvec/vector literal: [0.1,0.2,...] (cast with ::halfvec in SQL)."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"
