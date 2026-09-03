"""Probe every model in `routing.TIERS` with a real completion. Evidence, not assumption.

The roster this checks was once annotated "verified live" while a third of it could not be called:
the check had confirmed the slugs EXIST on OpenRouter, not that this account can reach them. A model
listed in the catalogue, and even one whose `/endpoints` names an allowed provider, can still 404 on
every actual call — only a completion settles it.

Probes each model THREE times and reports the success rate rather than a verdict, because "does it
work" turned out to be the wrong question. `z-ai/glm-5.2` on Cloudflare fails roughly one call in
six — measured, 6 consecutive probes: 5 ok, 1 "Provider returned error". Two probes would call that
dead about 3% of the time and retire a working model; one probe would call it dead 17% of the time.
A flake rate is the honest output, and it is also the more useful one: a flaky primary is fine when
the tier behind it is real, and alarming when it is the only live model.

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


_ATTEMPTS = 3


async def probe(client: httpx.AsyncClient, model: str) -> tuple[str, str, str]:
    ok, last = 0, ""
    for _ in range(_ATTEMPTS):
        try:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
                json={"model": model, "messages": _PROMPT, "max_tokens": _MAX_TOKENS})
            body = r.json()
            if body.get("error"):
                last = (body["error"].get("message") or "")[:70]
                continue
            choice = (body.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            if (msg.get("content") or "").strip():
                ok += 1
            else:
                last = (f"empty: finish={choice.get('finish_reason')} "
                        f"reasoning={len(msg.get('reasoning') or '')}")
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:70]
    if ok == _ATTEMPTS:
        return model, "LIVE", f"{ok}/{_ATTEMPTS}"
    if ok:
        return model, "FLAKY", f"{ok}/{_ATTEMPTS} — {last}"
    return model, "DEAD", last or "no successful call"


async def main() -> int:
    bad = 0
    async with httpx.AsyncClient(timeout=180) as client:
        for tier, models in TIERS.items():
            print(f"{tier}:")
            for model, status, detail in await asyncio.gather(
                    *[probe(client, m) for m in models]):
                print(f"   {status:<6} {model:<34} {detail}")
                bad += status == "DEAD"
    if bad:
        print(f"\n{bad} model(s) never answered — a tier whose fallbacks are dead has none.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
