"""Interactive API docs must be OFF by default (not published to the public internet)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from glitch_signal.server import app


def test_docs_disabled_by_default():
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None


def test_docs_routes_404_by_default():
    client = TestClient(app)
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404
