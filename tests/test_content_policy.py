"""Content policy — strip AI footprints + scan the softer tells."""
from __future__ import annotations

from glitch_signal import content_policy as cp


# ── strip_footprints (deterministic auto-fix) ──
def test_strips_em_dash_to_comma():
    assert cp.strip_footprints("fast payouts — no waiting") == "fast payouts, no waiting"
    assert cp.strip_footprints("fast—simple") == "fast, simple"


def test_en_dash_range_becomes_hyphen():
    assert cp.strip_footprints("5–10 minutes") == "5-10 minutes"


def test_en_dash_non_range_becomes_comma():
    assert cp.strip_footprints("the challenge – our fastest – is live") == "the challenge, our fastest, is live"


def test_double_hyphen_and_bar():
    assert cp.strip_footprints("a -- b") == "a, b"
    assert cp.strip_footprints("a ― b") == "a, b"


def test_smart_quotes_and_ellipsis_normalized():
    assert cp.strip_footprints("“hi” it’s …") == '"hi" it\'s ...'


def test_tidies_comma_before_period():
    # em-dash right before end punctuation shouldn't leave ", ."
    assert cp.strip_footprints("done — .") == "done."


def test_strip_is_safe_on_clean_text():
    s = "your payout hits before your coffee. no games."
    assert cp.strip_footprints(s) == s


# ── scan_footprints (flag what needs a rewrite) ──
def test_scan_flags_banned_words():
    v = cp.scan_footprints("We leverage a seamless, robust ecosystem to elevate results.")
    joined = " ".join(v)
    assert "leverage" in joined and "seamless" in joined and "robust" in joined and "elevate" in joined


def test_scan_flags_not_only_but_also():
    v = cp.scan_footprints("It's not only fast but also simple.")
    assert any("not only" in x for x in v)


def test_scan_flags_remaining_dash():
    assert any("dash" in x for x in cp.scan_footprints("still — here"))


def test_scan_clean_text_is_empty():
    assert cp.scan_footprints("payouts hit fast. no waiting, no games.") == []


# ── enforce (clean then report) ──
def test_enforce_cleans_dash_then_flags_word():
    clean, violations = cp.enforce("Fast payouts — we leverage speed.")
    assert "—" not in clean and "," in clean          # dash auto-fixed
    assert any("leverage" in v for v in violations)   # word flagged for rewrite


# ── polish_copy tool ──
async def test_polish_copy_tool():
    import json

    from glitch_signal.agent.loop import tools

    out = json.loads(await tools.execute("polish_copy", {"text": "Fast — and seamless"}, "glitch_executor"))
    assert "—" not in out["clean"]
    assert any("seamless" in v for v in out["violations"])
