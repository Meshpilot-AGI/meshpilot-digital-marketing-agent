"""Action policy gate (AGENT-POLICY) — a deterministic allow/deny check on every tool call.

OpenClaw-style: the loop is untrusted (an LLM picks tools); this gate is trusted and runs
BEFORE any tool executes. Rules, in order:

1. **Per-brand deny** — a brand may forbid specific tools outright.
2. **External MCP default-deny** — an `mcp__*` tool is allowed only if per-brand allowlisted, has a
   read-only verb prefix, or publishing is on; everything else is denied (leaky-denylist fix, #93).
3. **Publish kill-switch** — every publish/post tool is denied unless publishing is explicitly
   enabled (config `agent_publish_enabled`, default False). Posting stays off until flipped.
4. **Per-run cost budget** — expensive paid media generation is capped per loop run so a
   runaway agent can't rack up spend.

The `Policy` is a pure value object (no I/O) so it unit-tests trivially; `from_config()` builds
one from settings, and `allow()` is a thin back-compat wrapper over the default policy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

# Tools that perform an outward-facing publish.
PUBLISH_TOOLS = frozenset({"publish", "post", "publish_facebook", "publish_instagram", "buffer_post"})

# External MCP tools default-DENY (#93): we can't know an arbitrary MCP tool's blast radius, so a
# tool is allowed only if it is explicitly allowlisted per brand, has a read-only verb prefix, or
# publishing is deliberately enabled. A denylist of "bad" verbs is leaky (misses create/update/run/
# grant/…) — an allowlist is the safe default.
_MCP_READONLY_PREFIXES = ("get_", "list_", "search_", "describe_", "read_", "fetch_", "query_", "find_")


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str = ""

    def as_tuple(self) -> tuple[bool, str]:
        return self.allow, self.reason


@dataclass(frozen=True)
class Policy:
    publish_enabled: bool = False
    max_media_per_run: int = 3
    brand_denied: Mapping[str, frozenset[str]] = field(default_factory=dict)
    mcp_allow: Mapping[str, frozenset[str]] = field(default_factory=dict)  # brand -> allowed mcp__ tools

    def check(self, tool_name: str, args: dict, brand_id: str, *,
              counts: Mapping[str, int] | None = None) -> Decision:
        """Return a Decision. `counts` = how many times each tool already ran this loop."""
        counts = counts or {}

        # 1. per-brand explicit deny
        if tool_name in self.brand_denied.get(brand_id, frozenset()):
            return Decision(False, f"tool '{tool_name}' is denied for brand {brand_id}")

        # 2. external MCP tools — DEFAULT-DENY. Allow only: explicit per-brand allowlist, a read-only
        #    verb prefix, or publishing deliberately enabled. Everything else is denied.
        if tool_name.startswith("mcp__"):
            if tool_name in self.mcp_allow.get(brand_id, frozenset()):
                return Decision(True, "")
            verb = tool_name.split("__", 2)[-1]
            if verb.startswith(_MCP_READONLY_PREFIXES):
                return Decision(True, "")
            if self.publish_enabled:
                return Decision(True, "")  # publishing explicitly on → side-effecting MCP tools permitted
            return Decision(False, f"MCP tool '{tool_name}' not allowlisted for brand {brand_id} "
                                   "(default-deny; add to <PREFIX>_MCP_ALLOW or enable publishing)")

        # 3. publish kill-switch
        if tool_name in PUBLISH_TOOLS and not self.publish_enabled:
            return Decision(False, "posting is disabled (agent_publish_enabled is off)")

        # 4. per-run media budget (cost control)
        if tool_name == "generate_media" and counts.get("generate_media", 0) >= self.max_media_per_run:
            return Decision(False, f"media budget exhausted ({self.max_media_per_run} per run)")

        return Decision(True, "")


def from_config() -> Policy:
    """Build the active policy from settings (publishing off by default).

    Populates the per-brand MCP allowlist from each brand's `<PREFIX>_MCP_ALLOW` (a JSON array of
    fully-namespaced tool names, e.g. `["mcp__heygen__create_video_agent"]`). Without it, only
    read-only MCP tools pass by default (#93 default-deny) unless publishing is enabled.
    """
    import json

    from glitch_signal.config import brand_env, brand_ids, settings

    s = settings()
    mcp_allow: dict[str, frozenset[str]] = {}
    for brand in brand_ids():
        raw = brand_env("MCP_ALLOW", brand)
        if not raw:
            continue
        try:
            names = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(names, list):
            mcp_allow[brand] = frozenset(str(x) for x in names)
    return Policy(
        publish_enabled=bool(getattr(s, "agent_publish_enabled", False)),
        max_media_per_run=int(getattr(s, "agent_max_media_per_run", 3)),
        mcp_allow=mcp_allow,
    )


def allow(tool_name: str, args: dict, brand_id: str, *,
          counts: Mapping[str, int] | None = None) -> tuple[bool, str]:
    """Back-compat wrapper: check against the config-derived policy, return (allowed, reason)."""
    return from_config().check(tool_name, args, brand_id, counts=counts).as_tuple()
