"""Persist generated media to per-brand Supabase Storage buckets (STORAGE-1).

muapi's `cdn.muapi.ai` URLs expire (~30 days), so every generated asset is
downloaded and re-uploaded to the **brand's own** Supabase Storage bucket, and
the runner's Asset is rewritten to point at the durable Supabase public URL
(the original muapi URL is kept in `metadata.source_url`).

Per-brand isolation: each brand gets its own bucket, `<env_prefix>-media`
(e.g. GE -> `ge-media`), overridable via the brand config's `media_bucket`.
The bucket is created idempotently on first use (runs on the app, not the Mac).

Uses the Supabase Storage REST API with the service key (`SUPABASE_SECRET_KEY`)
over httpx — no new dependency, no supabase-py.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import replace
from urllib.parse import urlsplit

import httpx
import structlog

from glitch_signal.media.generation.engines.base import EngineError
from glitch_signal.media.generation.spec import Asset

log = structlog.get_logger(__name__)

# content-type -> extension fallback when the URL has no usable suffix
_CT_EXT = {
    "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif",
    "video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov",
    "audio/mpeg": "mp3", "audio/wav": "wav",
}


def _supabase() -> tuple[str, str]:
    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_SECRET_KEY") or "").strip()
    if not url or not key:
        raise EngineError("SUPABASE_URL / SUPABASE_SECRET_KEY not set — cannot store media")
    return url, key


def bucket_for(brand_id: str) -> str:
    """The brand's media bucket name: config `media_bucket`, else `<prefix>-media`."""
    from glitch_signal.config import brand_config, brand_env_prefix

    cfg = brand_config(brand_id) or {}
    if cfg.get("media_bucket"):
        return str(cfg["media_bucket"])
    prefix = (brand_env_prefix(brand_id) or "brand").lower()
    return f"{prefix}-media"


def _ext_for(url: str, content_type: str, kind: str) -> str:
    suffix = os.path.splitext(urlsplit(url).path)[1].lstrip(".").lower()
    if suffix and len(suffix) <= 5:
        return suffix
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _CT_EXT:
        return _CT_EXT[ct]
    return "mp4" if kind == "video" else "png"


def _headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}", "apikey": key}


async def ensure_bucket(
    bucket: str, *, public: bool = True, client: httpx.AsyncClient | None = None
) -> None:
    """Create the bucket if it doesn't exist (idempotent)."""
    url, key = _supabase()
    owns = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        resp = await client.post(
            f"{url}/storage/v1/bucket",
            headers={**_headers(key), "Content-Type": "application/json"},
            json={"id": bucket, "name": bucket, "public": public},
        )
    finally:
        if owns:
            await client.aclose()
    if resp.status_code in (200, 201):
        log.info("storage.bucket_created", bucket=bucket, public=public)
        return
    # already-exists is success for our purposes
    if resp.status_code == 409 or "exist" in resp.text.lower() or "duplicate" in resp.text.lower():
        return
    raise EngineError(f"ensure_bucket {bucket} -> {resp.status_code}: {resp.text[:200]}")


async def persist(
    asset: Asset, brand_id: str, *, client: httpx.AsyncClient | None = None
) -> Asset:
    """Download the generated asset and store it in the brand's bucket.

    Returns a new Asset whose `url` is the durable Supabase public URL; the
    original engine URL is preserved in `metadata.source_url`.
    """
    url, key = _supabase()
    bucket = bucket_for(brand_id)
    owns = client is None
    client = client or httpx.AsyncClient(timeout=120)
    try:
        await ensure_bucket(bucket, client=client)
        src = await client.get(asset.url)
        if src.status_code >= 400:
            raise EngineError(f"fetch generated media {asset.url} -> {src.status_code}")
        content_type = src.headers.get("content-type", "application/octet-stream")
        ext = _ext_for(asset.url, content_type, asset.kind)
        path = f"{asset.recipe or 'media'}/{uuid.uuid4().hex}.{ext}"
        up = await client.post(
            f"{url}/storage/v1/object/{bucket}/{path}",
            headers={**_headers(key), "Content-Type": content_type, "x-upsert": "true"},
            content=src.content,
        )
        if up.status_code not in (200, 201):
            raise EngineError(f"upload to {bucket}/{path} -> {up.status_code}: {up.text[:200]}")
    finally:
        if owns:
            await client.aclose()

    public_url = f"{url}/storage/v1/object/public/{bucket}/{path}"
    meta = dict(asset.metadata)
    meta.update({"source_url": asset.url, "bucket": bucket, "path": path})
    log.info("storage.persisted", brand=brand_id, bucket=bucket, path=path)
    return replace(asset, url=public_url, metadata=meta)
