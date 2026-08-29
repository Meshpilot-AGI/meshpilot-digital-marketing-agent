"""Regression tests for the audit security fixes: SSRF guard (#92) + cron brand-scoping/IDOR (#95)."""
from __future__ import annotations

import pytest

from glitch_signal.media.net import assert_safe_media_url


# ── #92: SSRF guard ──
def test_ssrf_blocks_non_https():
    with pytest.raises(ValueError):
        assert_safe_media_url("http://example.com/x.png")


def test_ssrf_blocks_cloud_metadata():
    with pytest.raises(ValueError):
        assert_safe_media_url("https://169.254.169.254/latest/meta-data/")


def test_ssrf_blocks_private_ip(monkeypatch):
    # host resolves to a private address → blocked
    monkeypatch.setattr("socket.getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 443))])
    with pytest.raises(ValueError):
        assert_safe_media_url("https://internal.evil.test/x.png")


def test_ssrf_allows_public_https(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    assert_safe_media_url("https://cdn.example.com/x.png")  # no raise


# ── #95: cron job brand-scoping (IDOR) ──
class _Res:
    def __init__(self, first):
        self._first = first

    def mappings(self):
        return self

    def first(self):
        return self._first


class _Conn:
    def __init__(self, sink, row):
        self._sink, self._row = sink, row

    async def execute(self, stmt, params=None):
        self._sink.append((str(stmt), params))
        return _Res(self._row)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Engine:
    def __init__(self, row=None):
        self.calls = []
        self._row = row

    def begin(self):
        return _Conn(self.calls, self._row)

    def connect(self):
        return _Conn(self.calls, self._row)


async def test_get_job_passes_brand_predicate():
    from glitch_signal.agent.cron import store

    eng = _Engine(row=None)
    await store.get_job("job-1", brand_id="brand_b", engine=eng)
    sql, params = eng.calls[0]
    assert "brand_id = cast(:brand as text)" in sql.lower()
    assert params["brand"] == "brand_b"


async def test_delete_job_brand_scoped_reports_miss():
    from glitch_signal.agent.cron import store

    # wrong brand → DELETE ... RETURNING matches no row → False (IDOR closed)
    eng = _Engine(row=None)
    ok = await store.delete_job("job-1", brand_id="not_owner_brand", engine=eng)
    assert ok is False
    sql = eng.calls[0][0].lower()
    assert "brand_id = cast(:brand as text)" in sql and "returning id" in sql


async def test_delete_job_internal_unscoped_still_works():
    from glitch_signal.agent.cron import store

    eng = _Engine(row={"id": "job-1"})
    ok = await store.delete_job("job-1", engine=eng)  # brand_id None → internal path
    assert ok is True
