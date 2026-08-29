"""The engine contract every media vendor implements.

An engine takes a resolved `(model, prompt, images, params)` and returns a
finished, hosted asset URL — submitting and polling internally. Keeping this
tiny is what makes MUapi / fal / HeyGen interchangeable to the runner.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class EngineError(RuntimeError):
    """Non-retryable engine failure (bad request, failed job, missing key)."""


@runtime_checkable
class Engine(Protocol):
    """Minimal generation interface.

    `model` is the vendor's endpoint/model id (recipes carry real slugs).
    `images` are reference-image URLs (image-edit / image-to-video). `params`
    are vendor knobs the recipe declares (aspect_ratio, duration, …), passed
    through untouched. Implementations submit + poll to completion and return
    the first output URL, or raise `EngineError`.
    """

    name: str

    async def generate(
        self,
        model: str,
        prompt: str,
        *,
        images: list[str] | None = None,
        params: dict[str, Any] | None = None,
        timeout_s: int = 360,
    ) -> str: ...
