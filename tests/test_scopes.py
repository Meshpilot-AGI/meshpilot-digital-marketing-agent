"""SCOPE — tool-scoping registry, resolver, subset (anti-escalation), runner filter."""
from __future__ import annotations

from glitch_signal.agent.loop import scopes
from glitch_signal.agent.loop.runner import run


# ── registry / resolver ───────────────────────────────────────────────
def test_resolve_and_allows():
    chat = scopes.resolve("chat")
    assert chat.allows("recall") and chat.allows("polish_copy") and chat.allows("read_brand_doc")
    assert not chat.allows("discover_trending") and not chat.allows("generate_media")
    assert not chat.allows("publish") and not chat.allows("send_email")
    assert not chat.allows("mcp__higgsfield__generate_image")     # no mcp in chat

    content = scopes.resolve("content")
    assert content.allows("generate_media") and content.allows("mcp__higgsfield__generate_image")
    assert not content.allows("discover_trending") and not content.allows("send_email")

    disc = scopes.resolve("discovery")
    assert disc.allows("discover_trending") and disc.allows("web_search")
    assert scopes.resolve("full").allows("publish")               # full = everything


def test_unknown_scope_falls_back_to_chat():
    s = scopes.resolve("nonsense")
    assert s.name == "chat" and s.allows("recall") and not s.allows("generate_media")


def test_is_subset_anti_escalation():
    assert scopes.is_subset("chat", "full") is True
    assert scopes.is_subset("full", "chat") is False
    assert scopes.is_subset("content", "content") is True
    assert scopes.is_subset("content", "discovery") is False      # media/higgsfield not in discovery
    assert scopes.is_subset("bogus", "full") is False             # unknown child denied → clamp


def test_current_contextvar():
    scopes.set_current("content")
    assert scopes.current() == "content"
    scopes.set_current(None)
    assert scopes.current() == "chat"


# ── runner offers only scoped tools ───────────────────────────────────
def _capturing_llm(store):
    async def _llm(messages, *, tools=None, system=None):
        store["tools"] = {t["name"] for t in (tools or [])}
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "done"}]}
    return _llm


async def _exec(tool, args, brand_id):
    return "[]"


async def test_runner_scope_filters_offered_tools():
    cap = {}
    await run("b", "g", llm=_capturing_llm(cap), execute=_exec, scope="chat")
    t = cap["tools"]
    assert {"recall", "polish_copy", "read_brand_doc"} <= t
    assert "discover_trending" not in t and "generate_media" not in t and "publish" not in t

    await run("b", "g", llm=_capturing_llm(cap), execute=_exec, scope="content")
    t = cap["tools"]
    assert "generate_media" in t and "recall" in t
    assert "discover_trending" not in t and "send_email" not in t


async def test_runner_default_scope_is_chat():
    cap = {}
    await run("b", "g", llm=_capturing_llm(cap), execute=_exec)   # no scope → chat
    assert "recall" in cap["tools"] and "generate_media" not in cap["tools"]
