"""MCP OAuth token store — refresh-on-expiry + rotation persistence (fake engine, no DB/net)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from glitch_signal.agent.mcp import ServerSpec, parse_servers
from glitch_signal.agent.mcp.oauth import _needs_refresh, get_bearer
from glitch_signal.crypto import decrypt


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
            self.store.update({"access_token_enc": params["a_enc"], "refresh_token_enc": params["r_enc"],
                               "access_token": None, "refresh_token": None, "expires_at": params["e"]})
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
    # legacy row: plaintext columns populated, *_enc still null (un-migrated) → exercises dual-read
    return {"access_token_enc": None, "refresh_token_enc": None,
            "access_token": "old_at", "refresh_token": "old_rt",
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
    # persisted ENCRYPTED (#91): ciphertext at rest, plaintext columns nulled
    assert eng.store["access_token_enc"] != "new_at"
    assert eng.store["access_token"] is None
    assert decrypt(eng.store["access_token_enc"]) == "new_at"
    assert decrypt(eng.store["refresh_token_enc"]) == "new_rt"   # rotation persisted (encrypted)


async def test_keeps_old_refresh_if_provider_did_not_rotate():
    eng = _Engine(_row(30))

    async def refresh(row):
        return {"access_token": "new_at", "expires_in": 3600}   # no new refresh_token

    await get_bearer("heygen", engine=eng, refresh=refresh)
    assert decrypt(eng.store["refresh_token_enc"]) == "old_rt"   # kept the old one (encrypted)


async def test_refresh_happens_outside_the_lock():
    # #96: the HTTP refresh must run with no open transaction. Track begin() vs refresh ordering.
    events = []

    class _TrackConn(_Conn):
        async def __aenter__(self):
            events.append("txn_open")
            return self

        async def __aexit__(self, *a):
            events.append("txn_close")
            return False

    class _TrackEngine(_Engine):
        def begin(self):
            return _TrackConn(self.store)

    eng = _TrackEngine(_row(30))

    async def refresh(row):
        events.append("refresh")
        return {"access_token": "new_at", "refresh_token": "new_rt", "expires_in": 3600}

    await get_bearer("heygen", engine=eng, refresh=refresh)
    # refresh occurs between two closed transactions, never inside an open one
    assert events == ["txn_open", "txn_close", "refresh", "txn_open", "txn_close"]


def test_parse_servers_oauth_field():
    servers = parse_servers('[{"name":"heygen","url":"https://mcp.heygen.com/mcp","oauth":"heygen"}]')
    assert servers == [ServerSpec("heygen", "https://mcp.heygen.com/mcp", {}, "heygen")]
