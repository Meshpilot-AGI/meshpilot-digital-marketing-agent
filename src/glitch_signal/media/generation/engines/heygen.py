"""HeyGen engine — avatar / talking-head video generation (HeyGen API v3).

Second media provider behind the same `Engine` protocol as MUapi. Async submit→poll:
    submit : POST {base}/v3/videos      X-Api-Key -> {data:{video_id}}
    poll   : GET  {base}/v3/videos/{id}           -> {data:{status, video_url}}

The `Engine` mapping: `model` is the HeyGen `avatar_id`, `prompt` is the spoken script
(`input_text`), and `params` carry HeyGen knobs (`voice_id`/`voice`, `aspect_ratio`,
`resolution`, `title`, `callback_id`, …) — merged into the request body untouched, so recipes
control the full payload. `images` is unused for standard avatar video.

`HEYGEN_API_KEY` / `HEYGEN_API_BASE` are global infra (one HeyGen account), read from the
environment, overridable via the constructor for tests.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
import structlog

from glitch_signal.media.generation.engines.base import EngineError

log = structlog.get_logger(__name__)

_DEFAULT_BASE = "https://api.heygen.com"
_DONE = {"completed", "success", "succeeded", "done"}
_FAILED = {"failed", "error", "cancelled", "canceled"}


class HeyGenEngine:
    """Engine protocol implementation for HeyGen video generation."""

    name = "heygen"

    def __init__(self, *, api_key: str | None = None, api_base: str | None = None,
                 poll_interval_s: float = 5.0) -> None:
        self._api_key = api_key  # None → read env lazily (import never fails)
        self._api_base = (api_base or os.environ.get("HEYGEN_API_BASE") or _DEFAULT_BASE).rstrip("/")
        self._poll_interval_s = poll_interval_s

    def _key(self) -> str:
        key = (self._api_key or os.environ.get("HEYGEN_API_KEY") or "").strip()
        if not key:
            raise EngineError("HEYGEN_API_KEY not set")
        return key

    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self._key(), "Content-Type": "application/json"}

    @staticmethod
    def _build_body(model: str, prompt: str, params: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {"input_text": prompt}
        p = dict(params or {})
        # avatar_id: prefer params (recipe params are templated; `model` is a static tag), else model
        avatar_id = p.pop("avatar_id", None) or model
        if avatar_id:
            body["avatar_id"] = avatar_id
        # convenience: voice_id → the nested voice object HeyGen expects
        if "voice_id" in p and "voice" not in p:
            p["voice"] = {"voice_id": p.pop("voice_id")}
        body.update(p)
        return body

    async def _submit(self, client: httpx.AsyncClient, body: dict[str, Any]) -> str:
        resp = await client.post(f"{self._api_base}/v3/videos", headers=self._headers(), json=body)
        if resp.status_code >= 400:
            raise EngineError(f"heygen submit -> {resp.status_code}: {resp.text[:200]}")
        data = (resp.json() or {}).get("data") or {}
        vid = data.get("video_id")
        if not vid:
            raise EngineError(f"heygen submit returned no video_id: {resp.text[:200]}")
        log.info("heygen.submit", video_id=vid)
        return vid

    async def _wait(self, client: httpx.AsyncClient, video_id: str, timeout_s: int) -> str:
        deadline = float("inf") if self._poll_interval_s <= 0 else timeout_s / self._poll_interval_s
        n = 0
        while True:
            resp = await client.get(f"{self._api_base}/v3/videos/{video_id}", headers=self._headers())
            if resp.status_code >= 400:
                raise EngineError(f"heygen poll -> {resp.status_code}: {resp.text[:200]}")
            data = (resp.json() or {}).get("data") or {}
            status = str(data.get("status", "")).lower()
            if status in _DONE:
                url = data.get("video_url")
                if not url:
                    raise EngineError(f"heygen {video_id} completed with no video_url")
                return url
            if status in _FAILED:
                raise EngineError(f"heygen {video_id} {status}: {data.get('error') or data.get('message') or ''}")
            n += 1
            if n > deadline:
                raise EngineError(f"heygen {video_id} poll timed out after {timeout_s}s (last status {status!r})")
            await asyncio.sleep(self._poll_interval_s)

    async def generate(self, model: str, prompt: str, *, images: list[str] | None = None,
                       params: dict[str, Any] | None = None, timeout_s: int = 360) -> str:
        body = self._build_body(model, prompt, params or {})
        async with httpx.AsyncClient(timeout=60) as client:
            video_id = await self._submit(client, body)
            return await self._wait(client, video_id, timeout_s)
