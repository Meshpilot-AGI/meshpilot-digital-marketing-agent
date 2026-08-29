"""FastAPI Cloud entrypoint for the Mesh Pilot social-media agent.

FastAPI Cloud (and `fastapi run` / `fastapi dev`) auto-detect the ASGI app
from a top-level module. The application itself is defined in the installed
package at `glitch_signal.server`; this thin module re-exports it so the CLI
has a conventional `main:app` target, and wires observability (Logfire).

Run locally:
    uv sync
    uv run fastapi dev main.py

Deploy:
    fastapi cloud deploy        # or merge to `production` once the repo is linked
"""
from __future__ import annotations

import os

from glitch_signal.server import app  # noqa: F401  (re-exported for the CLI)

# Observability — Logfire. FastAPI Cloud injects LOGFIRE_TOKEN when the Logfire
# integration is connected in the dashboard. Guarded so local/dev without the
# token is a silent no-op rather than a boot failure.
if os.environ.get("LOGFIRE_TOKEN"):
    import logfire

    logfire.configure(token=os.environ["LOGFIRE_TOKEN"])
    logfire.instrument_fastapi(app)

__all__ = ["app"]
