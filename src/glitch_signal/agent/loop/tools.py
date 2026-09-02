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
    from urllib.parse import urlsplit

    import httpx

    from glitch_signal.media.generation.storage import upload_bytes
    from glitch_signal.media.imaging import apply_ops

    url = str(args.get("image_url", "")).strip()
    ops = args.get("ops", []) or []
    if not url:
        return "ERROR: edit_image requires image_url"
    if urlsplit(url).scheme != "https":
        return "ERROR: unsafe image_url: only https URLs are allowed"
    # SSRF guard (#92, hardened for #192): resolve the host ONCE with the async, non-blocking
    # getaddrinfo, require every resolved address to be public, then connect to that EXACT
    # validated IP (same pinned-connection pattern as web_fetch). This closes the DNS-rebinding
    # TOCTOU where a plain "validate the URL, then let httpx re-resolve it" guard can be bypassed
    # by a host that answers the guard's lookup and the fetch's lookup with different addresses.
    ok, why, host, ip, _port = await _web_url_resolve(url)
    if not ok:
        return f"ERROR: unsafe image_url: {why}"
    pinned, host_header = _pin_url(url, host, ip)
    async with httpx.AsyncClient(timeout=60, follow_redirects=False, trust_env=False) as c:
        r = await c.get(pinned, headers={"host": host_header, "user-agent": "Mozilla/5.0"},
                         extensions={"sni_hostname": host})
        if r.status_code >= 400:
            return f"ERROR: could not fetch image ({r.status_code})"
        data = r.content
    out = apply_ops(data, ops)
    fmt = next((str(o.get("format", "")).lower() for o in ops if o.get("op") == "format"), "png")
    ext = {"jpeg": "jpg", "jpg": "jpg", "webp": "webp"}.get(fmt, "png")
    ctype = {"jpg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/png")
    new_url = await upload_bytes(out, brand_id, ext=ext, content_type=ctype, prefix="edited")
    return f"edited image ({len(ops)} op(s)): {new_url}"


async def _t_publish(args: dict, brand_id: str) -> str:
    """Publish a post to a platform via Buffer (x/twitter/linkedin/tiktok…): `text` plus an optional
    `media_url`. GATED — the policy denies this unless `agent_publish_enabled`. As the pre-commit
    safety check for this irreversible outward action, the independent CONSCIENCE critic reviews the
    text first when conscience is enabled: an `escalate` verdict BLOCKS the post for a human."""
    from glitch_signal.platforms import buffer

    platform = str(args.get("platform", "")).strip().lower()
    text = str(args.get("text", "")).strip()
    if not platform:
        return "ERROR: publish requires 'platform'"
    if not text:
        return "ERROR: publish requires 'text'"

    # Pre-commit conscience gate on the irreversible action (deliberation design: conscience gates
    # publish). Advisory 'concerns' still posts; only 'escalate' blocks for a human.
    from glitch_signal.config import settings as _settings
    if bool(getattr(_settings(), "agent_conscience_enabled", False)):
        from glitch_signal.agent.loop import conscience
        facts = await conscience.brand_facts(brand_id)   # verified ground truth for the pre-publish gate
        verdict = await conscience.review(f"publish a post to {platform}", text, facts=facts)
        if verdict.get("verdict") == "escalate":
            return (f"BLOCKED by conscience (escalate): {str(verdict.get('notes', ''))[:200]} — "
                    "not published; a human must approve this post.")

    try:
        post_id, status = await buffer.create_post(brand_id, platform, text=text,
                                                   media_url=args.get("media_url"), mode="shareNow")
    except Exception as exc:  # noqa: BLE001 — surface to the agent, never crash the loop
        return f"ERROR: publish to {platform} failed: {str(exc)[:200]}"
    return f"PUBLISHED to {platform}: buffer_post_id={post_id} status={status}"


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


def _compact_trending(item: Any) -> dict:
    """Trim one trending item to the signals the agent needs (drops noisy url/expiry fields)."""
    if not isinstance(item, dict):
        return {"value": str(item)[:80]}
    out: dict[str, Any] = {}
    for k, v in item.items():
        # Drop large signed CDN links + their expiries generically: any camelCase *Url
        # (videoUrl/thumbnailUrl/coverUrl/dynamicCoverUrl/originCoverUrl…) or *ExpiresAt.
        # The item's canonical lowercase `url`/`permalink` is kept.
        if k.endswith("Url") or k.endswith("ExpiresAt"):
            continue
        if isinstance(v, str):
            out[k] = v[:160]
        elif isinstance(v, (int, float, bool)):
            out[k] = v
        elif isinstance(v, dict):
            out[k] = {kk: vv for kk, vv in list(v.items())[:5] if isinstance(vv, (str, int, float, bool))}
        elif isinstance(v, list):
            out[k] = v[:6]
    return out


async def _t_discover_trending(args: dict, brand_id: str) -> str:
    """Discover TRENDING social content (CaptAPI) as inspiration/signals. Gated by the policy —
    denied unless discovery is enabled, so this makes no external pull until deliberately turned on."""
    from glitch_signal.agent.discovery import captapi
    platform = str(args.get("platform", "instagram")).strip().lower()
    kind = str(args.get("kind") or ("reels" if platform == "instagram" else "feed")).strip().lower()
    country = args.get("country")
    try:
        data = await captapi.trending(platform, kind, country=country)
    except Exception as exc:  # noqa: BLE001 — surface to the loop, don't crash it
        return f"ERROR: discovery failed: {str(exc)[:200]}"
    lst = (next((v for v in data.values() if isinstance(v, list) and v), [])
           if isinstance(data, dict) else (data if isinstance(data, list) else []))
    trimmed = [_compact_trending(x) for x in lst[:10]]
    return json.dumps({"platform": data.get("platform", platform) if isinstance(data, dict) else platform,
                       "kind": kind, "country": (data.get("country") if isinstance(data, dict) else None),
                       "count": len(trimmed), "trending": trimmed})


async def _t_web_search(args: dict, brand_id: str) -> str:
    """Search the LIVE web via OpenRouter's native web plugin. Returns {answer, sources}. Gated: the
    policy denies this unless agent_web_search_enabled is on, so it only runs when deliberately enabled."""
    from glitch_signal.agent.loop import llm as agent_llm

    q = str(args.get("query", "")).strip()
    if not q:
        return "ERROR: web_search requires 'query'"
    try:
        answer, sources = await agent_llm.complete_web(q, max_results=int(args.get("max_results", 5)))
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: web_search failed: {str(exc)[:200]}"
    return json.dumps({"answer": answer[:3000], "sources": sources[:8]})


_WEB_FETCH_MAX_BYTES = 500_000   # hard cap on retained response bytes (memory / bandwidth bound)


def _canonical_host(host: str) -> str:
    """Canonicalize a hostname for comparison: lowercase, drop a terminal DNS-root dot, and IDNA-encode
    so equivalent forms compare equal (closes the FQDN-trailing-dot and unicode-vs-punycode bypasses of
    blocked-domain matching). Falls back to the lowercased value for non-IDNA / already-ascii input."""
    h = (host or "").strip().rstrip(".").lower()
    if not h:
        return ""
    try:
        return h.encode("idna").decode("ascii")
    except Exception:  # noqa: BLE001 — literal IPs, already-ascii, or malformed hosts: compare as-is
        return h


def _ip_is_public(ip_str: str) -> bool:
    """True iff `ip_str` is a routable public address (not private/loopback/link-local/reserved/etc.)."""
    import ipaddress
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
                or addr.is_multicast or addr.is_unspecified)


def _web_url_precheck(url: str) -> tuple[bool, str, str, int]:
    """Synchronous SSRF pre-check (no DNS): http(s) scheme, canonical host, not a blocked domain/host, and —
    for a literal-IP host — the IP is public. Returns (ok, why, canonical_host, port)."""
    import ipaddress
    from urllib.parse import urlsplit

    from glitch_signal.media.net import _BLOCKED_HOSTS

    p = urlsplit(url)
    if p.scheme not in ("http", "https"):
        return False, f"scheme {p.scheme!r} not allowed", "", 0
    host = _canonical_host(p.hostname or "")
    if not host:
        return False, "no host", "", 0
    if host in _BLOCKED_HOSTS:
        return False, f"blocked host {host!r}", "", 0
    blocked = [_canonical_host(d) for d in (os.environ.get("AGENT_WEB_BLOCKED_DOMAINS") or "").split(",")
               if d.strip()]
    if any(host == b or host.endswith("." + b) for b in blocked if b):
        return False, "domain is blocked (AGENT_WEB_BLOCKED_DOMAINS)", "", 0
    try:
        ipaddress.ip_address(host)       # literal IP → validate now (no DNS involved)
        if not _ip_is_public(host):
            return False, "host is a non-public address", "", 0
    except ValueError:
        pass                             # a hostname: IP validation happens after resolution
    port = p.port or (443 if p.scheme == "https" else 80)
    return True, "", host, port


async def _web_url_resolve(url: str) -> tuple[bool, str, str, str, int]:
    """SSRF guard + validated-address binding. Runs the sync pre-check, then resolves the host with the
    event loop's async getaddrinfo (never blocking the loop) and requires EVERY resolved address to be
    public. Returns (ok, why, host, validated_ip, port). The caller connects to `validated_ip` directly,
    so the address the guard approved is the exact address used — no second lookup, no DNS-rebinding
    window between validation and connection."""
    import asyncio
    import ipaddress
    import socket

    ok, why, host, port = _web_url_precheck(url)
    if not ok:
        return False, why, "", "", 0
    try:
        ipaddress.ip_address(host)       # already a literal IP (validated in the pre-check)
        return True, "", host, host, port
    except ValueError:
        pass
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except Exception:  # noqa: BLE001
        return False, "DNS resolution failed", "", "", 0
    ips = [info[4][0] for info in infos if info[4] and info[4][0]]
    if not ips:
        return False, "DNS resolution returned no addresses", "", "", 0
    for ip in ips:                        # refuse if ANY resolved address is non-public
        if not _ip_is_public(ip):
            return False, f"host resolves to a non-public address ({ip})", "", "", 0
    return True, "", host, ips[0], port


def _bracket_if_ipv6(literal: str) -> str:
    """RFC 3986/7230: an IPv6 literal needs square brackets in a URL authority / Host header
    (`[::1]:8080`), or the trailing `:port` becomes ambiguous with the address's own colons."""
    import ipaddress

    try:
        if ipaddress.ip_address(literal).version == 6:
            return f"[{literal}]"
    except ValueError:
        pass                          # not an IP literal (a hostname, or already bracketed) — leave as-is
    return literal


def _pin_url(url: str, host: str, ip: str) -> tuple[str, str]:
    """Rewrite `url`'s netloc to the validated `ip` so an httpx client connects to EXACTLY the
    address the SSRF guard approved — no second DNS lookup, no DNS-rebinding window. Returns
    (pinned_url, host_header): pass host_header as the `Host` header and `host` as the
    `sni_hostname` extension so TLS SNI + certificate verification stay bound to the real hostname.

    Both `ip` (always a literal — v4 or v6) and `host` (a literal when the original URL used an IPv6
    address, e.g. `https://[::1]:8080/x` — `urlsplit().hostname` strips the brackets) are bracketed
    when they're IPv6, so the authority/Host header stays valid (#196: an unbracketed IPv6 host
    produces a malformed `host:port` — the port becomes ambiguous with the address's own colons)."""
    from urllib.parse import urlsplit, urlunsplit

    p = urlsplit(url)
    ip_netloc = _bracket_if_ipv6(ip)
    if p.port:
        ip_netloc += f":{p.port}"
    pinned = urlunsplit((p.scheme, ip_netloc, p.path or "/", p.query, ""))
    host_literal = _bracket_if_ipv6(host)
    host_header = f"{host_literal}:{p.port}" if p.port else host_literal
    return pinned, host_header


async def _t_web_fetch(args: dict, brand_id: str) -> str:
    """Fetch a URL and return its readable text. Gated: the policy denies this unless
    agent_web_fetch_enabled is on, so it only runs when deliberately enabled. Also http(s) only,
    SSRF-checked with the connection PINNED to a validated public IP (original Host header + TLS SNI/cert
    hostname preserved), OS/env proxies disabled, redirects NOT followed, response hard-bounded to 500KB."""
    import re as _re

    import httpx as _httpx
    url = str(args.get("url", "")).strip()
    if not url:
        return "ERROR: web_fetch requires 'url'"
    ok, why, host, ip, _port = await _web_url_resolve(url)
    if not ok:
        return f"ERROR: web_fetch refused: {why}"
    # Pin the connection to the validated IP: the URL host becomes the IP literal, so httpx connects
    # exactly there with NO second DNS lookup that could rebind to a private address. The original Host
    # header and the sni_hostname extension keep TLS SNI + certificate verification bound to the real
    # hostname. trust_env=False stops HTTP(S)_PROXY / NO_PROXY from moving resolution or the destination
    # outside this guard.
    pinned, host_header = _pin_url(url, host, ip)
    try:
        async with _httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as c:
            async with c.stream("GET", pinned,
                                headers={"host": host_header, "user-agent": "Mozilla/5.0"},
                                extensions={"sni_hostname": host}) as r:
                if 300 <= r.status_code < 400:
                    return f"ERROR: web_fetch got a redirect (HTTP {r.status_code}) — not followed"
                if r.status_code >= 400:
                    return f"ERROR: web_fetch got HTTP {r.status_code}"
                chunks, total = [], 0
                async for chunk in r.aiter_bytes():
                    take = chunk[:_WEB_FETCH_MAX_BYTES - total]   # retain only the remaining allowance
                    chunks.append(take)
                    total += len(take)
                    if total >= _WEB_FETCH_MAX_BYTES:             # hard memory/bandwidth bound — stop now
                        break
        raw = b"".join(chunks).decode("utf-8", "ignore")
        text = _re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=_re.S | _re.I)
        text = _re.sub(r"<[^>]+>", " ", text)
        return _re.sub(r"\s+", " ", text).strip()[:4000] or "(no readable text)"
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: web_fetch failed: {str(exc)[:200]}"


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
                "description": "Publish a post to a platform (x/twitter/linkedin/tiktok) via Buffer — "
                               "`text` plus an optional `media_url`. GATED: denied unless publishing is "
                               "enabled; even then an 'escalate' conscience verdict blocks it.",
                "input_schema": _obj({"platform": {"type": "string"},
                                      "text": {"type": "string"},
                                      "media_url": {"type": "string"}}, ["platform", "text"])},
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
    "discover_trending": {"fn": _t_discover_trending,
                          "description": "Discover TRENDING social content for inspiration / signals. "
                                         "platform=instagram|tiktok; kind: instagram→reels, "
                                         "tiktok→feed|hashtags|songs|creators (default reels/feed). "
                                         "Returns the top trending items (caption, engagement, hashtags, "
                                         "author, url). NOTE: gated — denied unless discovery is enabled.",
                          "input_schema": _obj({"platform": {"type": "string", "enum": ["instagram", "tiktok"]},
                                                "kind": {"type": "string",
                                                         "enum": ["reels", "feed", "hashtags", "songs", "creators"]},
                                                "country": {"type": "string"}}, ["platform"], closed=False)},
    "web_search": {"fn": _t_web_search, "strict": True,
                   "description": "Search the LIVE web for current information (trends, examples, facts). "
                                  "Returns {answer, sources}.",
                   "input_schema": _obj({"query": {"type": "string"},
                                         "max_results": {"type": "integer"}}, ["query"])},
    "web_fetch": {"fn": _t_web_fetch, "strict": True,
                  "description": "Fetch a specific URL and return its readable text.",
                  "input_schema": _obj({"url": {"type": "string"}}, ["url"])},
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


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


def server_tool_defs() -> list[dict[str, Any]]:
    """Retired 2026-08-30 (OpenRouter migration). Anthropic server tools (web_search/web_fetch) don't
    exist on OpenRouter — web is now CLIENT tools (`web_search`/`web_fetch` in TOOLS, backed by
    OpenRouter's native web plugin). Kept as a no-op so the runner's tool assembly stays stable."""
    return []


async def execute(tool_name: str, args: dict, brand_id: str) -> str:
    t = TOOLS.get(tool_name)
    if not t:
        return f"ERROR: unknown tool {tool_name!r}. Available: {', '.join(TOOLS)}"
    try:
        return await t["fn"](args, brand_id)
    except Exception as exc:  # noqa: BLE001 — surface tool errors to the loop, don't crash it
        return f"ERROR: {tool_name} failed: {str(exc)[:200]}"
