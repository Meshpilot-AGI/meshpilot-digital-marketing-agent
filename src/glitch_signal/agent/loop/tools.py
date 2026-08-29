"""Tool registry — the capabilities the agent can call (memory, media, …).

Each tool is `async fn(args: dict, brand_id: str) -> str` returning a concise text
observation the LLM reads back. Publishing tools exist but are denied by `policy.allow`
(AGENT-POLICY fills that in later).
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from glitch_signal.agent.memory import recall as mem_recall
from glitch_signal.agent.memory import remember as mem_remember

ToolFn = Callable[[dict, str], Awaitable[str]]


async def _t_recall(args: dict, brand_id: str) -> str:
    mems = await mem_recall(brand_id, str(args.get("query", "")), k=int(args.get("k", 5)))
    return json.dumps([{"kind": m.kind, "content": m.content} for m in mems]) or "[]"


async def _t_remember(args: dict, brand_id: str) -> str:
    m = await mem_remember(
        brand_id, str(args.get("kind", "fact")), str(args.get("content", "")),
        key=args.get("key"), importance=float(args.get("importance", 0.5)), source="agent_loop",
    )
    return f"remembered {m.kind} id={m.id}"


async def _t_list_recipes(args: dict, brand_id: str) -> str:
    from glitch_signal.media.generation import list_recipes
    return json.dumps([{"slug": r.slug, "kind": r.kind, "description": r.description[:80]}
                       for r in list_recipes()])


async def _t_generate_media(args: dict, brand_id: str) -> str:
    from glitch_signal.media.generation import generate
    from glitch_signal.media.generation.compose import llm_compose
    from glitch_signal.media.generation.spec import Brief
    from glitch_signal.media.generation.storage import persist

    brief = Brief(brand_id=brand_id, recipe=str(args.get("recipe", "")), inputs=args.get("inputs", {}) or {})
    asset = await generate(brief, compose=llm_compose)
    asset = await persist(asset, brand_id)
    return f"generated {asset.kind} via {asset.recipe}: {asset.url}"


async def _t_publish(args: dict, brand_id: str) -> str:  # never reached — policy denies
    return "publish executed"


TOOLS: dict[str, dict[str, Any]] = {
    "recall": {"fn": _t_recall,
               "description": "Search the brand's memory. args: {query, k?}"},
    "remember": {"fn": _t_remember,
                 "description": "Store a durable fact or an episode of what you did. args: {kind: fact|episode, content, key?}"},
    "list_recipes": {"fn": _t_list_recipes,
                     "description": "List available media-generation recipes. args: {}"},
    "generate_media": {"fn": _t_generate_media,
                       "description": "Generate an image/video from a recipe (returns a stored URL). args: {recipe, inputs}"},
    "publish": {"fn": _t_publish,
                "description": "Publish content to a platform. args: {platform, ...}. NOTE: currently DISABLED."},
}


def tool_descriptions() -> str:
    return "\n".join(f"- {name}: {t['description']}" for name, t in TOOLS.items())


async def execute(tool_name: str, args: dict, brand_id: str) -> str:
    t = TOOLS.get(tool_name)
    if not t:
        return f"ERROR: unknown tool {tool_name!r}. Available: {', '.join(TOOLS)}"
    try:
        return await t["fn"](args, brand_id)
    except Exception as exc:  # noqa: BLE001 — surface tool errors to the loop, don't crash it
        return f"ERROR: {tool_name} failed: {str(exc)[:200]}"
