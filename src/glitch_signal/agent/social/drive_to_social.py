"""Post what already exists: one Drive video a day to Instagram and TikTok (DRIVE-TO-SOCIAL).

A brand whose content is NOT generated. The videos are finished and sitting in a Drive folder; the
agent's whole job is to post each one exactly once, oldest first, with a short caption in the
brand's voice. No ideation, no media generation, no A/B matrix — the `social_campaign` pipeline is
the wrong tool, and this is deliberately a much smaller one.

It composes four things that already existed: the Drive client (list + download), the media store
(a public URL both platforms can ingest from — Drive links are not fetchable by Meta or Buffer), the
Instagram Reels publisher, and Buffer's TikTok channel. The orchestration between them was part of
the legacy pipeline retired on 2026-09-02; this is its replacement, without the sheet tracker.

**Per-platform outcomes are independent.** IG and TikTok fail separately, and a TikTok outage must
not cause the IG post to be repeated tomorrow. Each platform's result is its own column, and the
file counts as consumed the moment EITHER succeeds — a file with one platform failed is retried on
that platform only, never re-posted where it already landed.

Brand-neutral: the folder, the voice, the guardrails and the platforms all come from the brand.
"""
from __future__ import annotations

import pathlib
import re
import tempfile
from typing import Any

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)

_MAX_CAPTION = 2000            # IG's limit; TikTok's is 2200, so the smaller governs.
_MAX_BYTES = 300 * 1024 * 1024 # Reels ingest tops out around here; refuse rather than time out.

_INSERT = text(
    "INSERT INTO drive_post (brand_id, file_id, file_name, media_url, caption, ig_media_id, "
    "  ig_error, tiktok_post_id, tiktok_error) "
    "VALUES (:b, :f, :n, :u, :c, :ig, :ige, :tt, :tte) "
    "ON CONFLICT (brand_id, file_id) DO UPDATE SET "
    "  media_url = COALESCE(EXCLUDED.media_url, drive_post.media_url), "
    "  caption = COALESCE(EXCLUDED.caption, drive_post.caption), "
    "  ig_media_id = COALESCE(EXCLUDED.ig_media_id, drive_post.ig_media_id), "
    "  ig_error = EXCLUDED.ig_error, "
    "  tiktok_post_id = COALESCE(EXCLUDED.tiktok_post_id, drive_post.tiktok_post_id), "
    "  tiktok_error = EXCLUDED.tiktok_error, posted_at = now()"
)
_DONE = text("SELECT file_id, ig_media_id, tiktok_post_id FROM drive_post WHERE brand_id = :b")


def _engine_or(engine: Any):
    from glitch_signal.db.session import _engine

    return engine or _engine()


def _on() -> bool:
    from glitch_signal.config import settings

    s = settings()
    return bool(getattr(s, "agent_social_enabled", False) and getattr(s, "agent_publish_enabled", False))


async def _posted(brand_id: str, *, engine: Any = None) -> dict[str, dict]:
    async with _engine_or(engine).connect() as conn:
        rows = (await conn.execute(_DONE, {"b": brand_id})).mappings().all()
    return {r["file_id"]: dict(r) for r in rows}


def pick_next(files: list[Any], posted: dict[str, dict]) -> tuple[Any | None, dict[str, bool]]:
    """Oldest file that still has a platform outstanding, and which platforms it needs.

    Sorted by name — a folder of dated or numbered files posts in the order the operator laid it
    out, which is the only ordering they can see and control.
    """
    for f in sorted(files, key=lambda x: x.name.lower()):
        rec = posted.get(f.id, {})
        need = {"instagram": not rec.get("ig_media_id"), "tiktok": not rec.get("tiktok_post_id")}
        if any(need.values()):
            return f, need
    return None, {}


def _hard_stops(brand_id: str) -> list[str]:
    from glitch_signal.config import brand_config

    return [p.lower() for p in (brand_config(brand_id).get("orm_guardrails") or {})
            .get("hard_stop_phrases", [])]


def scrub(caption: str, hard_stops: list[str]) -> str:
    """A caption that trips a brand's hard-stop phrase is not posted — it is shortened past it.

    The same phrases the ORM lane refuses to say in a reply, the caption must not say in a post:
    for a pet-health brand that is "cures", "treats", "vet recommended". Rather than fail the whole
    post over a word, cut at the sentence that contains it; if nothing safe remains, fall back to
    the filename-derived caption the caller supplies.
    """
    keep = []
    for sentence in re.split(r"(?<=[.!?])\s+", caption.strip()):
        low = sentence.lower()
        if any(h in low for h in hard_stops):
            break
        keep.append(sentence)
    return " ".join(keep).strip()


def caption_from_name(name: str) -> str:
    """The zero-model fallback: the filename, cleaned. `2026-09-01_turmeric-chew-closeup.mp4` →
    `Turmeric chew closeup`."""
    stem = re.sub(r"\.[a-z0-9]{2,4}$", "", name, flags=re.I)
    stem = re.sub(r"^[\d_\-\s]+", "", stem)
    stem = re.sub(r"[_\-]+", " ", stem).strip()
    return (stem[:1].upper() + stem[1:]) if stem else "New from the team"


_CAPTION_PROMPT = """Write ONE short social caption (max 2 sentences, no hashtags) for a video a
brand is posting to Instagram and TikTok.

BRAND: {name}
VOICE: {voice}
VIDEO FILENAME: {filename}

You have NOT seen the video. Do not describe what happens in it, who is in it, or how a product
is used — you would be making it up. If the filename plainly names a product or theme, you may
lean on that; otherwise write a line about the brand's everyday care that fits any clip.
Rules: no health or outcome claims of any kind, no superlatives, no emoji walls (one is fine),
no "link in bio", no questions to the audience. Sound like a person who owns the product, not a
marketer. Reply with the caption only."""


def _strip_hashtags(text: str) -> str:
    """Drop any hashtags the model added anyway — the brand's own set is appended once."""
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
    return re.sub(r"\s#\w+", "", "\n".join(lines)).strip()


async def write_caption(brand_id: str, filename: str, *, complete: Any = None) -> str:
    from glitch_signal.config import brand_config

    cfg = brand_config(brand_id)
    if complete is None:
        from glitch_signal.agent.loop import llm as agent_llm

        async def complete(prompt: str) -> str:
            return await agent_llm.complete_messages(
                [{"role": "user", "content": prompt}], tier="moderate", max_tokens=1200,
                timeout_s=60)

    raw = ""
    try:
        raw = await complete(_CAPTION_PROMPT.format(
            name=cfg.get("display_name") or brand_id,
            voice=(cfg.get("brand") or {}).get("voice", ""), filename=filename))
    except Exception as exc:  # noqa: BLE001 — a caption is not worth failing the post
        log.warning("drive_to_social.caption_failed", error=str(exc)[:160])
    hashtags = " ".join(f"#{h.lstrip('#')}" for h in (cfg.get("default_hashtags") or [])[:5])
    body = scrub(_strip_hashtags(raw or ""), _hard_stops(brand_id)) or caption_from_name(filename)
    return f"{body}\n\n{hashtags}".strip()[:_MAX_CAPTION]


async def run(brand_id: str, args: dict | None = None, *, engine: Any = None,
              deps: dict | None = None) -> dict:
    """Post the next unposted Drive video to every platform that still needs it."""
    from glitch_signal.config import brand_env

    args = args or {}
    d = deps or {}
    dry = bool(args.get("dry_run"))
    if not dry and not _on():
        return {"skipped": "social_or_publish_disabled"}

    folder = args.get("folder_id") or brand_env("DRIVE_FOLDER_ID", brand_id)
    if not folder:
        return {"skipped": "no_folder", "detail": f"set <PREFIX>_DRIVE_FOLDER_ID for {brand_id}"}

    list_files = d.get("list_files")
    if list_files is None:
        from glitch_signal.integrations.google_drive import list_video_files as list_files
    files = await list_files(folder, brand_id)
    if not files:
        return {"skipped": "folder_empty", "folder": folder}

    posted = await _posted(brand_id, engine=engine)
    file, need = pick_next(files, posted)
    if file is None:
        return {"skipped": "all_posted", "files": len(files)}
    if file.size and file.size > _MAX_BYTES:
        return {"skipped": "file_too_large", "file": file.name, "bytes": file.size}

    caption = (posted.get(file.id) or {}).get("caption") or await write_caption(
        brand_id, file.name, complete=d.get("complete"))
    if dry:
        return {"dry_run": True, "would_post": file.name, "platforms": [k for k, v in need.items() if v],
                "caption": caption}

    # A public copy: neither Meta nor Buffer can fetch from Drive.
    media_url = (posted.get(file.id) or {}).get("media_url")
    if not media_url:
        download = d.get("download") or _download
        upload = d.get("upload") or _upload
        with tempfile.TemporaryDirectory() as tmp:
            dest = pathlib.Path(tmp) / file.name
            await download(file.id, dest, brand_id)
            media_url = await upload(dest.read_bytes(), brand_id, ext=dest.suffix.lstrip(".") or "mp4",
                                     content_type=file.mime_type or "video/mp4")

    out = {"ran": "drive_to_social", "file": file.name, "media_url": media_url,
           "instagram": None, "tiktok": None}
    ig_id = ig_err = tt_id = tt_err = None
    if need["instagram"]:
        try:
            publish_ig = d.get("publish_instagram") or _publish_ig
            ig_id, permalink = await publish_ig(brand_id=brand_id, caption=caption, video_url=media_url)
            out["instagram"] = permalink or ig_id
        except Exception as exc:  # noqa: BLE001 — the other platform still gets its turn
            ig_err = str(exc)[:300]
            out["instagram_error"] = ig_err
            log.warning("drive_to_social.instagram_failed", file=file.name, error=ig_err)
    if need["tiktok"]:
        try:
            create_post = d.get("create_post") or _create_tiktok
            tt_id, status = await create_post(brand_id, "tiktok", text=caption, media_url=media_url,
                                              idem_key=f"drive:{brand_id}:{file.id}:tiktok")
            out["tiktok"] = f"{tt_id} ({status})"
        except Exception as exc:  # noqa: BLE001
            tt_err = str(exc)[:300]
            out["tiktok_error"] = tt_err
            log.warning("drive_to_social.tiktok_failed", file=file.name, error=tt_err)

    async with _engine_or(engine).begin() as conn:
        await conn.execute(_INSERT, {"b": brand_id, "f": file.id, "n": file.name, "u": media_url,
                                     "c": caption, "ig": ig_id, "ige": ig_err, "tt": tt_id, "tte": tt_err})
    log.info("drive_to_social.posted", brand_id=brand_id, file=file.name,
             instagram=bool(ig_id), tiktok=bool(tt_id))
    return out


async def _download(file_id: str, dest: pathlib.Path, brand_id: str | None = None) -> int:
    from glitch_signal.integrations.google_drive import download_file

    return await download_file(file_id, dest, brand_id)


async def _upload(data: bytes, brand_id: str, **kw: Any) -> str:
    from glitch_signal.media.generation.storage import upload_bytes

    return await upload_bytes(data, brand_id, prefix="drive", **kw)


async def _publish_ig(**kw: Any):
    from glitch_signal.platforms.instagram import publish_instagram

    return await publish_instagram(**kw)


async def _create_tiktok(brand_id: str, service: str, **kw: Any):
    from glitch_signal.platforms.buffer import create_post

    return await create_post(brand_id, service, **kw)
