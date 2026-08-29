"""Higgsfield engine — third media provider (image / video / 3D / audio) via its SDK.

Behind the same `Engine` protocol as MUapi/HeyGen. `model` is the Higgsfield application slug
(e.g. an image/video model id), `prompt` → `arguments.prompt`, `params` merged into arguments,
`images` passed as a reference. The SDK's `subscribe` submits and polls to completion, returning
a result whose asset URL we extract.

    HIGGSFIELD_API_KEY / HIGGSFIELD_API_SECRET — global infra (one Higgsfield account). The SDK
    credential is the pair joined as "key:secret". `client_factory` is injectable for tests.
"""
from __future__ import annotations

import os
from typing import Any

import structlog

from glitch_signal.media.generation.engines.base import EngineError

log = structlog.get_logger(__name__)


def _extract_url(result: Any) -> str:
    """Pull the first asset URL from a Higgsfield result (images/videos/audio/model)."""
    if isinstance(result, str):
        return result
    if not isinstance(result, dict):
        return str(result)
    for key in ("images", "videos", "audios", "models", "results"):
        items = result.get(key)
        if isinstance(items, list) and items:
            first = items[0]
            url = first.get("url") if isinstance(first, dict) else first
            if url:
                return url
    for key in ("video", "image", "audio", "url"):
        v = result.get(key)
        if isinstance(v, dict) and v.get("url"):
            return v["url"]
        if isinstance(v, str) and v:
            return v
    raise EngineError(f"higgsfield: no asset URL in result: {str(result)[:200]}")


class HiggsfieldEngine:
    """Engine protocol implementation for Higgsfield."""

    name = "higgsfield"

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None,
                 client_factory: Any = None) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._client_factory = client_factory  # () -> client (injectable for tests)

    def _credential(self) -> str:
        key = (self._api_key or os.environ.get("HIGGSFIELD_API_KEY") or "").strip()
        secret = (self._api_secret or os.environ.get("HIGGSFIELD_API_SECRET") or "").strip()
        if not key or not secret:
            raise EngineError("HIGGSFIELD_API_KEY / HIGGSFIELD_API_SECRET not set")
        return f"{key}:{secret}"

    def _client(self):
        if self._client_factory is not None:
            return self._client_factory()
        from higgsfield_client import AsyncClient
        return AsyncClient(api_key=self._credential())

    async def generate(self, model: str, prompt: str, *, images: list[str] | None = None,
                       params: dict[str, Any] | None = None, timeout_s: int = 360) -> str:
        arguments: dict[str, Any] = {"prompt": prompt, **(params or {})}
        if images:
            arguments.setdefault("image_url", images[0])
        client = self._client()
        try:
            result = await client.subscribe(model, arguments)
        except Exception as exc:  # noqa: BLE001
            raise EngineError(f"higgsfield {model} failed: {str(exc)[:200]}")
        url = _extract_url(result)
        log.info("higgsfield.generated", model=model)
        return url
