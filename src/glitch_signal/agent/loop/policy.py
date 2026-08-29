"""Action policy gate (AGENT-POLICY stub, filled in a later increment).

Every tool call passes through `allow()` before execution. For now the ONLY rule is:
**publishing/posting is disabled** — the agent can plan, generate, and remember, but it
cannot post anywhere. AGENT-POLICY (increment 3) will add real allow/deny logic.
"""
from __future__ import annotations

# Tools that perform an outward-facing publish. Denied until AGENT-POLICY enables them.
PUBLISH_TOOLS = frozenset({"publish", "post", "publish_facebook", "publish_instagram", "buffer_post"})


def allow(tool_name: str, args: dict, brand_id: str) -> tuple[bool, str]:
    """(allowed, reason). Deny all publish tools; allow the rest for now."""
    if tool_name in PUBLISH_TOOLS:
        return False, "posting is disabled (AGENT-POLICY not yet enabled)"
    return True, ""
