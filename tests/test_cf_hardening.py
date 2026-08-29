"""CF / origin hardening middleware tests (Part A)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from glitch_signal.middleware import (
    BodySizeLimitMiddleware,
    OriginAuthMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)


def _app_with(*middleware_specs) -> FastAPI:
    app = FastAPI()

    @app.get("/internal/thing")
    def internal():
        return {"ok": True}

    @app.get("/healthz")
    def health():
        return {"ok": True}

    @app.post("/internal/echo")
    def echo():
        return {"ok": True}

    for mw, kwargs in middleware_specs:
        app.add_middleware(mw, **kwargs)
    return app


# ── origin auth ───────────────────────────────────────────────────────
def test_origin_auth_fail_open_when_unset():
    c = TestClient(_app_with((OriginAuthMiddleware, {"secret": None})))
    assert c.get("/internal/thing").status_code == 200  # gate disabled


def test_origin_auth_blocks_gated_without_header():
    c = TestClient(_app_with((OriginAuthMiddleware, {"secret": "s3cret"})))
    assert c.get("/internal/thing").status_code == 403


def test_origin_auth_allows_gated_with_header():
    c = TestClient(_app_with((OriginAuthMiddleware, {"secret": "s3cret"})))
    r = c.get("/internal/thing", headers={"x-origin-auth": "s3cret"})
    assert r.status_code == 200


def test_origin_auth_wrong_header_blocked():
    c = TestClient(_app_with((OriginAuthMiddleware, {"secret": "s3cret"})))
    assert c.get("/internal/thing", headers={"x-origin-auth": "nope"}).status_code == 403


def test_origin_auth_ungated_paths_open():
    c = TestClient(_app_with((OriginAuthMiddleware, {"secret": "s3cret"})))
    assert c.get("/healthz").status_code == 200  # not /internal|/jobs → open


# ── security headers ──────────────────────────────────────────────────
def test_security_headers_present():
    c = TestClient(_app_with((SecurityHeadersMiddleware, {})))
    h = c.get("/healthz").headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert "max-age=" in h["strict-transport-security"]


# ── body limit ────────────────────────────────────────────────────────
def test_body_limit_rejects_oversized():
    c = TestClient(_app_with((BodySizeLimitMiddleware, {"max_bytes": 10})))
    assert c.post("/internal/echo", content=b"x" * 50).status_code == 413


def test_body_limit_allows_small():
    c = TestClient(_app_with((BodySizeLimitMiddleware, {"max_bytes": 1000})))
    assert c.post("/internal/echo", content=b"small").status_code == 200


# ── rate limit ────────────────────────────────────────────────────────
def test_rate_limit_429_after_ceiling():
    c = TestClient(_app_with((RateLimitMiddleware, {"per_ip": 2, "window_s": 60, "global_limit": 100})))
    assert c.get("/internal/thing").status_code == 200
    assert c.get("/internal/thing").status_code == 200
    r = c.get("/internal/thing")
    assert r.status_code == 429 and int(r.headers.get("retry-after", "0")) >= 1


def test_rate_limit_healthz_exempt():
    c = TestClient(_app_with((RateLimitMiddleware, {"per_ip": 1, "window_s": 60, "global_limit": 100})))
    assert c.get("/healthz").status_code == 200
    assert c.get("/healthz").status_code == 200  # exempt → never limited
