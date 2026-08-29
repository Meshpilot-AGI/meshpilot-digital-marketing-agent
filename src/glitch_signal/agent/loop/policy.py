"""Action policy gate (AGENT-POLICY) — a deterministic allow/deny check on every tool call.

OpenClaw-style: the loop is untrusted (an LLM picks tools); this gate is trusted and runs
BEFORE any tool executes. Rules, in order:

1. **Per-brand deny** — a brand may forbid specific tools outright.
2. **Publish kill-switch** — every publish/post tool is denied unless publishing is explicitly
   enabled (config `agent_publish_enabled`, default False). Posting stays off until flipped.
3. **Per-run cost budget** — expensive paid media generation is capped per loop run so a
   runaway agent can't rack up spend.

The `Policy` is a pure value object (no I/O) so it unit-tests trivially; `from_config()` builds
one from settings, and `allow()` is a thin back-compat wrapper over the default policy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

# Tools that perform an outward-facing publish.
PUBLISH_TOOLS = frozenset({"publish", "post", "publish_facebook", "publish_instagram", "buffer_post"})


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

    def check(self, tool_name: str, args: dict, brand_id: str, *,
              counts: Mapping[str, int] | None = None) -> Decision:
        """Return a Decision. `counts` = how many times each tool already ran this loop."""
        counts = counts or {}

        # 1. per-brand explicit deny
        if tool_name in self.brand_denied.get(brand_id, frozenset()):
            return Decision(False, f"tool '{tool_name}' is denied for brand {brand_id}")

        # 2. publish kill-switch
        if tool_name in PUBLISH_TOOLS and not self.publish_enabled:
            return Decision(False, "posting is disabled (agent_publish_enabled is off)")

        # 3. per-run media budget (cost control)
        if tool_name == "generate_media" and counts.get("generate_media", 0) >= self.max_media_per_run:
            return Decision(False, f"media budget exhausted ({self.max_media_per_run} per run)")

        return Decision(True, "")


def from_config() -> Policy:
    """Build the active policy from settings (publishing off by default)."""
    from glitch_signal.config import settings

    s = settings()
    return Policy(
        publish_enabled=bool(getattr(s, "agent_publish_enabled", False)),
        max_media_per_run=int(getattr(s, "agent_max_media_per_run", 3)),
    )


def allow(tool_name: str, args: dict, brand_id: str, *,
          counts: Mapping[str, int] | None = None) -> tuple[bool, str]:
    """Back-compat wrapper: check against the config-derived policy, return (allowed, reason)."""
    return from_config().check(tool_name, args, brand_id, counts=counts).as_tuple()
