"""Sheet-posting reconciliation — currently a no-op.

Historically this reconciled sheet rows whose platform_post_id still carried
a `request:xxx` placeholder from an earlier async publisher's document-upload
path (the vendor accepted the post into a background worker but hadn't
finalized the real platform post id when we wrote the row back).

The sheet-posting path now routes through Buffer/Meta:
`platforms.buffer.create_post(..., mode="shareNow")`, which returns
a Buffer post id + status synchronously — there's nothing left to reconcile
here. Buffer's own async webhook/reconcile handling (for the video path)
lives in scheduler/queue.py, not here.

Kept as a callable no-op (rather than deleted) so
scheduler/queue.py::_sheet_reconcile_tick can keep importing and calling it
without a scheduler-side change.
"""
from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


async def reconcile_pending() -> dict:
    """No-op. Returns an empty summary dict for logging."""
    return {}
