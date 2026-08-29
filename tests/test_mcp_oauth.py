"""MCP OAuth token store — refresh-on-expiry + rotation persistence (fake engine, no DB/net)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from glitch_signal.agent.mcp import ServerSpec, parse_servers
from glitch_signal.agent.mcp.oauth import _needs_refresh, get_bearer


def test_needs_refresh():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert _needs_refresh(now + timedelta(seconds=3600), now) is False   # plenty left
    assert _needs_refresh(now + timedelta(seconds=60), now) is True       # < skew
    assert _needs_refresh(None, now) is True
    assert _needs_refresh(now + timedelta(seconds=1000), now, min_remaining_s=1500) is True


class _Res:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _Conn:
    def __init__(self, store):
        self.store = store

    async def execute(self, stmt, params=None):
        s = str(stmt).upper()
        if s.lstrip().startswith("SELECT"):
            return _Res(dict(self.store) if self.store else None)
        if "UPDATE" in s:
            self.store.update({"access_token": params["a"], "refresh_token": params["r"],
                               "expires_at": params["e"]})
        return _Res(None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Engine:
    def __init__(self, store):
        self.store = store

    def begin(self):
        return _Conn(self.store)


def _row(exp_delta_s):
    return {"access_token": "old_at", "refresh_token": "old_rt",
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=exp_delta_s),
            "client_id": "cid", "token_endpoint": "https://as/token", "resource": "https://mcp"}


async def test_returns_cached_token_when_valid():
    called = {"n": 0}

    async def refresh(row):
        called["n"] += 1
        return {}

    eng = _Engine(_row(3600))
    tok = await get_bearer("heygen", engine=eng, refresh=refresh)
    assert tok == "old_at" and called["n"] == 0            # still valid → no refresh


async def test_refreshes_and_rotates_when_expiring():
    eng = _Engine(_row(30))                                # < skew → must refresh

    async def refresh(row):
        assert row["refresh_token"] == "old_rt"            # uses the stored refresh token
        return {"access_token": "new_at", "refresh_token": "new_rt", "expires_in": 3600}

    tok = await get_bearer("heygen", engine=eng, refresh=refresh)
    assert tok == "new_at"
    assert eng.store["access_token"] == "new_at"           # persisted
    assert eng.store["refresh_token"] == "new_rt"          # rotation persisted


async def test_keeps_old_refresh_if_provider_did_not_rotate():
    eng = _Engine(_row(30))

    async def refresh(row):
        return {"access_token": "new_at", "expires_in": 3600}   # no new refresh_token

    await get_bearer("heygen", engine=eng, refresh=refresh)
    assert eng.store["refresh_token"] == "old_rt"          # kept the old one


def test_parse_servers_oauth_field():
    servers = parse_servers('[{"name":"heygen","url":"https://mcp.heygen.com/mcp","oauth":"heygen"}]')
    assert servers == [ServerSpec("heygen", "https://mcp.heygen.com/mcp", {}, "heygen")]
