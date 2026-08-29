"""brand_env_or_default — a brand's own value, falling back to the agent-wide default app."""
from __future__ import annotations

from glitch_signal.config import brand_env_or_default


def test_falls_back_to_global_default(monkeypatch):
    monkeypatch.delenv("GE_SYSTEM_USER_TOKEN", raising=False)
    monkeypatch.setenv("SYSTEM_USER_TOKEN", "meshpilot_default")     # agent-wide default
    assert brand_env_or_default("SYSTEM_USER_TOKEN", "glitch_executor") == "meshpilot_default"


def test_brand_value_overrides_default(monkeypatch):
    monkeypatch.setenv("SYSTEM_USER_TOKEN", "meshpilot_default")
    monkeypatch.setenv("GE_SYSTEM_USER_TOKEN", "ge_own")            # project brings its own
    assert brand_env_or_default("SYSTEM_USER_TOKEN", "glitch_executor") == "ge_own"


def test_empty_when_neither_set(monkeypatch):
    monkeypatch.delenv("GE_META_PAGE_ID", raising=False)
    monkeypatch.delenv("META_PAGE_ID", raising=False)
    assert brand_env_or_default("META_PAGE_ID", "glitch_executor") == ""
