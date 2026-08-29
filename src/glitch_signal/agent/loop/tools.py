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


async def _t_schedule(args: dict, brand_id: str) -> str:
    from glitch_signal.agent.cron.tool import schedule_tool
    return await schedule_tool(args, brand_id)


async def _t_list_playbooks(args: dict, brand_id: str) -> str:
    from glitch_signal.agent.playbooks import list_playbooks
    return json.dumps([{"slug": p.slug, "description": p.description} for p in list_playbooks()]) or "[]"


async def _t_read_playbook(args: dict, brand_id: str) -> str:
    from glitch_signal.agent.playbooks import get_playbook
    pb = get_playbook(str(args.get("slug", "")))
    if pb is None:
        from glitch_signal.agent.playbooks import list_playbooks
        return f"ERROR: no playbook {args.get('slug')!r}. Available: {', '.join(p.slug for p in list_playbooks())}"
    return pb.body


async def _t_list_recipes(args: dict, brand_id: str) -> str:
    from glitch_signal.media.generation import list_recipes
    return json.dumps([{"slug": r.slug, "kind": r.kind, "description": r.description[:80]}
                       for r in list_recipes()])


async def _t_generate_media(args: dict, brand_id: str) -> str:
    from glitch_signal.analytics.cost import budget as cost_budget
    from glitch_signal.media.generation import generate
    from glitch_signal.media.generation.compose import llm_compose
    from glitch_signal.media.generation.spec import Brief
    from glitch_signal.media.generation.storage import persist

    allowed, reason = await cost_budget.check(brand_id)  # INC-3: don't spend past the daily cap
    if not allowed:
        return f"DENIED: {reason}"
    brief = Brief(brand_id=brand_id, recipe=str(args.get("recipe", "")), inputs=args.get("inputs", {}) or {})
    asset = await generate(brief, compose=llm_compose)
    asset = await persist(asset, brand_id)
    return f"generated {asset.kind} via {asset.recipe}: {asset.url}"


async def _t_edit_image(args: dict, brand_id: str) -> str:
    """Deterministic native edit (resize/crop/text/format) of an existing image → stored URL."""
    import httpx

    from glitch_signal.media.generation.storage import upload_bytes
    from glitch_signal.media.imaging import apply_ops
    from glitch_signal.media.net import assert_safe_media_url

    url = str(args.get("image_url", "")).strip()
    ops = args.get("ops", []) or []
    if not url:
        return "ERROR: edit_image requires image_url"
    try:
        assert_safe_media_url(url)  # SSRF guard: https + public IP only (#92)
    except ValueError as exc:
        return f"ERROR: unsafe image_url: {exc}"
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as c:
        r = await c.get(url)
        if r.status_code >= 400:
            return f"ERROR: could not fetch image ({r.status_code})"
        data = r.content
    out = apply_ops(data, ops)
    fmt = next((str(o.get("format", "")).lower() for o in ops if o.get("op") == "format"), "png")
    ext = {"jpeg": "jpg", "jpg": "jpg", "webp": "webp"}.get(fmt, "png")
    ctype = {"jpg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/png")
    new_url = await upload_bytes(out, brand_id, ext=ext, content_type=ctype, prefix="edited")
    return f"edited image ({len(ops)} op(s)): {new_url}"


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
    "edit_image": {"fn": _t_edit_image,
                   "description": "Deterministically edit an existing image (exact resize/crop-to-aspect/"
                                  "text overlay/format) and return a stored URL. args: {image_url, ops:[{op:resize|fit|text|format, ...}]}"},
    "publish": {"fn": _t_publish,
                "description": "Publish content to a platform. args: {platform, ...}. NOTE: currently DISABLED."},
    "list_playbooks": {"fn": _t_list_playbooks,
                       "description": "List your domain-knowledge handbooks (name + what each teaches). "
                                      "Consult the relevant one BEFORE specialized work — ads audits, "
                                      "per-platform captions/copy, SEO, YouTube, ORM, tracking. args: {}"},
    "read_playbook": {"fn": _t_read_playbook,
                      "description": "Read a handbook's full guidance by slug (from list_playbooks). args: {slug}"},
    "schedule": {"fn": _t_schedule,
                 "description": "Schedule your OWN future work (self-cron). args: {action: create|list|cancel|next_check, ...}. "
                                "create: {name, schedule_kind: at|every|cron, schedule:{at|every_ms|cron_expr,tz?}, "
                                "payload_kind: agentTurn|capability, payload:{goal,max_steps}|{name,args}, pacing?:{min_ms,max_ms}}. "
                                "next_check {in:'30m'} re-paces the current scheduled run."},
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
