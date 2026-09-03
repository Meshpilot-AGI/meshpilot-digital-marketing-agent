"""Probe every model in `routing.TIERS` with a real completion. Evidence, not assumption.

The roster this checks was once annotated "verified live" while a third of it could not be called:
the check had confirmed the slugs EXIST on OpenRouter, not that this account can reach them. A model
listed in the catalogue, and even one whose `/endpoints` names an allowed provider, can still 404 on
every actual call — only a completion settles it.

Probes twice before reporting a model dead: a one-off "Provider returned error" is transient and is
not the same thing as an access denial.

    uv run python scripts/probe_router_models.py
"""
from __future__ import annotations

import asyncio
import os
import sys

import httpx

from glitch_signal.agent.loop.routing import TIERS

_PROMPT = [{"role": "user", "content": "Reply with the single word: ok"}]
# Sized for the THINKING, not the answer: a reasoning model on a small budget returns nothing at all.
_MAX_TOKENS = 1200


async def probe(client: httpx.AsyncClient, model: str) -> tuple[str, str, str]:
    for attempt in (1, 2):
        try:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
                json={"model": model, "messages": _PROMPT, "max_tokens": _MAX_TOKENS})
            body = r.json()
            if body.get("error"):
                if attempt == 1:
                    continue
                return model, "DEAD", (body["error"].get("message") or "")[:70]
            choice = (body.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            if (msg.get("content") or "").strip():
                return model, "LIVE", f"finish={choice.get('finish_reason')}"
            return model, "EMPTY", (f"finish={choice.get('finish_reason')} "
                                    f"reasoning={len(msg.get('reasoning') or '')}")
        except Exception as exc:  # noqa: BLE001
            if attempt == 2:
                return model, "ERROR", str(exc)[:70]
    return model, "ERROR", "unreachable"


async def main() -> int:
    bad = 0
    async with httpx.AsyncClient(timeout=180) as client:
        for tier, models in TIERS.items():
            print(f"{tier}:")
            for model, status, detail in await asyncio.gather(
                    *[probe(client, m) for m in models]):
                print(f"   {status:<6} {model:<34} {detail}")
                bad += status != "LIVE"
    if bad:
        print(f"\n{bad} model(s) are not usable — a tier with one live model has no fallback.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
