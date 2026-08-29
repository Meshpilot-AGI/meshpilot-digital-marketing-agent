"""Buffer publisher — GraphQL-backed TikTok publishing.

Why a third vendor on top of Upload-Post and Zernio:

  Upload-Post's TikTok pipeline silently triggers TikTok's synthetic-media
  audio mute for AI-generated voice content. The same files post cleanly
  on Upload-Post → Instagram and on Buffer → TikTok. Direct-to-origin
  evidence: diagnostic posts on 2026-04-19 where the same byte-identical
  file had muted audio via Upload-Post and full audio via Buffer to the
  same `@glitchexec` TikTok channel.

  Buffer's server forwards our file URL to TikTok's Content Posting API
  *without* server-side re-muxing. The `video_was_transcoded: false`
  on Upload-Post combined with the mute asymmetry points to their
  remux pipeline as the trigger; Buffer avoids this by staying hands-off.

Scope:
  Today this publisher is TikTok-only. Buffer supports Instagram / YouTube
  / LinkedIn / X etc., but their IG path passes files straight through
  (no normalization), which means our 20 Mbps / 100+ MB reels exceed
  Instagram Graph API native limits — Upload-Post's re-encoding is
  actually useful there. Add per-platform coverage later if we hit
  similar issues on non-TikTok targets.

Platform-key convention mirrors zernio_* and upload_post_*:
  buffer_tiktok, buffer_instagram, buffer_youtube, …

Per-brand config lives under platforms.buffer_<target>:
  - enabled: true
  - channel_id: Buffer channel id (get from `channels(input: {organizationId})`)
  - organization_id: Buffer organization id

Webhook-driven finalization:
  createPost returns a Buffer post id immediately with status=sending.
  Buffer uploads to the target platform asynchronously (~30s–3min) and
  status flips to sent/failed. We return a `webhook_pending:<post_id>`
  sentinel so publisher.py flips ScheduledPost to `awaiting_webhook`.
  The reconcile sweep in scheduler/queue.py polls Buffer's post(input)
  query and finalizes when status is sent/failed.

  Buffer has no webhooks on free/basic tiers as of 2026-04. If that
  changes, wire a webhook handler — the plumbing is the same as Upload-
  Post's.

Rate limits:
  Buffer enforces a 24-hour per-client quota on GraphQL requests.
  Observed error shape:
    {"errors":[{"extensions":{"code":"RATE_LIMIT_EXCEEDED","window":"24h"}}]}
  Scale considerations for the reconcile sweep: poll at a slow cadence
  (minutes, not seconds) and batch where possible.

DISPATCH_MODE=dry_run short-circuits without calling the API.
"""
from __future__ import annotations

import pathlib
import uuid

import httpx
import structlog

from glitch_signal.config import brand_config, brand_env, settings
from glitch_signal.crypto import make_state_token
from glitch_signal.db.models import ContentScript
from glitch_signal.db.session import _session_factory

log = structlog.get_logger(__name__)

_GRAPHQL_URL = "https://api.buffer.com"

# TTL for the signed URL we hand Buffer. Their ingest worker HEAD-checks
# the URL immediately on createPost, then GETs it during upload to the
# target platform (seconds to a few minutes later). 1 hour is a generous
# ceiling.
_MEDIA_URL_TTL_S = 60 * 60

# Sentinel prefix shared with upload_post.py. publisher.py treats both
# vendors' pending posts uniformly — it stashes the post id in
# scheduled_post.vendor_request_id and flips status to awaiting_webhook.
# The reconcile sweep then routes by sp.platform prefix to the right vendor.
_WEBHOOK_PENDING_PREFIX = "webhook_pending:"

# Short timeout for the submission call. Buffer accepts createPost in
# milliseconds even for large videos — they just register the URL and
# hand off to a worker. A long deadline here means a stuck TCP session
# blocks the scheduler tick.
_SUBMIT_TIMEOUT_S = 30.0
_POLL_TIMEOUT_S = 15.0


# ---------------------------------------------------------------------------
# Platform-key mapping
# ---------------------------------------------------------------------------

_PLATFORM_MAP = {
    "buffer_tiktok":    "tiktok",
    "buffer_instagram": "instagram",
    "buffer_youtube":   "youtube",
    "buffer_linkedin":  "linkedin",
    "buffer_facebook":  "facebook",
    "buffer_x":         "x",
    "buffer_threads":   "threads",
    "buffer_pinterest": "pinterest",
    "buffer_bluesky":   "bluesky",
}


def is_webhook_pending(token: str) -> bool:
    """True if publish() returned a pending sentinel rather than a finalized id."""
    return isinstance(token, str) and token.startswith(_WEBHOOK_PENDING_PREFIX)


def extract_post_id(token: str) -> str:
    """Return the Buffer post id from a pending sentinel."""
    if not is_webhook_pending(token):
        raise ValueError(f"Not a webhook-pending sentinel: {token!r}")
    return token[len(_WEBHOOK_PENDING_PREFIX):]


# ---------------------------------------------------------------------------
# Per-brand token + GraphQL helpers + generic create_post (text and/or media)
# ---------------------------------------------------------------------------

# Buffer reports X as either "x" or "twitter" depending on when the channel
# was connected — treat them as the same service.
_SERVICE_ALIASES = {"x": {"x", "twitter"}, "twitter": {"x", "twitter"}}

_CREATE_POST_QUERY = (
    "mutation($input: CreatePostInput!) { createPost(input: $input) {"
    " __typename"
    " ... on PostActionSuccess { post { id status } }"
    " ... on InvalidInputError { message }"
    " ... on UnauthorizedError { message }"
    " ... on LimitReachedError { message }"
    " ... on NotFoundError { message }"
    " ... on UnexpectedError { message }"
    " ... on RestProxyError { message } } }"
)


def _buffer_token(brand_id: str | None) -> str:
    token = brand_env("BUFFER_API_KEY", brand_id)
    if not token:
        raise RuntimeError(f"buffer: <PREFIX>_BUFFER_API_KEY not set for brand={brand_id!r}")
    return token


async def _graphql(token: str, query: str, variables: dict | None = None,
                   *, timeout: float = _SUBMIT_TIMEOUT_S) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            _GRAPHQL_URL,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"query": query, "variables": variables or {}},
        )
    resp.raise_for_status()
    body = resp.json()
    if body.get("errors"):
        raise RuntimeError(f"Buffer GraphQL error: {body['errors']}")
    return body.get("data") or {}


async def list_channels(brand_id: str) -> dict:
    """{organization_id, organizations, channels:[{id,name,service}]} for the brand."""
    token = _buffer_token(brand_id)
    acct = await _graphql(token, "query { account { id email organizations { id name } } }")
    orgs = (acct.get("account") or {}).get("organizations") or []
    if not orgs:
        raise RuntimeError("buffer: account has no organizations")
    org_id = orgs[0]["id"]
    data = await _graphql(
        token,
        "query($input: ChannelsInput!) { channels(input: $input) { id name service } }",
        {"input": {"organizationId": org_id}},
    )
    return {"organization_id": org_id, "organizations": orgs, "channels": data.get("channels") or []}


async def _channel_id_for_service(brand_id: str, service: str) -> str:
    want = _SERVICE_ALIASES.get(service.lower(), {service.lower()})
    channels = (await list_channels(brand_id))["channels"]
    for ch in channels:
        if (ch.get("service") or "").lower() in want:
            return ch["id"]
    raise RuntimeError(
        f"buffer: no {service!r} channel for brand={brand_id!r} "
        f"(connected: {[c.get('service') for c in channels]})"
    )


async def create_post(
    brand_id: str,
    service: str,
    *,
    text: str,
    media_url: str | None = None,
    mode: str = "shareNow",
) -> tuple[str, str | None]:
    """Create a Buffer post to `service` (x / linkedin / tiktok / …), text and/or
    media. Returns (buffer_post_id, status). Buffer publishes asynchronously;
    use `poll_status_for_post` for the final externalLink."""
    token = _buffer_token(brand_id)
    channel_id = await _channel_id_for_service(brand_id, service)
    inp: dict = {
        "channelId": channel_id,
        "schedulingType": "automatic",
        "mode": mode,
        "text": text or "",
        "source": "glitch-social-media-agent",
    }
    if media_url:
        from urllib.parse import urlsplit
        # Match on the PATH, not the whole URL — a signed URL like
        # /media/fetch?token=… or clip.mp4?sig=… has a query string that would
        # otherwise defeat an endswith() check and mis-file a video as a photo.
        ext = urlsplit(media_url).path.lower()
        key = "videos" if ext.endswith((".mp4", ".mov", ".webm", ".m4v")) else "photos"
        inp["assets"] = {key: [{"url": media_url}]}
    data = await _graphql(token, _CREATE_POST_QUERY, {"input": inp})
    payload = data.get("createPost") or {}
    if payload.get("__typename") != "PostActionSuccess":
        raise RuntimeError(
            f"Buffer createPost {payload.get('__typename')}: {payload.get('message') or 'no detail'}"
        )
    post = payload.get("post") or {}
    log.info("buffer.create_post.ok", brand_id=brand_id, service=service,
             channel_id=channel_id, post_id=post.get("id"), status=post.get("status"))
    return post.get("id"), post.get("status")


# ---------------------------------------------------------------------------
# Publish entry point
# ---------------------------------------------------------------------------

async def publish(
    platform: str,
    file_path: str,
    script_id: str,
    brand_id: str | None = None,
    attempts: int = 1,
) -> tuple[str, str | None]:
    """Publish a video via Buffer. Returns (sentinel, None).

    The first return is a `webhook_pending:<buffer_post_id>` token; the
    reconcile sweep pulls the real per-platform post URL later via
    `poll_status_for_post`. `attempts` is currently unused — Buffer
    dedupes server-side on its own post ids, so our scheduler's retry
    with the same ScheduledPost never produces a duplicate createPost
    on Buffer's side provided we cache the post id we got back.
    """
    s = settings()

    if s.is_dry_run:
        fake_id = f"buffer-dry-{uuid.uuid4().hex[:10]}"
        log.info(
            "buffer.publish.dry_run",
            publish_id=fake_id,
            file_path=file_path,
            brand_id=brand_id,
            platform=platform,
        )
        return fake_id, None

    if not brand_id:
        raise ValueError("buffer.publish: brand_id is required for live publish")
    token = _buffer_token(brand_id)

    target = _PLATFORM_MAP.get(platform)
    if not target:
        raise ValueError(f"buffer.publish: unknown platform key {platform!r}")

    cfg_block = (brand_config(brand_id).get("platforms", {}).get(platform, {}) or {})
    channel_id = cfg_block.get("channel_id")
    organization_id = cfg_block.get("organization_id")
    if not channel_id:
        raise RuntimeError(
            f"buffer.publish: brand={brand_id!r} is missing "
            f"platforms.{platform}.channel_id — get it via Buffer's "
            f"channels(input:{{organizationId}}) query and add to the brand config"
        )
    if not organization_id:
        raise RuntimeError(
            f"buffer.publish: brand={brand_id!r} is missing "
            f"platforms.{platform}.organization_id"
        )

    path = pathlib.Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"buffer.publish: file missing: {file_path}")

    caption = await _read_caption(script_id)
    video_url = _build_signed_media_url(path)

    log.info(
        "buffer.publish.media_url_issued",
        brand_id=brand_id,
        file_path=str(path),
        media_url_host=video_url.split("/")[2] if "://" in video_url else video_url,
        target=target,
        channel_id=channel_id,
    )

    variables = {
        "input": {
            "channelId": channel_id,
            "schedulingType": "automatic",
            "mode": "shareNow",
            "text": caption or "",
            "assets": {"videos": [{"url": video_url}]},
            "source": "glitch-social-media-agent",
        }
    }
    query = (
        "mutation($input: CreatePostInput!) {"
        "  createPost(input: $input) {"
        "    __typename"
        "    ... on PostActionSuccess { post { id status } }"
        "    ... on InvalidInputError { message }"
        "    ... on UnauthorizedError { message }"
        "    ... on LimitReachedError { message }"
        "    ... on NotFoundError { message }"
        "    ... on UnexpectedError { message }"
        "    ... on RestProxyError { message }"
        "  }"
        "}"
    )

    async with httpx.AsyncClient(timeout=_SUBMIT_TIMEOUT_S) as client:
        resp = await client.post(
            _GRAPHQL_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"query": query, "variables": variables},
        )
    resp.raise_for_status()
    body = resp.json()

    if body.get("errors"):
        raise RuntimeError(f"Buffer createPost failed: {body['errors']}")

    payload = (body.get("data") or {}).get("createPost") or {}
    typename = payload.get("__typename")
    if typename != "PostActionSuccess":
        msg = payload.get("message") or "no detail"
        raise RuntimeError(f"Buffer createPost returned {typename}: {msg}")

    post = payload.get("post") or {}
    post_id = post.get("id")
    status = post.get("status")
    if not post_id:
        raise RuntimeError(f"Buffer createPost succeeded but no post.id in response: {payload}")

    log.info(
        "buffer.publish.submitted",
        brand_id=brand_id,
        target=target,
        channel_id=channel_id,
        buffer_post_id=post_id,
        buffer_status=status,
    )
    return f"{_WEBHOOK_PENDING_PREFIX}{post_id}", None


# ---------------------------------------------------------------------------
# Reconciliation — polled by scheduler/queue.py for awaiting_webhook rows
# ---------------------------------------------------------------------------

async def poll_status_for_post(
    buffer_post_id: str, organization_id: str | None = None, brand_id: str | None = None
) -> tuple[str | None, str | None]:
    """Return (platform_post_id, share_url) for a Buffer post, or (None, None).

    Called by the reconcile sweep. A None return means "still in flight,
    try again next tick". A RuntimeError means "Buffer rejected the post"
    and caller should mark ScheduledPost as failed.

    Buffer's Post type exposes `status` (sending/sent/failed/…) and
    `externalLink` (the native TikTok URL once published). We don't get
    the per-platform post id separately — the externalLink carries it
    in the path, which is enough for sheet tracking and observability.

    `organization_id` is accepted for API symmetry with the brand-config
    caller but is NOT part of Buffer's PostInput schema — the post id
    alone is the key. The param stays to keep the scheduler callsite
    uniform; remove once we're confident no branch relies on it.
    """
    del organization_id  # retained for caller symmetry, unused in query

    token = _buffer_token(brand_id)

    query = (
        "query($input: PostInput!) {"
        "  post(input: $input) {"
        "    id status externalLink channelService"
        "  }"
        "}"
    )
    # Buffer's PostInput is {id} only — organizationId is not in its schema.
    variables = {"input": {"id": buffer_post_id}}

    async with httpx.AsyncClient(timeout=_POLL_TIMEOUT_S) as client:
        resp = await client.post(
            _GRAPHQL_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"query": query, "variables": variables},
        )
    resp.raise_for_status()
    body = resp.json()

    if body.get("errors"):
        # Rate limit errors bubble up here. The reconcile caller treats
        # RuntimeError as "don't mark failed yet, retry next tick" — let
        # the exception propagate with enough detail for the log line.
        raise RuntimeError(f"Buffer post() query failed: {body['errors']}")

    post = (body.get("data") or {}).get("post") or {}
    status = post.get("status")
    external = post.get("externalLink")

    if status == "sent":
        return buffer_post_id, external
    if status in ("failed", "error"):
        raise RuntimeError(
            f"Buffer post {buffer_post_id!r} reported status={status!r}"
        )
    # sending / processing / unknown → still in flight
    return None, None


# ---------------------------------------------------------------------------
# Caption extraction — reads ContentScript.script_body by script_id
# ---------------------------------------------------------------------------

async def _read_caption(script_id: str | None) -> str:
    """Return the caption body for the post, or empty string if not found.

    Mirrors upload_post._read_caption but returns just the caption — Buffer
    only has one text field on createPost (no title/description split),
    so hashtag extraction + title derivation aren't needed here.
    """
    if not script_id:
        return ""
    factory = _session_factory()
    async with factory() as session:
        cs = await session.get(ContentScript, script_id)
    return (cs.script_body if cs else "").strip()


# ---------------------------------------------------------------------------
# Signed media URL (shares scheme with upload_post.py / zernio.py)
# ---------------------------------------------------------------------------

def _build_signed_media_url(local_path: pathlib.Path) -> str:
    """Return an HMAC-signed public URL served by /media/fetch.

    Buffer validates the URL with a HEAD request before accepting the
    post (see server.py::media_fetch_head). The GET happens later when
    Buffer's worker uploads to TikTok.
    """
    s = settings()
    token = make_state_token(
        {"p": str(local_path.resolve()), "k": "media"},
        ttl_s=_MEDIA_URL_TTL_S,
    )
    base = s.media_public_base_url.rstrip("/")
    return f"{base}/media/fetch?token={token}"
