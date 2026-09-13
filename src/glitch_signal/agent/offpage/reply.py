"""OFFPAGE-2 REPLY — answer a stranger's question well; earn the right to do it unattended.

The finder scores recent Reddit threads (`signal_item`), the drafter answers the top few from
facts the brand can prove, and every draft becomes an `offpage_candidate` offered to the operator in
Discord. At stage R0 the operator posts by hand and the account earns standing from genuinely
useful answers; the ladder (standing.py) derives the stage from that evidence — no setter.

    score = surface_fit × recency × question × novelty
      recency  1.0 <6h · 0.7 <24h · 0.3 <48h · 0 older        (a gate disguised as a factor)
      question 1.0 asks for a tool / comparison / rule / how-to · 0.4 otherwise
      novelty  0 we commented or were named · 0.5 a competitor is recommended · 1 otherwise

The only tunable opinion is `question`: answering a question is the one behaviour every
subreddit's rules permit. Design: docs/plans/2026-09-12-offpage-seo.md § 4 S3, § 5.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import text

from glitch_signal.agent.offpage import store
from glitch_signal.agent.offpage.syndicate import figures, supported

log = structlog.get_logger()

LEVER = "reply"
SURFACE_KIND = "subreddit"
DEFAULTS = {"daily_candidates": 3, "min_gap_hours": 72, "max_age_hours": 48, "offer_ttl_hours": 36}
MAX_CHARS = 1200
# Phrases no reply may carry, whatever the brand: promises. A brand adds its own under
# `offpage.forbidden_phrases`. (The ORM hard stops are the wrong list here — GE's includes "loss",
# which every drawdown answer must say.)
DEFAULT_FORBIDDEN = ("guaranteed", "guarantee", "risk-free", "risk free", "cannot lose", "can't lose",
                     "100% pass", "sure pass")
_ASKS = re.compile(r"\b(which|what|how do|how to|any (?:good|decent)|recommend|recommendation|best|"
                   r"alternative|vs\b|versus|should i|is there a|looking for|does anyone|anyone (?:use|know))",
                   re.I)
_TOOL_ASK = re.compile(r"\b(tool|app|software|tracker|dashboard|platform|bot|ea\b|service|recommend)", re.I)
_COMPETITOR_HINT = re.compile(r"\b(i use|i'd recommend|i recommend|try|check out)\b", re.I)

_SIGNALS = text(
    "SELECT external_id, surface, title, excerpt, url, score AS upvotes, comment_count, observed_at, raw "
    "FROM signal_item WHERE brand_id = :b AND source = 'reddit' AND kind = 'post' "
    "  AND observed_at >= now() - interval '7 days' ORDER BY observed_at DESC LIMIT 300"
)


# --------------------------------------------------------------------------- config

def config_for(brand_id: str) -> dict:
    from glitch_signal.config import brand_config

    op = brand_config(brand_id).get("offpage") or {}
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in (op.get("reply") or {}).items() if k in DEFAULTS and isinstance(v, int)})
    cfg["brand_terms"] = [t for t in op.get("brand_terms", []) if isinstance(t, str)]
    cfg["forbidden"] = [p.lower() for p in list(DEFAULT_FORBIDDEN) + list(op.get("forbidden_phrases", []))]
    cfg["product_line"] = str(op.get("product_line") or "").strip()
    return cfg


# --------------------------------------------------------------------------- scoring

def created_at(item: dict) -> datetime | None:
    raw = item.get("raw") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    ts = raw.get("created_utc")
    if ts:
        try:
            return datetime.fromtimestamp(float(ts), tz=UTC)
        except (TypeError, ValueError, OSError):
            pass
    obs = item.get("observed_at")
    if isinstance(obs, datetime):
        return obs if obs.tzinfo else obs.replace(tzinfo=UTC)
    return None


def recency(age: timedelta | None) -> float:
    if age is None or age < timedelta(0):
        return 0.0
    if age < timedelta(hours=6):
        return 1.0
    if age < timedelta(hours=24):
        return 0.7
    if age < timedelta(hours=48):
        return 0.3
    return 0.0


def question(title: str, excerpt: str) -> float:
    t = f"{title} {excerpt}"
    return 1.0 if ("?" in t or _ASKS.search(t)) else 0.4


def asks_for_tool(title: str, excerpt: str) -> bool:
    return bool(_TOOL_ASK.search(f"{title} {excerpt}"))


def mentions_any(text_: str, terms: list[str]) -> bool:
    low = text_.lower()
    return any(re.search(rf"\b{re.escape(t.lower())}\b", low) for t in terms if t)


def novelty(title: str, excerpt: str, *, brand_terms: list[str], already_commented: bool) -> float:
    if already_commented or mentions_any(f"{title} {excerpt}", brand_terms):
        return 0.0
    return 0.5 if _COMPETITOR_HINT.search(excerpt or "") else 1.0


def score(item: dict, *, now: datetime, surface_fit: float | None, brand_terms: list[str],
          already_commented: bool = False) -> tuple[float, dict]:
    made = created_at(item)
    parts = {
        "surface_fit": 0.5 if surface_fit is None else float(surface_fit),   # provisional prior
        "recency": recency(now - made if made else None),
        "question": question(item.get("title") or "", item.get("excerpt") or ""),
        "novelty": novelty(item.get("title") or "", item.get("excerpt") or "",
                           brand_terms=brand_terms, already_commented=already_commented),
    }
    total = parts["surface_fit"] * parts["recency"] * parts["question"] * parts["novelty"]
    return round(total, 4), parts


# --------------------------------------------------------------------------- finding

def pick(items: list[dict], *, surfaces: dict[str, dict], existing: list[dict], cfg: dict,
         now: datetime) -> list[tuple[dict, float, dict, dict]]:
    """Top threads to draft for, honouring every cap. Returns (item, score, parts, room)."""
    taken_urls = {c.get("target_url") for c in existing}
    today = [c for c in existing if c["created_at"] and
             (c["created_at"].replace(tzinfo=UTC) if c["created_at"].tzinfo is None else c["created_at"])
             >= now - timedelta(hours=24)]
    budget = max(0, cfg["daily_candidates"] - len(today))
    if budget == 0:
        return []
    recent_by_room: dict[str, datetime] = {}
    for c in existing:
        made = c["created_at"]
        made = made.replace(tzinfo=UTC) if made and made.tzinfo is None else made
        if made and (now - made) < timedelta(hours=cfg["min_gap_hours"]):
            recent_by_room[str(c.get("surface") or "").lower()] = made

    scored = []
    for it in items:
        url = it.get("url") or ""
        room = str(it.get("surface") or "").lower()
        if not url or url in taken_urls or not room:
            continue
        srow = surfaces.get(room) or {}
        if srow.get("status") == "blocked":
            continue
        if room in recent_by_room:
            continue
        s, parts = score(it, now=now, surface_fit=srow.get("fit_score"), brand_terms=cfg["brand_terms"])
        if s <= 0:
            continue
        scored.append((it, s, parts, srow))
    scored.sort(key=lambda x: x[1], reverse=True)
    out, rooms = [], set()
    for it, s, parts, srow in scored:
        room = str(it.get("surface")).lower()
        if room in rooms:
            continue                      # one thread per room per run — the gap cap, forward-looking
        out.append((it, s, parts, srow))
        rooms.add(room)
        if len(out) >= budget:
            break
    return out


# --------------------------------------------------------------------------- drafting

_PROMPT = """You are answering a stranger's Reddit thread as a knowledgeable trader, on behalf of a
brand's account. Write ONE reply, plain text, max {max_chars} characters, no links, no hashtags,
no sign-off, no "as an AI".

SUBREDDIT: r/{subreddit}
THREAD TITLE: {title}
THREAD TEXT: {excerpt}

FACTS YOU MAY USE (every figure in your reply must appear here or in the thread text):
{facts}

SUBREDDIT RULES (obey them; they outrank everything below):
{rules}

BRAND MENTION POLICY: {mention_policy}

Answer the actual question first, concretely. If a fact is unknown, say what to check and where
(the firm's own rules page), do not guess. Use no numbers other than those in the facts or the
thread — no illustrative figures, no "50-100 trades". No promises about outcomes. No superlatives.
No sales language. Sound like a person who has traded funded accounts, not a marketer. Reply with the
comment only."""


def mention_policy(*, allowed: bool, tool_asked: bool, product_line: str) -> str:
    if allowed and tool_asked and product_line:
        return (f"The thread asks for a tool. You may mention the brand's product ONCE, plainly, "
                f"in one sentence, and say you are from the team: {product_line}")
    return "Do NOT mention the brand or any product. Just answer."


def rules_excerpt(rules: Any, limit: int = 900) -> str:
    if not rules:
        return "(no rules captured — assume no self-promotion of any kind)"
    if isinstance(rules, str):
        return rules[:limit]
    try:
        items = rules if isinstance(rules, list) else (rules.get("rules") or rules.get("items") or [])
        lines = []
        for r in items:
            if isinstance(r, dict):
                lines.append("- " + str(r.get("shortName") or r.get("short_name") or r.get("title") or "")
                             + (": " + str(r.get("description") or r.get("violationReason") or "")[:160]
                                if (r.get("description") or r.get("violationReason")) else ""))
            else:
                lines.append("- " + str(r)[:160])
        return "\n".join(lines)[:limit] or json.dumps(rules)[:limit]
    except Exception:  # noqa: BLE001
        return json.dumps(rules)[:limit]


def rules_hash(rules: Any) -> str:
    return hashlib.sha256(json.dumps(rules, sort_keys=True, default=str).encode()).hexdigest()[:16]


_LIST_MARK = re.compile(r"(?m)^\s*\d+[.)]\s+")
_SHORTEN = """Shorten this Reddit reply to at most {max_chars} characters. Keep every figure and firm
name exactly as written, drop the least important point first, no new facts, no links.
Reply with the shortened comment only.

{body}"""


def trim_to(body: str, limit: int) -> str:
    """Cut at the last sentence end under the limit — a comment that ends mid-word reads as a bot."""
    if len(body) <= limit:
        return body
    cut = body[:limit]
    end = max(cut.rfind(". "), cut.rfind(".\n"), cut.rfind("? "), cut.rfind("! "))
    return (cut[:end + 1] if end > limit // 2 else cut.rsplit(" ", 1)[0]).rstrip()


def check(draft: str, *, facts: str, thread_text: str, cfg: dict, mention_allowed: bool) -> list[str]:
    problems: list[str] = []
    body = _LIST_MARK.sub("", draft.strip())          # "1. " list markers are not figures
    if not body:
        return ["empty"]
    if len(body) > MAX_CHARS:
        problems.append(f"too_long:{len(body)}>{MAX_CHARS}")
    if re.search(r"https?://|www\.", body, re.I):
        problems.append("contains_url")
    known = figures(facts) | figures(thread_text)
    invented = sorted(f for f in figures(body) if not supported(f, known))
    if invented:
        problems.append("unsupported_figures:" + ",".join(invented))
    low = body.lower()
    hit = [p for p in cfg["forbidden"] if p and p in low]
    if hit:
        problems.append("forbidden:" + ",".join(hit))
    if mentions_any(body, cfg["brand_terms"]):
        if not mention_allowed:
            problems.append("brand_mention_not_allowed")
        elif sum(low.count(t.lower()) for t in cfg["brand_terms"]) > 1:
            problems.append("brand_mentioned_more_than_once")
    if re.search(r"\bas an ai\b|language model", low):
        problems.append("breaks_character")
    return problems


async def facts_for(title: str, excerpt: str, *, engine: Any = None) -> str:
    from glitch_signal.agent import firms

    keys = firms.rule_keys_for_topic(f"{title} {excerpt}")
    if not keys:
        return "(no firm-rule facts match this thread — answer from general knowledge without figures)"
    rows = await firms.rules_for_distribution(keys, engine=engine)
    return firms.distribution_block(rows, keys) or "(no live firm rules for these topics)"


async def _default_complete(prompt: str) -> str:
    from glitch_signal.agent.loop import llm as agent_llm

    last: Exception | None = None
    for tier in ("complex", "simple"):        # an answer to a person deserves the better model first
        try:
            out = await agent_llm.complete_messages([{"role": "user", "content": prompt}],
                                                    tier=tier, max_tokens=1500, timeout_s=120)
            if out and out.strip():
                return out
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise RuntimeError(f"no tier produced a reply: {str(last)[:160] if last else 'empty'}")


async def _signals(brand_id: str, *, engine: Any = None) -> list[dict]:
    async with store._engine_or(engine).connect() as conn:
        rows = (await conn.execute(_SIGNALS, {"b": brand_id})).mappings().all()
    return [dict(r) for r in rows]


async def _surfaces(brand_id: str, *, engine: Any = None) -> dict[str, dict]:
    from glitch_signal.agent.social.surfaces import top

    rows = await top(brand_id, kind=SURFACE_KIND, limit=100, engine=engine)
    return {str(r["handle"]).lower(): r for r in rows}


async def _rules(brand_id: str, room: str, *, engine: Any = None) -> Any:
    async with store._engine_or(engine).connect() as conn:
        row = (await conn.execute(text(
            "SELECT rules FROM surface WHERE brand_id = :b AND kind = 'subreddit' AND lower(handle) = :h"),
            {"b": brand_id, "h": room})).first()
    if not row:
        return None
    r = row[0]
    return json.loads(r) if isinstance(r, str) else r


async def run(brand_id: str, args: dict | None = None, *, engine: Any = None,
              deps: dict | None = None) -> dict:
    """Draft replies for today's top threads and offer them in Discord. Never posts anything."""
    args = args or {}
    d = deps or {}
    dry = bool(args.get("dry_run"))
    cfg = config_for(brand_id)
    now = d.get("now") or datetime.now(UTC)

    items = await (d.get("signals") or _signals)(brand_id, engine=engine)
    if not items:
        return {"skipped": "no_signals", "detail": "run offpage_listen_reddit first"}
    surfaces = await (d.get("surfaces") or _surfaces)(brand_id, engine=engine)
    existing = await (d.get("recent") or store.recent)(brand_id, LEVER, hours=24 * 30, engine=engine)
    picked = pick(items, surfaces=surfaces, existing=existing, cfg=cfg, now=now)
    out: dict[str, Any] = {"ran": "offpage_reply_draft", "dry_run": dry, "signals": len(items),
                           "picked": len(picked), "offered": 0, "refused": [], "drafts": []}
    if not picked:
        out["skipped"] = "nothing_to_draft"
        return out

    complete = d.get("complete") or _default_complete
    get_facts = d.get("facts") or facts_for
    get_rules = d.get("rules") or _rules
    offer = d.get("offer")
    if offer is None and not dry:
        from glitch_signal.agent.offpage.approvals import offer as _offer
        offer = _offer

    for it, s, parts, srow in picked:
        room = str(it.get("surface"))
        title, excerpt = it.get("title") or "", it.get("excerpt") or ""
        rules = await get_rules(brand_id, room.lower(), engine=engine)
        promo_allowed = srow.get("self_promo_allowed") is True
        tool_asked = asks_for_tool(title, excerpt)
        mention_ok = promo_allowed and tool_asked and bool(cfg["product_line"])
        facts = await get_facts(title, excerpt, engine=engine)
        try:
            body = (await complete(_PROMPT.format(
                max_chars=MAX_CHARS, subreddit=room, title=title, excerpt=excerpt[:1500], facts=facts,
                rules=rules_excerpt(rules),
                mention_policy=mention_policy(allowed=promo_allowed, tool_asked=tool_asked,
                                              product_line=cfg["product_line"])))).strip().strip('"')
            if len(body) > MAX_CHARS:            # models write well and count badly: one pass
                shorter = (await complete(_SHORTEN.format(max_chars=MAX_CHARS, body=body))).strip().strip('"')
                body = trim_to(shorter or body, MAX_CHARS)
        except Exception as exc:  # noqa: BLE001
            out["refused"].append({"url": it.get("url"), "error": f"draft_failed: {str(exc)[:160]}"})
            continue
        problems = check(body, facts=facts, thread_text=f"{title} {excerpt}", cfg=cfg,
                         mention_allowed=mention_ok)
        entry = {"url": it.get("url"), "subreddit": room, "title": title[:120], "score": s,
                 "parts": parts, "draft": body}
        if problems:
            entry["refused"] = problems
            out["refused"].append(entry)
            log.warning("offpage.reply.refused", url=it.get("url"), problems=problems)
            continue
        out["drafts"].append(entry)
        if dry:
            continue
        meta = {"subreddit": room, "title": title[:200], "score_parts": parts,
                "rules_hash": rules_hash(rules), "mention_allowed": mention_ok,
                "facts_keys": facts[:200]}
        cid = await store.add_candidate(brand_id, lever=LEVER, surface_kind=SURFACE_KIND, surface=room,
                                        draft=body, target_url=it.get("url"),
                                        source_ref=str(it.get("external_id") or ""), score=s, meta=meta,
                                        status="drafted", engine=engine)
        try:
            msg_id = await offer(brand_id, {"id": cid, "surface": room, "target_url": it.get("url"),
                                            "draft": body, "score": s, "draft_meta": meta})
            await store.mark_offered(cid, msg_id, ttl_hours=cfg["offer_ttl_hours"], engine=engine)
            out["offered"] += 1
        except Exception as exc:  # noqa: BLE001 — the row stays `drafted`; the decide tick re-offers
            out["refused"].append({"url": it.get("url"), "error": f"offer_failed: {str(exc)[:160]}"})
            log.warning("offpage.reply.offer_failed", candidate=cid, error=str(exc)[:160])
    return out
