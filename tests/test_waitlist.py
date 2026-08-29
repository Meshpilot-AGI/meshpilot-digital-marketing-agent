"""Public waitlist signup endpoint (#99)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from glitch_signal.server import app


class _Conn:
    def __init__(self, sink):
        self._sink = sink

    async def execute(self, stmt, params=None):
        self._sink.append((str(stmt), params))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Engine:
    def __init__(self):
        self.calls = []

    def begin(self):
        return _Conn(self.calls)


def test_waitlist_rejects_bad_email():
    client = TestClient(app)
    assert client.post("/waitlist", json={"email": "not-an-email"}).status_code == 422
    assert client.post("/waitlist", json={"email": ""}).status_code == 422


def test_waitlist_persists_valid_signup(monkeypatch):
    eng = _Engine()
    monkeypatch.setattr("glitch_signal.db.session._engine", lambda: eng)
    client = TestClient(app)
    r = client.post("/waitlist", json={"email": "Founder@Example.com", "source": "landing"})
    assert r.status_code == 200 and r.json()["ok"] is True
    stmt, params = eng.calls[0]
    assert "insert into waitlist" in stmt.lower() and "on conflict" in stmt.lower()
    assert params["email"] == "founder@example.com"  # normalized lower-case
    assert params["source"] == "landing"
