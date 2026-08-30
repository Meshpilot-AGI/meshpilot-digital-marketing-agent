"""Tool registry — the capabilities the agent can call (memory, media, …).

Each tool is `async fn(args: dict, brand_id: str) -> str` returning a concise text
observation the LLM reads back. Publishing tools exist but are denied by `policy.allow`
(AGENT-POLICY fills that in later).
"""
from __future__ import annotations

import json
import os
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


async def _t_polish_copy(args: dict, brand_id: str) -> str:
    """Run drafted content through the content policy: strip AI footprints + report any that remain."""
    from glitch_signal import content_policy
    clean, violations = content_policy.enforce(str(args.get("text", "")))
    return json.dumps({"clean": clean, "violations": violations})


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


async def _t_send_email(args: dict, brand_id: str) -> str:
    """Send an email for the brand via Resend. Gated: the policy denies this unless
    agent_email_enabled is on, so it only runs when email sending is deliberately enabled."""
    from glitch_signal.comms import email

    to = args.get("to")
    if not to:
        return "ERROR: send_email requires 'to'"
    rid = await email.send_email(
        brand_id=brand_id,
        to=to,
        subject=str(args.get("subject", "")),
        html=args.get("html"),
        text=args.get("text"),
        from_addr=args.get("from"),
    )
    return f"email sent (message_id={rid})"


async def _t_read_brand_doc(args: dict, brand_id: str) -> str:
    """Answer a question grounded ONLY in THIS brand's uploaded documents (Files API).

    Isolation: file_ids come from the brand's own `brand_document` store (scoped by brand_id) —
    never from the tool input — so the agent can only ever read its own brand's files.
    """
    from glitch_signal.agent import documents
    from glitch_signal.agent.loop.llm import complete_messages

    docs = await documents.list_for_brand(brand_id)
    if not docs:
        return "No brand documents have been uploaded for this brand yet."
    query = str(args.get("query", "")).strip() or "Summarize this brand's documents."
    content: list[dict] = [{"type": "document", "source": {"type": "file", "file_id": d["file_id"]}}
                           for d in docs]
    content.append({"type": "text", "text": query})
    msgs = [
        {"role": "system", "content": "Answer using ONLY the attached brand document(s). "
                                      "If the answer is not in them, say so plainly."},
        {"role": "user", "content": content},
    ]
    return await complete_messages(msgs, max_tokens=800)


def _obj(properties: dict, required: list[str], *, closed: bool = True) -> dict:
    """A JSON-Schema object. `closed` sets additionalProperties:false (needed for strict)."""
    s: dict[str, Any] = {"type": "object", "properties": properties, "required": required}
    if closed:
        s["additionalProperties"] = False
    return s


# Each tool: fn + description + input_schema (JSON Schema). `strict: True` is set only on tools
# whose schema is fully closed (no free-form nested objects) — the model's input is then
# guaranteed schema-valid, eliminating the missing/extra-arg retry loop. Tools with free-form
# nested payloads (generate_media inputs, edit_image ops, schedule) omit strict but still validate.
TOOLS: dict[str, dict[str, Any]] = {
    "recall": {"fn": _t_recall, "strict": True,
               "description": "Search the brand's memory for what you already know.",
               "input_schema": _obj({"query": {"type": "string"},
                                     "k": {"type": "integer", "default": 5}}, ["query"])},
    "remember": {"fn": _t_remember, "strict": True,
                 "description": "Store a durable fact, or an episode of what you did.",
                 "input_schema": _obj({"kind": {"type": "string", "enum": ["fact", "episode"]},
                                       "content": {"type": "string"},
                                       "key": {"type": "string"},
                                       "importance": {"type": "number"}}, ["kind", "content"])},
    "list_recipes": {"fn": _t_list_recipes, "strict": True,
                     "description": "List available media-generation recipes.",
                     "input_schema": _obj({}, [])},
    "generate_media": {"fn": _t_generate_media,
                       "description": "Generate an image/video from a recipe (returns a stored URL).",
                       "input_schema": _obj({"recipe": {"type": "string"},
                                             "inputs": {"type": "object"}}, ["recipe"], closed=False)},
    "edit_image": {"fn": _t_edit_image,
                   "description": "Deterministically edit an existing image (exact resize / crop-to-aspect "
                                  "/ text overlay / format) and return a stored URL.",
                   "input_schema": _obj({"image_url": {"type": "string"},
                                         "ops": {"type": "array", "items": {"type": "object"}}},
                                        ["image_url"], closed=False)},
    "publish": {"fn": _t_publish, "strict": True,
                "description": "Publish content to a platform. NOTE: currently DISABLED (denied by policy).",
                "input_schema": _obj({"platform": {"type": "string"},
                                      "text": {"type": "string"}}, ["platform"])},
    "send_email": {"fn": _t_send_email, "strict": True,
                   "description": "Send an email for this brand via Resend (html or text body; run through "
                                  "the content policy). NOTE: gated — denied unless email sending is enabled.",
                   "input_schema": _obj({"to": {"type": "string"}, "subject": {"type": "string"},
                                         "html": {"type": "string"}, "text": {"type": "string"},
                                         "from": {"type": "string"}}, ["to"])},
    "polish_copy": {"fn": _t_polish_copy, "strict": True,
                    "description": "MANDATORY before finalizing ANY content (caption, post, blog, etc.): run "
                                   "your draft through the content policy. Returns {clean, violations} — use "
                                   "`clean`, and if `violations` is non-empty rewrite to fix them.",
                    "input_schema": _obj({"text": {"type": "string"}}, ["text"])},
    "list_playbooks": {"fn": _t_list_playbooks, "strict": True,
                       "description": "List your domain-knowledge handbooks (name + what each teaches). "
                                      "Consult the relevant one BEFORE specialized work.",
                       "input_schema": _obj({}, [])},
    "read_playbook": {"fn": _t_read_playbook, "strict": True,
                      "description": "Read a handbook's full guidance by slug (from list_playbooks).",
                      "input_schema": _obj({"slug": {"type": "string"}}, ["slug"])},
    "read_brand_doc": {"fn": _t_read_brand_doc, "strict": True,
                       "description": "Consult THIS brand's uploaded documents (style guide / brief / "
                                      "deck) to answer a question or ground content in the real brand "
                                      "guidelines. Returns an answer drawn only from those documents.",
                       "input_schema": _obj({"query": {"type": "string"}}, ["query"])},
    "schedule": {"fn": _t_schedule,
                 "description": "Schedule your OWN future work (self-cron). action=create|list|cancel|next_check. "
                                "create: {name, schedule_kind:at|every|cron, schedule:{at|every_ms|cron_expr,tz?}, "
                                "payload_kind:agentTurn|capability, payload:{goal,max_steps}|{name,args}, "
                                "pacing?:{min_ms,max_ms}}. next_check {in:'30m'} re-paces the current run.",
                 "input_schema": _obj({"action": {"type": "string",
                                                   "enum": ["create", "list", "cancel", "next_check"]}},
                                      ["action"], closed=False)},
}


def tool_defs() -> list[dict[str, Any]]:
    """The built-in tools as Anthropic native tool definitions (name/description/input_schema[/strict])."""
    defs = []
    for name, t in TOOLS.items():
        d: dict[str, Any] = {"name": name, "description": t["description"],
                             "input_schema": t["input_schema"]}
        if t.get("strict"):
            d["strict"] = True
        defs.append(d)
    return defs


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


def server_tool_defs() -> list[dict[str, Any]]:
    """Anthropic **server-side** tools (web_search / web_fetch) — Anthropic executes them and
    returns the result inline, so they are NOT in the TOOLS registry (no fn) and never go through
    `execute()`/`policy.allow`. Config-gated; web_search is capped + metered ($0.01/search).

    The agent runs on a **standard (non-HIPAA) Anthropic org**, so both web_search and web_fetch
    (and code_execution / Files API for future lanes) are available. web_search defaults to the
    **basic `web_search_20250305`** tag on purpose — the *dynamic-filtering* tag
    (`web_search_20260318`) auto-provisions code_execution and does extra search rounds (more cost),
    so it's opt-in via `AGENT_WEB_SEARCH_TAG`. Override the fetch tag via `AGENT_WEB_FETCH_TAG`.
    """
    blocked = [d.strip() for d in (os.environ.get("AGENT_WEB_BLOCKED_DOMAINS") or "").split(",")
               if d.strip()]
    defs: list[dict[str, Any]] = []
    if _env_bool("AGENT_WEB_SEARCH_ENABLED", True):
        d: dict[str, Any] = {
            "type": os.environ.get("AGENT_WEB_SEARCH_TAG") or "web_search_20250305",
            "name": "web_search", "max_uses": _env_int("AGENT_WEB_SEARCH_MAX_USES", 3)}
        if blocked:
            d["blocked_domains"] = blocked
        defs.append(d)
    if _env_bool("AGENT_WEB_FETCH_ENABLED", True):
        d = {"type": os.environ.get("AGENT_WEB_FETCH_TAG") or "web_fetch_20260318",
             "name": "web_fetch", "max_uses": _env_int("AGENT_WEB_FETCH_MAX_USES", 5)}
        if blocked:
            d["blocked_domains"] = blocked
        defs.append(d)
    return defs


async def execute(tool_name: str, args: dict, brand_id: str) -> str:
    t = TOOLS.get(tool_name)
    if not t:
        return f"ERROR: unknown tool {tool_name!r}. Available: {', '.join(TOOLS)}"
    try:
        return await t["fn"](args, brand_id)
    except Exception as exc:  # noqa: BLE001 — surface tool errors to the loop, don't crash it
        return f"ERROR: {tool_name} failed: {str(exc)[:200]}"
