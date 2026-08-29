"""FastAPI Cloud entrypoint for the Mesh Pilot social-media agent.

FastAPI Cloud (and `fastapi run` / `fastapi dev`) auto-detect the ASGI app
from a top-level module. The application itself is defined in the installed
package at `glitch_signal.server`; this thin module re-exports it and wires
observability (Sentry + Logfire).

Run locally:
    uv sync
    uv run fastapi dev main.py
"""
from __future__ import annotations

import os

# Sentry must init BEFORE the FastAPI app is created (importing server.py
# creates it), so Sentry's FastAPI integration auto-enables. Guarded on
# SENTRY_DSN so local/dev without it is a no-op.
if os.environ.get("SENTRY_DSN"):
    import sentry_sdk

    sentry_sdk.init(
        dsn=os.environ["SENTRY_DSN"],
        send_default_pii=True,
        traces_sample_rate=1.0,
    )

from glitch_signal.server import app  # noqa: E402  (app import after Sentry init, by design)

# Logfire — FastAPI Cloud injects LOGFIRE_TOKEN when the integration is
# connected. Guarded so a missing token is a silent no-op.
if os.environ.get("LOGFIRE_TOKEN"):
    import logfire

    logfire.configure(token=os.environ["LOGFIRE_TOKEN"])
    logfire.instrument_fastapi(app)

__all__ = ["app"]
