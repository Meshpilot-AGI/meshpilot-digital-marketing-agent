"""SQLModel table definitions for Glitch Social Media Agent.

Every table stores a full audit trail:
  Signal → ContentScript → VideoJob → VideoAsset → ScheduledPost → PublishedPost → MetricsSnapshot

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

# ---------------------------------------------------------------------------
# Signal — one row per discovered event worth making a video about
# ---------------------------------------------------------------------------

class Signal(SQLModel, table=True):
    __tablename__ = "signal"

    id: str = Field(primary_key=True)
    brand_id: str = Field(index=True, default="glitch_executor")
    source: str                           # github | milestones | trading_metrics
    source_ref: str                       # commit SHA, milestone title, metric snapshot id
    summary: str                          # LLM-generated 1-sentence novelty description
    novelty_score: float
    status: str = "queued"                # queued | scripting | scripted | skipped
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# ContentScript — script per signal × platform
# ---------------------------------------------------------------------------

class ContentScript(SQLModel, table=True):
    __tablename__ = "content_script"

    id: str = Field(primary_key=True)
    brand_id: str = Field(index=True, default="glitch_executor")
    signal_id: str = Field(foreign_key="signal.id", index=True)
    platform: str                         # youtube_shorts | twitter | instagram_reels
    script_body: str
    content_type: str                     # cinematic | product | technical | data
    key_visuals: str = "[]"               # JSON list[str]
    shots: str = "[]"                     # JSON list[{visual, duration_s, model_hint}]
    status: str = "draft"                 # draft | approved | generating | done | failed
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# VideoJob — one row per shot (async generation tracked here)
# ---------------------------------------------------------------------------

class VideoJob(SQLModel, table=True):
    __tablename__ = "video_job"

    id: str = Field(primary_key=True)
    brand_id: str = Field(index=True, default="glitch_executor")
    script_id: str = Field(foreign_key="content_script.id", index=True)
    shot_index: int
    model: str                            # kling_2 | runway_gen4 | veo_3 | hailuo | mock
    prompt: str
    api_job_id: str | None = None
    status: str = "queued"               # queued | dispatched | polling | done | failed
    video_url: str | None = None
    local_path: str | None = None
    cost_usd: float | None = None
    last_error: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = None


# ---------------------------------------------------------------------------
# VideoAsset — assembled final video file
# ---------------------------------------------------------------------------

class VideoAsset(SQLModel, table=True):
    __tablename__ = "video_asset"

    id: str = Field(primary_key=True)
    brand_id: str = Field(index=True, default="glitch_executor")
    script_id: str = Field(foreign_key="content_script.id", unique=True, index=True)
    file_path: str
    duration_s: float
    quality_score: float | None = None
    qc_notes: str | None = None       # JSON from QC LLM
    assembler_version: str = "1.0"
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# ScheduledPost — publish queue entry (one per platform per asset)
# ---------------------------------------------------------------------------

class ScheduledPost(SQLModel, table=True):
    __tablename__ = "scheduled_post"

    id: str = Field(primary_key=True)
    brand_id: str = Field(index=True, default="glitch_executor")
    # asset_id is nullable for text-only posts (no backing VideoAsset). The
    # text pipeline creates a ContentScript and stores its id in script_id
    # instead. Exactly one of (asset_id, script_id) must be set on a row.
    asset_id: str | None = Field(default=None, foreign_key="video_asset.id", index=True)
    script_id: str | None = Field(default=None, foreign_key="content_script.id", index=True)
    platform: str
    scheduled_for: datetime
    status: str = "pending_veto"
    # pending_veto | queued | dispatching | awaiting_webhook | done | failed | vetoed
    veto_deadline: datetime | None = None
    attempts: int = 0
    last_attempt_at: datetime | None = None
    last_error: str | None = None
    # Vendor-side request identifier (e.g. the Buffer post id).
    # Populated when a publisher hands control off to an asynchronous vendor
    # pipeline. Used by the webhook handler and the reconciliation sweep to
    # correlate vendor callbacks back to the ScheduledPost row.
    vendor_request_id: str | None = Field(default=None, index=True)
    # Parsed-filename denormalisations used by the variant-aware dispatcher
    # to avoid posting visually near-duplicate Meta ad variants back-to-back.
    # Populated by telegram_preview when the ScheduledPost is created.
    variant_group: str | None = Field(default=None, index=True)
    product: str | None = None
    geo: str | None = None


# ---------------------------------------------------------------------------
# PublishedPost — terminal record after successful publish
# ---------------------------------------------------------------------------

class PublishedPost(SQLModel, table=True):
    __tablename__ = "published_post"

    id: str = Field(primary_key=True)
    brand_id: str = Field(index=True, default="glitch_executor")
    scheduled_post_id: str = Field(foreign_key="scheduled_post.id", unique=True)
    platform: str
    platform_post_id: str
    platform_url: str | None = None
    published_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# MetricsSnapshot — periodic pull of platform engagement data
# ---------------------------------------------------------------------------

class MetricsSnapshot(SQLModel, table=True):
    __tablename__ = "metrics_snapshot"

    id: str = Field(primary_key=True)
    brand_id: str = Field(index=True, default="glitch_executor")
    published_post_id: str = Field(foreign_key="published_post.id", index=True)
    captured_at: datetime = Field(default_factory=_utcnow)
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0


# ---------------------------------------------------------------------------
# ScoutCheckpoint — tracks last-seen position per repo / source
# ---------------------------------------------------------------------------

class ScoutCheckpoint(SQLModel, table=True):
    __tablename__ = "scout_checkpoint"

    source_key: str = Field(primary_key=True)  # e.g. "github:glitch-cod-confirm"
    brand_id: str = Field(index=True, default="glitch_executor")
    last_checked_at: datetime = Field(default_factory=_utcnow)
    last_ref: str | None = None             # last commit SHA or MILESTONES SHA


# ---------------------------------------------------------------------------
# PlatformAuth — per-brand OAuth credentials
# ---------------------------------------------------------------------------

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
