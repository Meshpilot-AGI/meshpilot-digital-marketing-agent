"""AGENT-POLICY — deterministic tool-call gate (pure, no network/DB)."""
from __future__ import annotations

from glitch_signal.agent.loop import policy
from glitch_signal.agent.loop.policy import Policy


# ── publish kill-switch ───────────────────────────────────────────────
def test_publish_denied_when_disabled():
    p = Policy(publish_enabled=False)
    for t in ["publish", "post", "publish_instagram", "buffer_post"]:
        d = p.check(t, {}, "glitch_executor")
        assert d.allow is False and "disabled" in d.reason


def test_publish_allowed_when_enabled():
    p = Policy(publish_enabled=True)
    assert p.check("publish", {}, "glitch_executor").allow is True


# ── read/memory tools always allowed ──────────────────────────────────
def test_non_publish_tools_allowed():
    p = Policy()
    for t in ["recall", "remember", "list_recipes"]:
        assert p.check(t, {}, "b").allow is True


# ── per-run media budget (cost control) ───────────────────────────────
def test_media_budget_enforced():
    p = Policy(max_media_per_run=2)
    assert p.check("generate_media", {}, "b", counts={"generate_media": 0}).allow is True
    assert p.check("generate_media", {}, "b", counts={"generate_media": 1}).allow is True
    d = p.check("generate_media", {}, "b", counts={"generate_media": 2})
    assert d.allow is False and "budget" in d.reason


# ── web kill-switches (#191) ───────────────────────────────────────────
def test_web_search_denied_when_disabled():
    p = Policy(web_search_enabled=False)
    d = p.check("web_search", {}, "b")
    assert d.allow is False and "disabled" in d.reason


def test_web_search_allowed_when_enabled():
    p = Policy(web_search_enabled=True)
    assert p.check("web_search", {}, "b").allow is True


def test_web_fetch_denied_when_disabled():
    p = Policy(web_fetch_enabled=False)
    d = p.check("web_fetch", {}, "b")
    assert d.allow is False and "disabled" in d.reason


def test_web_fetch_allowed_when_enabled():
    p = Policy(web_fetch_enabled=True)
    assert p.check("web_fetch", {}, "b").allow is True


def test_web_switches_are_independent():
    # enabling one web tool must not implicitly enable the other
    p = Policy(web_search_enabled=True, web_fetch_enabled=False)
    assert p.check("web_search", {}, "b").allow is True
    assert p.check("web_fetch", {}, "b").allow is False


def test_from_config_defaults_web_tools_off():
    p = policy.from_config()
    assert p.web_search_enabled is False              # safe default (#191)
    assert p.web_fetch_enabled is False
    assert p.check("web_search", {}, "b").allow is False
    assert p.check("web_fetch", {}, "b").allow is False


# ── per-brand explicit deny ───────────────────────────────────────────
def test_per_brand_deny():
    p = Policy(brand_denied={"acme": frozenset({"generate_media"})})
    assert p.check("generate_media", {}, "acme").allow is False
    assert p.check("generate_media", {}, "other").allow is True  # only acme denied


# ── back-compat allow() + config wiring ───────────────────────────────
def test_allow_wrapper_denies_publish_by_default():
    allowed, reason = policy.allow("publish", {}, "b")
    assert allowed is False and reason


def test_allow_wrapper_permits_recall():
    allowed, _ = policy.allow("recall", {}, "b")
    assert allowed is True


def test_from_config_defaults_publishing_off():
    p = policy.from_config()
    assert p.publish_enabled is False               # safe default
    assert p.check("publish", {}, "b").allow is False


def test_an_mcp_tool_that_hides_its_verb_in_an_argument_is_denied_by_default():
    """🔴 Measured 2026-09-17. viaSocket exposes ONE tool per app and selects the verb with an
    `action_name` argument: `mcp__viasocket__Gmail` can Search Email Messages OR Send Email. Gating
    on the tool name cannot tell those apart, and because publishing was enabled the default-deny
    branch was bypassed entirely — so the agent could have sent mail as the operator.

    A tool whose name does not bound its blast radius must be allowlisted per ACTION."""
    from glitch_signal.agent.loop.policy import Policy

    p = Policy(publish_enabled=True)   # publishing ON — must NOT wave this through
    d = p.check("mcp__viasocket__Gmail", {"action_name": "rowSEND123"}, "tejas")
    assert not d.allow
    assert "mcp__viasocket__Gmail:rowSEND123" in d.reason, "the error must name the exact fix"
    assert "publishing does NOT grant this" in d.reason


def test_the_exact_action_allowlist_entry_permits_just_that_action():
    from glitch_signal.agent.loop.policy import Policy

    p = Policy(mcp_allow={"tejas": frozenset({"mcp__viasocket__Gmail:rowREAD1"})})
    assert p.check("mcp__viasocket__Gmail", {"action_name": "rowREAD1"}, "tejas").allow
    assert not p.check("mcp__viasocket__Gmail", {"action_name": "rowSEND2"}, "tejas").allow, \
        "allowlisting one action must not permit the others on the same tool"


def test_a_human_readable_read_action_still_classifies_honestly():
    """An opaque id cannot be judged, but `search_messages` can — and refusing it would push
    operators toward allowlisting everything, which is worse."""
    from glitch_signal.agent.loop.policy import Policy

    p = Policy()
    assert p.check("mcp__x__Gmail", {"action_name": "search_messages"}, "tejas").allow
    assert not p.check("mcp__x__Gmail", {"action_name": "send_message"}, "tejas").allow
