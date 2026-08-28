"""FastAPI Cloud entrypoint for the Mesh Pilot social-media agent.

FastAPI Cloud (and `fastapi run` / `fastapi dev`) auto-detect the ASGI app
from a top-level module. The application itself is defined in the installed
package at `glitch_signal.server`; this thin module just re-exports it so the
CLI has a conventional `main:app` target.

Run locally:
    uv sync
    uv run fastapi dev main.py

Deploy:
    uv run fastapi deploy        # or merge to `main` once the repo is linked
"""
from __future__ import annotations

from glitch_signal.server import app  # noqa: F401  (re-exported for the CLI)

__all__ = ["app"]
