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

from collections.abc import Mapping
from dataclasses import dataclass, field, replace

# Tools that perform an outward-facing publish.
PUBLISH_TOOLS = frozenset({"publish", "post", "publish_facebook", "publish_instagram", "buffer_post",
                           "job_apply"})

# Tools that send email (EMAIL-1) — gated by their own kill-switch, separate from publishing.
EMAIL_TOOLS = frozenset({"send_email"})

# Discovery tools (CaptAPI trending pulls) — gated by their own kill-switch. External, credit-metered
# pulls stay OFF until deliberately enabled, so the ability ships inert (no scraping until flipped).
DISCOVERY_TOOLS = frozenset({"discover_trending", "discover_conversations", "discover_communities"})

# Web tools (web_search / web_fetch) — each gated by its own kill-switch (#191). Live outbound
# search/fetch + LLM-plugin cost stay OFF until deliberately enabled, so the ability ships inert.
WEB_SEARCH_TOOLS = frozenset({"web_search"})
WEB_FETCH_TOOLS = frozenset({"web_fetch"})

# JOBS tools (JOBS-1) — three tiers, each with its own kill-switch. `job_apply` ALSO joins
# PUBLISH_TOOLS below, so it inherits the publish kill-switch: submitting an application is an
# outward, irreversible act in the operator's name, and one switch for it is not enough.
JOB_DISCOVERY_TOOLS = frozenset({"search_jobs", "fetch_jd"})
JOB_TAILOR_TOOLS = frozenset({"tailor_cv", "render_cv"})
JOB_APPLY_TOOLS = frozenset({"job_apply"})
JOB_TOOLS = JOB_DISCOVERY_TOOLS | JOB_TAILOR_TOOLS | JOB_APPLY_TOOLS | frozenset({"score_job", "offer_job"})

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
    email_enabled: bool = False
    discovery_enabled: bool = False
    web_search_enabled: bool = False
    web_fetch_enabled: bool = False
    jobs_enabled: bool = False
    job_discovery_enabled: bool = False
    job_tailor_enabled: bool = False
    job_apply_enabled: bool = False
    job_applications_today: int = 0      # already SUBMITTED today for this brand (caller supplies)
    max_job_applications_per_day: int = 3
    max_media_per_run: int = 3
    max_emails_per_run: int = 5
    max_discovery_per_run: int = 5
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

        # 3b. email kill-switch + per-run send cap (EMAIL-1) — sending stays off until enabled
        if tool_name in EMAIL_TOOLS:
            if not self.email_enabled:
                return Decision(False, "email sending is disabled (agent_email_enabled is off)")
            if counts.get(tool_name, 0) >= self.max_emails_per_run:
                return Decision(False, f"email budget exhausted ({self.max_emails_per_run} per run)")

        # 3c. discovery kill-switch + per-run pull cap — external CaptAPI pulls stay off until enabled
        if tool_name in DISCOVERY_TOOLS:
            if not self.discovery_enabled:
                return Decision(False, "discovery is disabled (agent_discovery_enabled is off)")
            if counts.get(tool_name, 0) >= self.max_discovery_per_run:
                return Decision(False, f"discovery budget exhausted ({self.max_discovery_per_run} per run)")

        # 3d. web kill-switches (#191) — outbound web search/fetch stays off until enabled
        if tool_name in WEB_SEARCH_TOOLS and not self.web_search_enabled:
            return Decision(False, "web_search is disabled (agent_web_search_enabled is off)")
        if tool_name in WEB_FETCH_TOOLS and not self.web_fetch_enabled:
            return Decision(False, "web_fetch is disabled (agent_web_fetch_enabled is off)")

        # 3e. JOBS kill-switches (JOBS-1). Tiered: the capability, then the tier, then the daily cap.
        #     Checked innermost-last so the denial reason names the switch the operator must flip.
        if tool_name in JOB_TOOLS:
            if not self.jobs_enabled:
                return Decision(False, "jobs capability is disabled (agent_jobs_enabled is off)")
            if tool_name in JOB_DISCOVERY_TOOLS and not self.job_discovery_enabled:
                return Decision(False, "job discovery is disabled (agent_job_discovery_enabled is off)")
            if tool_name in JOB_TAILOR_TOOLS and not self.job_tailor_enabled:
                return Decision(False, "CV tailoring is disabled (agent_job_tailor_enabled is off)")
            if tool_name in JOB_APPLY_TOOLS:
                if not self.job_apply_enabled:
                    return Decision(False, "applying is disabled (agent_job_apply_enabled is off)")
                # Per-DAY cap, not per-run: a runaway that restarts its loop would reset a per-run
                # counter and keep applying. The count is of rows already submitted today.
                if (self.max_job_applications_per_day
                        and self.job_applications_today >= self.max_job_applications_per_day):
                    return Decision(False, f"daily application cap reached "
                                           f"({self.max_job_applications_per_day}/day for {brand_id})")

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
        email_enabled=bool(getattr(s, "agent_email_enabled", False)),
        discovery_enabled=bool(getattr(s, "agent_discovery_enabled", False)),
        web_search_enabled=bool(getattr(s, "agent_web_search_enabled", False)),
        web_fetch_enabled=bool(getattr(s, "agent_web_fetch_enabled", False)),
        max_media_per_run=int(getattr(s, "agent_max_media_per_run", 3)),
        max_emails_per_run=int(getattr(s, "agent_max_emails_per_run", 5)),
        max_discovery_per_run=int(getattr(s, "agent_max_discovery_per_run", 5)),
        jobs_enabled=bool(getattr(s, "agent_jobs_enabled", False)),
        job_discovery_enabled=bool(getattr(s, "agent_job_discovery_enabled", False)),
        job_tailor_enabled=bool(getattr(s, "agent_job_tailor_enabled", False)),
        job_apply_enabled=bool(getattr(s, "agent_job_apply_enabled", False)),
        max_job_applications_per_day=int(getattr(s, "agent_job_max_applications_per_day", 3)),
        mcp_allow=mcp_allow,
    )


def allow(tool_name: str, args: dict, brand_id: str, *,
          counts: Mapping[str, int] | None = None) -> tuple[bool, str]:
    """Back-compat wrapper: check against the config-derived policy, return (allowed, reason)."""
    policy = from_config()
    # The per-DAY application cap needs a number only the DB has. Query it ONLY when the tool under
    # check is the submitting one — every other tool call would pay a round-trip for nothing.
    # Without this the cap reads 0 forever and never trips, which is the quiet kind of broken: the
    # switch exists, the tests pass, and it silently enforces nothing in production.
    if tool_name in JOB_APPLY_TOOLS and policy.job_apply_enabled:
        try:
            from glitch_signal.agent.jobs import store as _jobstore

            policy = replace(policy, job_applications_today=_jobstore.submitted_today(brand_id))
        except Exception as exc:  # noqa: BLE001
            # Fail CLOSED: if we cannot count today's submissions we must not assume zero.
            return False, f"cannot verify the daily application cap ({str(exc)[:80]})"
    return policy.check(tool_name, args, brand_id, counts=counts).as_tuple()
