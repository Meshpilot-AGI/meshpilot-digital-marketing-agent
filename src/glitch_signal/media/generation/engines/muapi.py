"""MUapi engine — the deterministic HTTP client for muapi.ai.

Async submit/poll contract (prod-proven in the Mesh Pilot bible):
    submit : POST {base}/{model}                   x-api-key -> {request_id}
    poll   : GET  {base}/predictions/{id}/result             -> {status, outputs:[url]}

The recipes carry **real endpoint slugs** as their `model` (e.g. `flux-2-pro-edit`,
`wan2.5-image-to-video-fast`), so we POST straight to `{base}/{model}` — no
hand-curated model→endpoint map to maintain, and new recipes/models work with no
code change. A tiny `_ALIASES` map only exists for a few legacy friendly names.

`MUAPI_API_KEY` / `MUAPI_API_BASE` are global infra (one muapi account) — read
from the environment, overridable via the constructor for tests.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
import structlog

from glitch_signal.media.generation.engines.base import EngineError

log = structlog.get_logger(__name__)

_DEFAULT_BASE = "https://api.muapi.ai/api/v1"

# Optional friendly-name → endpoint slug. Recipes use real slugs, so this is a
# convenience only; unknown models pass through as the endpoint verbatim.
_ALIASES: dict[str, str] = {
    "nano-banana": "nano-banana",
    "seedream-v4": "bytedance-seedream-v4",
    "gpt-image-2": "gpt-image-2-text-to-image",
}

_DONE = {"completed", "succeeded", "success", "done"}
_FAILED = {"failed", "error", "cancelled", "canceled"}


class MuapiEngine:
    """Engine protocol implementation for muapi.ai."""

    name = "muapi"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        poll_interval_s: float = 3.0,
    ) -> None:
        self._api_key = api_key  # None → read env lazily (so import never fails)
        self._api_base = (api_base or os.environ.get("MUAPI_API_BASE") or _DEFAULT_BASE).rstrip("/")
        self._poll_interval_s = poll_interval_s

    # -- internals ---------------------------------------------------------
    def _key(self) -> str:
        key = (self._api_key or os.environ.get("MUAPI_API_KEY") or "").strip()
        if not key:
            raise EngineError("MUAPI_API_KEY not set")
        return key

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._key(), "Content-Type": "application/json"}

    @staticmethod
    def _endpoint(model: str) -> str:
        return _ALIASES.get(model, model)

    async def _submit(
        self,
        client: httpx.AsyncClient,
        model: str,
        prompt: str,
        images: list[str],
        params: dict[str, Any],
    ) -> str:
        url = f"{self._api_base}/{self._endpoint(model)}"
        payload: dict[str, Any] = {"prompt": prompt}
        if images:
            payload["images_list"] = images
            payload["image_url"] = images[0]
        if params:
            payload.update(params)
        resp = await client.post(url, headers=self._headers(), json=payload)
        if resp.status_code >= 400:
            raise EngineError(f"muapi submit {model} -> {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        rid = data.get("request_id") or data.get("id")
        if not rid:
            raise EngineError(f"muapi submit {model}: no request_id in {data!r}")
        log.info("muapi.submit", model=model, request_id=rid, n_images=len(images))
        return str(rid)

    async def _wait(self, client: httpx.AsyncClient, request_id: str, timeout_s: int) -> str:
        waited = 0.0
        while waited < timeout_s:
            await asyncio.sleep(self._poll_interval_s)
            waited += self._poll_interval_s
            resp = await client.get(
                f"{self._api_base}/predictions/{request_id}/result",
                headers=self._headers(),
            )
            j = resp.json()
            status = (j.get("status") or "").lower()
            if status in _DONE:
                outs = j.get("outputs") or []
                if not outs:
                    raise EngineError(f"muapi {request_id} completed with no output url")
                return str(outs[0])
            if status in _FAILED:
                raise EngineError(f"muapi {request_id} {status}: {j.get('error')}")
        raise EngineError(f"muapi {request_id} poll timed out after {timeout_s}s")

    # -- Engine protocol ---------------------------------------------------
    async def generate(
        self,
        model: str,
        prompt: str,
        *,
        images: list[str] | None = None,
        params: dict[str, Any] | None = None,
        timeout_s: int = 360,
    ) -> str:
        """Submit + poll to completion; return the finished asset URL."""
        async with httpx.AsyncClient(timeout=60) as client:
            rid = await self._submit(client, model, prompt, images or [], params or {})
            return await self._wait(client, rid, timeout_s)
