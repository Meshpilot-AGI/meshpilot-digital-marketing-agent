"""Post one queued row from the sheet → Buffer / Meta → write result back.

Called by the scheduler tick in scheduler/queue.py. Idempotency comes from
the sheet's id column: every call flips the row to posted|failed so the
next tick won't re-fire it.

Routing (VENDOR-1, 2026-08-29): Upload-Post and native LinkedIn are gone.
Every row's legacy `platform` value (upload_post_x, upload_post_linkedin, …)
is normalized to a bare target (x, linkedin, tiktok, facebook, instagram,
youtube) and resolved via `config.resolve_publish_platform` to the surviving
publisher — Buffer (x / linkedin / tiktok) or Meta (facebook / instagram).
YouTube is video-file only and isn't reachable from this text/image sheet
path, so it's marked unsupported.
"""
from __future__ import annotations

import pathlib
from datetime import UTC, datetime

import structlog

from glitch_signal.config import brand_config, resolve_publish_platform, settings
from glitch_signal.db.models import PublishedPost, ScheduledPost
from glitch_signal.db.session import _session_factory
from glitch_signal.integrations.google_sheets import update_row_by_key
from glitch_signal.platforms import buffer, facebook, instagram
from glitch_signal.sheet_posting.quote_card import generate_quote_card
from glitch_signal.sheet_posting.reader import SHEET_COLUMNS, QueuedPost

log = structlog.get_logger(__name__)


async def post_one(row: QueuedPost) -> tuple[bool, str]:
    """Publish a single queued row. Returns (ok, message).

    On success, updates the sheet with posted_at / post_url / platform_post_id
    and flips status to posted. On failure, flips to failed with the error
    in notes.
    """
    cfg = brand_config(row.brand_id)
    target = row.platform.replace("upload_post_", "").strip().lower()

    if settings().is_dry_run:
        log.info(
            "sheet_posting.dry_run",
            row_id=row.id,
            brand_id=row.brand_id,
            platform=row.platform,
        )
        await _write_result(
            row,
            status="posted",
            post_url="https://dry-run.local/fake",
            platform_post_id=f"dry-{row.id[:8]}",
        )
        return True, "[dry-run] marked posted"

    try:
        key = resolve_publish_platform(row.brand_id, target)
    except RuntimeError as exc:
        return await _mark_failed(row, str(exc))

    if key == "youtube_shorts":
        return await _mark_failed(
            row,
            "youtube_shorts is video-file only; the sheet posting path only "
            "supports text/image content",
        )

    text = _augment_body(row, cfg, key)
    content_type = row.content_type or ("carousel" if target == "linkedin" else "text")

    media_url: str | None = None
    if content_type in ("quote_card", "carousel"):
        if content_type == "carousel":
            # Buffer/Meta have no multi-slide document post like the old
            # LinkedIn PDF carousel. Degrade to a single designed image
            # rather than trying to build a PDF for a publisher that can't
            # take one.
            log.info(
                "sheet_posting.carousel_degraded_to_single_image",
                row_id=row.id,
                brand_id=row.brand_id,
            )
        image_path = await generate_quote_card(body=text, brand_id=row.brand_id)
        media_url = buffer._build_signed_media_url(pathlib.Path(image_path))

    if key == "meta_instagram" and not media_url:
        return await _mark_failed(
            row, "instagram requires an image; row has no quote_card/carousel content"
        )

    try:
        if key.startswith("buffer_"):
            platform_post_id, _status = await buffer.create_post(
                row.brand_id,
                service=target,
                text=text,
                media_url=media_url,
                mode="shareNow",
            )
            post_url = None
        elif key == "meta_facebook":
            platform_post_id, post_url = await facebook.publish_facebook(
                brand_id=row.brand_id, message=text, image_url=media_url,
            )
        elif key == "meta_instagram":
            platform_post_id, post_url = await instagram.publish_instagram(
                brand_id=row.brand_id, caption=text, image_url=media_url,
            )
        else:
            return await _mark_failed(row, f"no sheet-posting route for publisher {key!r}")
    except Exception as exc:
        log.warning("sheet_posting.publish_failed", row_id=row.id, error=str(exc)[:200])
        return await _mark_failed(row, f"publish failed: {exc}")

    await _write_result(
        row,
        status="posted",
        post_url=post_url or "",
        platform_post_id=platform_post_id or "",
    )

    # Also write a PublishedPost row so downstream features (comment sweeper,
    # analytics) can find this post. We create a synthetic ScheduledPost
    # first because PublishedPost FKs to it; text posts use the nullable
    # asset_id path added in migration 0006.
    if platform_post_id:
        try:
            await _write_audit_rows(row, platform_post_id, post_url)
        except Exception as exc:
            log.warning("sheet_posting.audit_write_failed", row_id=row.id, error=str(exc)[:200])

    log.info(
        "sheet_posting.posted",
        row_id=row.id,
        brand_id=row.brand_id,
        platform=row.platform,
        publisher=key,
        platform_post_id=platform_post_id,
    )
    return True, "posted"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _write_result(
    row: QueuedPost,
    *,
    status: str,
    post_url: str = "",
    platform_post_id: str = "",
    extra_note: str = "",
) -> None:
    s = settings()
    now = datetime.now(UTC).replace(tzinfo=None)
    updates = {
        "status": status,
        "posted_at": now.isoformat(timespec="seconds"),
        "post_url": post_url,
        "platform_post_id": platform_post_id,
    }
    if extra_note:
        existing = row.notes or ""
        updates["notes"] = (existing + ("; " if existing else "") + extra_note).strip()
    try:
        await update_row_by_key(
            sheet_id=s.glitch_posts_sheet_id,
            worksheet=row.worksheet or s.glitch_posts_worksheet,
            columns=SHEET_COLUMNS,
            key_column="id",
            key_value=row.id,
            updates=updates,
        )
    except Exception as exc:
        log.error("sheet_posting.sheet_update_failed", row_id=row.id, error=str(exc)[:200])


async def _mark_failed(row: QueuedPost, reason: str) -> tuple[bool, str]:
    await _write_result(row, status="failed", extra_note=reason[:180])
    return False, reason


async def _write_audit_rows(
    row: QueuedPost, platform_post_id: str, post_url: str | None
) -> None:
    """Write ScheduledPost + PublishedPost so comment sweeper / analytics see this post."""
    import uuid

    now = datetime.now(UTC).replace(tzinfo=None)
    factory = _session_factory()
    async with factory() as session:
        sp = ScheduledPost(
            id=str(uuid.uuid4()),
            brand_id=row.brand_id,
            asset_id=None,
            script_id=None,
            platform=row.platform,
            scheduled_for=now,
            status="done",
            veto_deadline=now,
            attempts=1,
            last_attempt_at=now,
        )
        session.add(sp)
        await session.flush()

        pp = PublishedPost(
            id=str(uuid.uuid4()),
            brand_id=row.brand_id,
            scheduled_post_id=sp.id,
            platform=row.platform,
            platform_post_id=platform_post_id,
            platform_url=post_url,
            published_at=now,
        )
        session.add(pp)
        await session.commit()


# ---------------------------------------------------------------------------
# Body augmentation — auto-append hashtags + github link when missing
# ---------------------------------------------------------------------------

def _augment_body(row: QueuedPost, cfg: dict, platform_key: str) -> str:
    """Append per-brand hashtags + repo link if the operator's body didn't
    include them. Idempotent: a body that already has the tags / link is
    returned unchanged.

    Hashtag source (in priority order):
      - cfg["platforms"][platform_key]["hashtags"]    — resolved-publisher-specific
      - cfg["default_hashtags"]                       — brand-wide

    Repo link source:
      - cfg["platforms"][platform_key]["default_repo_link"]
      - cfg["default_repo_link"]
    """
    body = (row.body or "").strip()
    if not body:
        return body

    block = (cfg.get("platforms", {}) or {}).get(platform_key) or {}
    hashtags = list(block.get("hashtags") or cfg.get("default_hashtags") or [])
    repo_link = block.get("default_repo_link") or cfg.get("default_repo_link") or ""

    additions: list[str] = []

    if repo_link:
        # Heuristic: only append if no link to the same domain is in the body.
        domain = repo_link.replace("https://", "").replace("http://", "").split("/")[0]
        if domain and domain not in body:
            additions.append(repo_link)

    if hashtags:
        # Detect any tag already present (case-insensitive).
        body_lower = body.lower()
        missing = [t for t in hashtags if t.lower() not in body_lower]
        if missing:
            additions.append(" ".join(missing))

    if not additions:
        return body

    # Two newlines if body ends with a paragraph; one newline if a single line.
    sep = "\n\n" if "\n\n" in body else "\n"
    return f"{body}{sep}{' '.join(additions)}"
