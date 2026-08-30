"""Test bootstrap helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Deterministic Fernet key so crypto.encrypt/decrypt work in tests (mirrors prod AUTH_ENCRYPTION_KEY).
os.environ.setdefault("AUTH_ENCRYPTION_KEY", "l3mgT3MDKZ2g8oh2l8r4e1XaS0o7Q8mT9H5V1v3P2Hk=")

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _dispose_async_engines(monkeypatch):
    """Dispose every async SQLite engine a test creates.

    Many tests build an in-memory `sqlite+aiosqlite` engine and rewire `_session_factory`, but
    never `dispose()` it — the aiosqlite worker thread/connection then lingers and surfaces as a
    `ResourceWarning` (connection deleted before closed) or a `PytestUnhandledThreadExceptionWarning`
    during a LATER test. Every such test imports `create_async_engine` at call time, so we wrap it
    here to record each engine and dispose the underlying pool in teardown. `sync_engine.dispose()`
    is synchronous, so it works from this sync fixture (no event loop needed)."""
    import sqlalchemy.ext.asyncio as _sa_async

    created = []
    _real = _sa_async.create_async_engine

    def _tracking(*args, **kwargs):
        eng = _real(*args, **kwargs)
        created.append(eng)
        return eng

    monkeypatch.setattr(_sa_async, "create_async_engine", _tracking)
    yield
    if not created:
        return

    import asyncio

    async def _close_all():
        for eng in created:
            try:
                await eng.dispose()   # awaits the aiosqlite worker-thread close (sync dispose doesn't)
            except Exception:  # noqa: BLE001 — best-effort cleanup, never fail on teardown
                pass

    try:
        asyncio.run(_close_all())
    except Exception:  # noqa: BLE001
        pass
