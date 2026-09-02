"""SQLModel table definitions for Glitch Social Media Agent.

Every table stores a full audit trail:

The ORM (reputation-management) chain that used to live here — MentionEvent → OrmResponse, plus
CommentReply and StrategicReply — was dropped in DB-OPT Tier 1 (2026-09-02): the subsystem had been
deleted, the models were declared but never queried, and every table held zero rows.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Naive UTC now. `datetime.utcnow()` is deprecated; this keeps the same naive-UTC value
    (no tzinfo) the schema and time comparisons rely on — see the sso-timestamps lesson."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

class PlatformAuth(SQLModel, table=True):
    """OAuth tokens stored encrypted at rest via Fernet (AUTH_ENCRYPTION_KEY).

    Never read the _enc columns directly — go through glitch_signal.oauth.storage.
    """
    __tablename__ = "platform_auth"

    id: str = Field(primary_key=True)
    brand_id: str = Field(index=True)
    platform: str = Field(index=True)                # tiktok | youtube | twitter | instagram
    account_identifier: str | None = Field(default=None, index=True)
    access_token_enc: str                            # Fernet ciphertext
    refresh_token_enc: str | None = None
    access_token_expires_at: datetime | None = None
    scopes: str = "[]"                               # JSON list[str]
    status: str = "active"                           # active | needs_reauth | revoked
    raw_provider_response: str = "{}"                # raw provider JSON for debugging
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
