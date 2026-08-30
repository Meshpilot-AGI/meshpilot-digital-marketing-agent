"""Per-run tool scoping (SCOPE) — bound the ReAct loop's toolset to the active job/pipeline.

A **scope** names a set of **capabilities**; a capability names a set of tools (an entry ending in
`*` is an `mcp__…` prefix match). The runner offers the model ONLY the tools the active scope allows,
so a capability is reachable only from the pipeline/job that asked for it — not by free-roaming
autonomy. Two independent layers: **scope = what's OFFERED**; the policy gate = **what's ALLOWED**
(kill-switches, caps). A tool runs only if it is in-scope AND policy-allowed. Default scope `chat` is
safe read+plan only (no external effects, no paid tools).
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass

# capability -> tool names ('name*' = mcp prefix match)
CAPABILITIES: dict[str, frozenset[str]] = {
    "memory": frozenset({"recall", "remember"}),
    "knowledge": frozenset({"list_playbooks", "read_playbook", "read_brand_doc"}),
    "quality": frozenset({"polish_copy"}),
    "media": frozenset({"list_recipes", "generate_media", "edit_image"}),
    "discovery": frozenset({"discover_trending"}),
    "web": frozenset({"web_search", "web_fetch"}),
    "schedule": frozenset({"schedule"}),
    "publish": frozenset({"publish", "send_email"}),
    "mcp:heygen": frozenset({"mcp__heygen__*"}),
    "mcp:higgsfield": frozenset({"mcp__higgsfield__*"}),
}

# scope -> capabilities
SCOPES: dict[str, frozenset[str]] = {
    "chat": frozenset({"memory", "knowledge", "quality"}),                       # safe default
    "discovery": frozenset({"memory", "knowledge", "discovery", "web"}),
    "content_draft": frozenset({"memory", "knowledge", "quality"}),              # caption-first content (no media)
    "content": frozenset({"memory", "knowledge", "quality", "media", "mcp:higgsfield"}),
    "orm": frozenset({"memory", "knowledge", "quality", "web"}),
    "full": frozenset(CAPABILITIES),                                             # everything
}

DEFAULT_SCOPE = "chat"


@dataclass(frozen=True)
class Scope:
    name: str
    exact: frozenset[str]
    prefixes: tuple[str, ...]
    all: bool = False   # `full` allows EVERY tool (incl. any configured MCP server, not just the two known)

    def allows(self, tool_name: str) -> bool:
        return (self.all or tool_name in self.exact
                or any(tool_name.startswith(p) for p in self.prefixes))


def resolve(name: str | None) -> Scope:
    """Resolve a scope name → a Scope. Unknown/blank → the safe `chat` default."""
    key = (name or DEFAULT_SCOPE).strip().lower()
    if key == "full":
        return Scope(name="full", exact=frozenset(), prefixes=(), all=True)  # everything, incl. any MCP
    caps = SCOPES.get(key)
    if caps is None:
        key, caps = DEFAULT_SCOPE, SCOPES[DEFAULT_SCOPE]
    exact: set[str] = set()
    prefixes: list[str] = []
    for cap in caps:
        for t in CAPABILITIES.get(cap, frozenset()):
            (prefixes.append(t[:-1]) if t.endswith("*") else exact.add(t))
    return Scope(name=key, exact=frozenset(exact), prefixes=tuple(prefixes))


def is_subset(child: str | None, parent: str | None) -> bool:
    """True if `child` scope's capabilities ⊆ `parent`'s (anti-escalation for self-scheduled jobs).

    An unknown `child` is NOT a subset (denied → clamp to the parent)."""
    c = SCOPES.get((child or "").strip().lower())
    if c is None:
        return False
    p = SCOPES.get((parent or DEFAULT_SCOPE).strip().lower(), SCOPES[DEFAULT_SCOPE])
    return c <= p


# The scope of the run currently executing on this task — so the `schedule` tool can clamp a
# self-scheduled job's scope to ⊆ the current run's scope (contextvars are per-task/coroutine).
_current: contextvars.ContextVar[str] = contextvars.ContextVar("current_scope", default=DEFAULT_SCOPE)


def set_current(name: str | None) -> None:
    _current.set((name or DEFAULT_SCOPE).strip().lower())


def current() -> str:
    return _current.get()
