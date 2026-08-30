"""Email sending (EMAIL-1) — the agent's outbound mail channel via Resend.

Gated by design: the agent's `send_email` tool is denied by the policy gate
unless `agent_email_enabled` is on (default OFF, mirroring `agent_publish_enabled`),
and every send is capped per brand per day. This module is the thin, brand-aware
send wrapper — it resolves the per-brand From address, runs the subject + body
through the content policy (no AI footprints), honours DISPATCH_MODE=dry_run, and
enforces the daily cap. Delivery/bounce feedback lands via POST /resend/webhook.
"""
from __future__ import annotations

import asyncio
import uuid

import structlog

from glitch_signal import content_policy
from glitch_signal.config import brand_config, brand_env, settings

log = structlog.get_logger(__name__)


def _from_address(brand_id: str, override: str | None) -> str:
    """Resolve the From address: explicit override → per-brand `<PREFIX>_RESEND_FROM`
    → brand config `email.from` → the agent-wide `RESEND_FROM` default."""
    if override:
        return override
    v = brand_env("RESEND_FROM", brand_id)
    if v:
        return v
    try:
        cfg = brand_config(brand_id)
        f = ((cfg.get("email") or {}).get("from")) or ""
        if f:
            return f
    except Exception:  # noqa: BLE001
        pass
    return settings().resend_from


async def send_email(
    *,
    brand_id: str,
    to: str | list[str],
    subject: str,
    html: str | None = None,
    text: str | None = None,
    from_addr: str | None = None,
) -> str:
    """Send one email for a brand via Resend. Returns the Resend message id.

    - DISPATCH_MODE=dry_run: logs intent, returns a mock id, sends nothing.
    - Subject + body are run through the content policy (strip AI footprints).
    - Enforces a per-brand daily send cap (SharedWindowLimiter over rate_counters).

    Raises RuntimeError on misconfiguration (no recipient/body/From/key, or cap reached).
    The kill-switch itself lives in the policy gate; this is the send-path backstop.
    """
    s = settings()
    recipients = [to] if isinstance(to, str) else list(to)
    recipients = [r for r in recipients if r and str(r).strip()]
    if not recipients:
        raise RuntimeError("send_email: no recipient")

    subject = content_policy.strip_footprints(subject or "")
    if html:
        html = content_policy.strip_footprints(html)
    if text:
        text = content_policy.strip_footprints(text)
    if not (html or text):
        raise RuntimeError("send_email: provide an html or text body")

    frm = _from_address(brand_id, from_addr)
    if not frm:
        raise RuntimeError(
            f"send_email: no From address for {brand_id} — set <PREFIX>_RESEND_FROM, "
            "brand config email.from, or the RESEND_FROM default"
        )

    # Per-brand daily cap (backstop; the agent_email_enabled kill-switch is the primary gate).
    cap = int(getattr(s, "agent_email_brand_daily_cap", 50))
    if cap > 0:
        from glitch_signal.middleware.shared_state import SharedWindowLimiter

        allowed, _ = await SharedWindowLimiter(cap, 86400.0).check(f"email:{brand_id}")
        if not allowed:
            raise RuntimeError(f"send_email: daily cap ({cap}) reached for brand {brand_id}")

    if s.is_dry_run:
        rid = f"email-dry-{uuid.uuid4().hex[:10]}"
        log.info("email.send.dry_run", brand=brand_id, to=recipients, subject=subject[:80])
        return rid

    if not s.resend_api_key:
        raise RuntimeError("send_email: RESEND_API_KEY is not set")

    import resend

    resend.api_key = s.resend_api_key
    params: dict = {"from": frm, "to": recipients, "subject": subject}
    if html:
        params["html"] = html
    if text:
        params["text"] = text
    resp = await asyncio.to_thread(resend.Emails.send, params)
    rid = (resp.get("id") if isinstance(resp, dict) else getattr(resp, "id", None)) or str(uuid.uuid4())
    log.info("email.sent", brand=brand_id, to=recipients, subject=subject[:80], message_id=rid)
    return rid
