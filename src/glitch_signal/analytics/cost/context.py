"""Ambient brand attribution — the active brand a vendor call should be billed to.

Per the multi-tenant cost-attribution playbook: pull the tenant from context, not a parameter you
can forget. Set the brand once at a run/job boundary; deep vendor calls inherit it automatically
(contextvars propagate across `await` and are copied into `asyncio.create_task`).
"""
from __future__ import annotations

import contextlib
import contextvars

_brand: contextvars.ContextVar[str | None] = contextvars.ContextVar("meter_brand", default=None)


def set_brand(brand_id: str | None):
    return _brand.set(brand_id)


def get_brand() -> str | None:
    return _brand.get()


@contextlib.contextmanager
def brand_scope(brand_id: str | None):
    """Set the active brand for the duration of a block (restores the previous brand on exit)."""
    token = _brand.set(brand_id)
    try:
        yield
    finally:
        _brand.reset(token)
