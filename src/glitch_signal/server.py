"""FastAPI application for Glitch Social Media Agent.

Endpoints:
  GET  /healthz                    — liveness
  POST /jobs/scout                 — trigger Scout node manually
  POST /jobs/assemble/{script_id}  — trigger VideoAssembler for a script

Approval / HITL surface lives in Discord now (glitch-discord-bot service +
in-process plugin). The Telegram bot was retired 2026-05-01.
"""
from __future__ import annotations

import asyncio
import html as _html_escape
import pathlib

import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlmodel import select

from glitch_signal import __version__
from glitch_signal.config import brand_env, brand_ids, settings
from glitch_signal.crypto import verify_state_token
from glitch_signal.db.models import ScheduledPost, VideoJob
from glitch_signal.db.session import _session_factory

log = structlog.get_logger(__name__)

app = FastAPI(
    title="Glitch Social Media Agent",
    version=__version__,
    description="Autonomous social video + ORM agent for Glitch Executor.",
)

# --- CF / origin hardening middleware (mirrors leaselens) --------------------
# Starlette runs the LAST-added middleware OUTERMOST, so add inner→outer:
# SecurityHeaders → CORS → TrustedHost → RateLimit → BodySizeLimit → OriginAuth (outer).
def _install_middleware() -> None:
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.middleware.trustedhost import TrustedHostMiddleware

    from glitch_signal.middleware import (
        BodySizeLimitMiddleware,
        OriginAuthMiddleware,
        RateLimitMiddleware,
        SecurityHeadersMiddleware,
    )

    s = settings()
    app.add_middleware(SecurityHeadersMiddleware)
    cors = [o.strip() for o in s.cors_allow_origins.split(",") if o.strip()]
    if cors:
        app.add_middleware(
            CORSMiddleware, allow_origins=cors, allow_methods=["*"], allow_headers=["*"]
        )
    hosts = [h.strip() for h in s.trusted_hosts.split(",") if h.strip()] or ["*"]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    if s.rate_limit_enabled:
        app.add_middleware(
            RateLimitMiddleware,
            per_ip=s.rate_limit_per_ip,
            window_s=s.rate_limit_window_s,
            global_limit=s.rate_limit_global,
        )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=s.max_request_body_bytes)
    app.add_middleware(
        OriginAuthMiddleware,
        secret=s.origin_shared_secret,
        header=s.origin_auth_header,
    )


_install_middleware()

_graph = None


@app.on_event("startup")
async def startup() -> None:
    global _graph

    # Build LangGraph
    from glitch_signal.agent.graph import get_graph
    _graph = get_graph()

    # Start scheduler
    from glitch_signal.scheduler.queue import start as start_scheduler
    start_scheduler()

    # Mesh Pilot brand-drift audit: log every locally-configured brand
    # against the hub `core.brands` table. Observation-only — never
    # blocks boot, even if the hub DB is unreachable.
    from glitch_signal.shared_context import audit_brand_registry_against_hub
    try:
        await audit_brand_registry_against_hub(brand_ids())
    except Exception as exc:  # pragma: no cover — pure diagnostic
        log.warning("signal.brand_drift audit_failed reason=%s", exc)

    log.info("glitch_signal.started", version=__version__, port=3111)


@app.on_event("shutdown")
async def shutdown() -> None:
    from glitch_signal.scheduler.queue import stop as stop_scheduler
    stop_scheduler()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/healthz")
async def healthz() -> dict:
    factory = _session_factory()
    async with factory() as session:
        pending_veto_r = await session.execute(
            select(ScheduledPost).where(ScheduledPost.status == "pending_veto")
        )
        queued_r = await session.execute(
            select(ScheduledPost).where(ScheduledPost.status == "queued")
        )
        dispatching_r = await session.execute(
            select(VideoJob).where(VideoJob.status == "dispatched")
        )

    return {
        "status": "ok",
        "service": "glitch-signal",
        "version": __version__,
        "dispatch_mode": settings().dispatch_mode,
        "queue": {
            "pending_veto": len(pending_veto_r.scalars().all()),
            "queued_to_publish": len(queued_r.scalars().all()),
            "shots_in_flight": len(dispatching_r.scalars().all()),
        },
    }


# ---------------------------------------------------------------------------
# Manual triggers
# ---------------------------------------------------------------------------

import hmac as _hmac


async def _require_jobs_auth(x_jobs_token: str = Header(default="")) -> None:
    """Gate the manual /jobs/* triggers (bug-2, 2026-06-10).

    These dispatch unbounded background LLM/video/Drive pipelines and are
    served on the public signal.meshpilot.app vhost. When JOBS_AUTH_TOKEN
    is set we require a matching x-jobs-token header (constant-time); when
    unset we log a warning and allow, so enabling auth is config-only and
    cannot break callers before the token is distributed.
    """
    # Per-brand (no global keys): reads <PREFIX>_JOBS_AUTH_TOKEN for the active
    # brand, e.g. GE_JOBS_AUTH_TOKEN. Gates /jobs/* and /internal/* — these have
    # side effects (publish, dispatch), so fail CLOSED: a missing token denies
    # rather than opening the control surface to the internet.
    expected = brand_env("JOBS_AUTH_TOKEN")
    if not expected:
        log.error("jobs.auth.misconfigured — <PREFIX>_JOBS_AUTH_TOKEN unset; denying")
        raise HTTPException(status_code=503, detail="jobs auth not configured")
    if not _hmac.compare_digest(x_jobs_token or "", expected):
        raise HTTPException(status_code=401, detail="invalid or missing x-jobs-token")


@app.post("/internal/facebook/test-post", dependencies=[Depends(_require_jobs_auth)])
async def internal_facebook_test_post(request: Request) -> dict:
    """Publish one post to a brand's Facebook Page (verification / manual).

    Body: {message?, brand_id?, link?, image_url?, video_url?}. Auth: x-jobs-token.
    Credentials resolve per-brand via brand_env — nothing is passed in the body.
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    _fb_brand = body.get("brand_id")
    if _fb_brand is not None and _fb_brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {_fb_brand!r}")
    from glitch_signal.platforms.facebook import publish_facebook

    post_id, permalink = await publish_facebook(
        brand_id=_fb_brand,
        message=body.get("message"),
        link=body.get("link"),
        image_url=body.get("image_url"),
        video_url=body.get("video_url"),
    )
    return {"ok": True, "post_id": post_id, "permalink": permalink}


@app.post("/internal/instagram/test-post", dependencies=[Depends(_require_jobs_auth)])
async def internal_instagram_test_post(request: Request) -> dict:
    """Publish one post to a brand's Instagram account (verification / manual).

    Body: {caption?, brand_id?, image_url?, video_url?}. Auth: x-jobs-token.
    Meta requires a PUBLIC media URL (e.g. a STORAGE-1 Supabase URL); IG needs
    image_url or video_url. Credentials resolve per-brand via brand_env.
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    _ig_brand = body.get("brand_id")
    if _ig_brand is not None and _ig_brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {_ig_brand!r}")
    from glitch_signal.platforms.instagram import publish_instagram

    media_id, permalink = await publish_instagram(
        brand_id=_ig_brand,
        caption=body.get("caption"),
        image_url=body.get("image_url"),
        video_url=body.get("video_url"),
    )
    return {"ok": True, "media_id": media_id, "permalink": permalink}


# ---------------------------------------------------------------------------
# Agent memory (AGENT-MEM) — per-brand facts + episodes with hybrid recall
# ---------------------------------------------------------------------------
@app.post("/internal/agent/remember", dependencies=[Depends(_require_jobs_auth)])
async def internal_agent_remember(request: Request) -> dict:
    """Store a fact or episode (auth: x-jobs-token).

    Body: {kind: fact|episode, content, brand?, key?, metadata?, importance?, source?}.
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    brand = body.get("brand", "glitch_executor")
    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    kind = body.get("kind")
    content = body.get("content")
    if kind not in ("fact", "episode") or not content:
        raise HTTPException(status_code=400, detail="kind (fact|episode) and content are required")
    from glitch_signal.agent.memory import remember

    m = await remember(
        brand, kind, content,
        key=body.get("key"), metadata=body.get("metadata"),
        importance=float(body.get("importance", 0.5)), source=body.get("source"),
    )
    return {"ok": True, "id": m.id, "kind": m.kind, "key": m.key}


@app.post("/internal/agent/recall", dependencies=[Depends(_require_jobs_auth)])
async def internal_agent_recall(request: Request) -> dict:
    """Recall top-k memories for a brand (auth: x-jobs-token).

    Body: {query, brand?, k?, kinds?} → ranked memories with fused/semantic/lexical scores.
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    brand = body.get("brand", "glitch_executor")
    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    query = body.get("query")
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    from glitch_signal.agent.memory import recall

    mems = await recall(brand, query, k=int(body.get("k", 8)), kinds=body.get("kinds"))
    return {
        "ok": True,
        "memories": [
            {
                "id": m.id, "kind": m.kind, "key": m.key, "content": m.content,
                "importance": m.importance, "score": m.score,
                "semantic": m.semantic, "lexical": m.lexical,
            }
            for m in mems
        ],
    }


async def _run_agent_bg(run_id: str, brand: str, goal: str, max_steps: int) -> None:
    from glitch_signal.agent.loop import run as agent_run
    from glitch_signal.agent.loop import runs as run_store
    try:
        res = await agent_run(brand, goal, max_steps=max_steps)
        await run_store.finish_run(run_id, res)
    except Exception as exc:  # noqa: BLE001
        await run_store.fail_run(run_id, str(exc))


@app.post("/internal/agent/run", dependencies=[Depends(_require_jobs_auth)])
async def internal_agent_run(request: Request) -> dict:
    """Start an agent-loop run for a goal (auth: x-jobs-token).

    Body: {goal, brand?, max_steps?}. The loop runs in the BACKGROUND (LLM round-trips exceed
    the edge request timeout), recalling memory, planning, and calling capability-tools — but
    publishing is DISABLED (AGENT-POLICY). Returns a `run_id`; poll GET /internal/agent/run/{id}.
    Run state is persisted to Postgres (agent_runs) so it is pollable across workers. Every run
    also writes an episode to the brand's memory.
    """
    import uuid as _uuid

    from glitch_signal.agent.loop import runs as run_store

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    brand = body.get("brand", "glitch_executor")
    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    goal = body.get("goal")
    if not goal:
        raise HTTPException(status_code=400, detail="goal is required")

    run_id = _uuid.uuid4().hex
    await run_store.create_run(run_id, brand, goal)  # row exists before we return
    asyncio.create_task(_run_agent_bg(run_id, brand, goal, int(body.get("max_steps", 5))))
    return {"ok": True, "run_id": run_id, "status": "running"}


@app.get("/internal/agent/run/{run_id}", dependencies=[Depends(_require_jobs_auth)])
async def internal_agent_run_status(run_id: str) -> dict:
    """Poll an agent run started via POST /internal/agent/run (reads the shared agent_runs table)."""
    from glitch_signal.agent.loop import runs as run_store

    rec = await run_store.get_run(run_id)
    if rec is None:
        return {"ok": True, "run_id": run_id, "status": "unknown"}
    return {"ok": True, **rec}


@app.post("/internal/agent/curate", dependencies=[Depends(_require_jobs_auth)])
async def internal_agent_curate(request: Request) -> dict:
    """Distill a brand's recent episodes into durable lessons (AGENT-LEARN; auth: x-jobs-token).

    Body: {brand?, limit?}. Reads uncurated episodes, asks the LLM to distill them into durable
    facts (upserted by a stable key), and marks those episodes curated. One LLM call — synchronous.
    """
    from glitch_signal.agent.learn import curate as agent_curate

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    brand = body.get("brand", "glitch_executor")
    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    res = await agent_curate(brand, limit=int(body.get("limit", 20)))
    return {"ok": True, "brand": brand, **res}


@app.get("/internal/agent/mcp/tools", dependencies=[Depends(_require_jobs_auth)])
async def internal_agent_mcp_tools(brand: str = "glitch_executor") -> dict:
    """List the MCP tools discovered from a brand's configured MCP servers (auth: x-jobs-token)."""
    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    from glitch_signal.agent.mcp import manager_for_brand

    mgr = await manager_for_brand(brand)
    async with mgr:
        tools = mgr.tool_descriptions()
    return {"ok": True, "brand": brand, "tools": tools, "count": len(tools)}


_HEYGEN_SEEN: set[str] = set()  # best-effort per-worker event-id dedup


@app.post("/webhooks/heygen")
async def heygen_webhook(request: Request):
    """Receive HeyGen webhook events (video finished/failed). Public (HeyGen calls it) but
    HMAC-verified: Heygen-Signature = hex HMAC-SHA256(raw body, HEYGEN_WEBHOOK_SECRET). We reject
    unverified/stale deliveries and dedup on Heygen-Event-Id, then ack 2xx fast.
    """
    import hashlib
    import hmac
    import json as _json
    import time as _time

    from fastapi import Response

    secret = (settings().heygen_webhook_secret or "").strip()
    raw = await request.body()
    sig = request.headers.get("Heygen-Signature", "")
    ts = request.headers.get("Heygen-Timestamp", "")
    eid = request.headers.get("Heygen-Event-Id", "")

    if not secret:  # fail closed — never trust an unverified event
        log.warning("heygen.webhook.no_secret")
        return Response(status_code=503)
    if not sig or not ts:
        return Response("missing signature headers", status_code=400)
    try:
        if abs(_time.time() - int(ts)) > 300:  # ~5 min replay window
            return Response("stale timestamp", status_code=400)
    except ValueError:
        return Response("bad timestamp", status_code=400)

    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return Response("bad signature", status_code=401)

    if eid and eid in _HEYGEN_SEEN:  # idempotency: HeyGen may redeliver on retry
        return Response(status_code=200)
    if eid:
        _HEYGEN_SEEN.add(eid)
        if len(_HEYGEN_SEEN) > 5000:
            _HEYGEN_SEEN.clear()

    try:
        event = _json.loads(raw or b"{}")
    except Exception:
        event = {}
    log.info("heygen.webhook", event_type=event.get("event_type"), event_id=eid,
             video_id=((event.get("event_data") or {}).get("video_id")))
    # Video completion is currently obtained by the HeyGen engine's own poll; this receiver
    # verifies + logs (and is the hook point for push-based completion handling later).
    return Response(status_code=200)


@app.post("/jobs/scout", dependencies=[Depends(_require_jobs_auth)])
async def job_scout(request: Request) -> dict:
    """Trigger a Scout run manually. Optionally pass {signal_id, platform} to run full pipeline."""
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass

    state = {
        "signal_id": body.get("signal_id", ""),
        "platform": body.get("platform", "youtube_shorts"),
        "retry_count": 0,
    }
    asyncio.create_task(_graph.ainvoke(state))
    return {"ok": True, "message": "Scout triggered in background"}


@app.post("/jobs/assemble/{script_id}", dependencies=[Depends(_require_jobs_auth)])
async def job_assemble(script_id: str) -> dict:
    """Manually trigger VideoAssembler for a script where all shots are done."""
    from glitch_signal.scheduler.queue import _trigger_assembler
    asyncio.create_task(_trigger_assembler(script_id))
    return {"ok": True, "script_id": script_id}


@app.post("/jobs/drive_scout", dependencies=[Depends(_require_jobs_auth)])
async def job_drive_scout(request: Request, brand: str) -> dict:
    """Trigger the drive_footage pipeline for a brand.

    Reads the brand's drive_folder_id from config, discovers new video files,
    downloads them, and runs drive_scout → caption_writer → publisher
    for the first new signal. Returns immediately after dispatching.
    """
    from glitch_signal.config import brand_config, brand_ids

    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")

    cfg = brand_config(brand)
    if cfg.get("content_source") != "drive_footage":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Brand {brand!r} content_source is {cfg.get('content_source')!r}; "
                "drive_scout only runs for brands with content_source=drive_footage"
            ),
        )

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass

    state = {
        "brand_id": brand,
        "content_source": "drive_footage",
        "signal_id": body.get("signal_id", ""),
        "platform": body.get("platform", "tiktok"),
        "retry_count": 0,
    }
    asyncio.create_task(_graph.ainvoke(state))
    return {
        "ok": True,
        "brand": brand,
        "message": "drive_scout dispatched in background",
    }


# --- YouTube OAuth (per-brand; a service account can't act on a channel) ---
@app.get("/oauth/youtube/start")
async def oauth_youtube_start(brand: str) -> RedirectResponse:
    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    from glitch_signal.oauth import youtube as yt_oauth

    url = yt_oauth.build_authorize_url(brand)
    log.info("oauth.youtube.start", brand=brand)
    return RedirectResponse(url=url, status_code=302)


@app.get("/oauth/youtube/callback")
async def oauth_youtube_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> HTMLResponse:
    if error:
        log.warning("oauth.youtube.callback_error", error=error, desc=error_description)
        return HTMLResponse(
            _html_page("YouTube authorization cancelled",
                       f"Error: <code>{_html_escape.escape(error or '')}</code>"),
            status_code=400,
        )
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    from glitch_signal.oauth import youtube as yt_oauth

    try:
        brand_id = yt_oauth.parse_state(state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid state: {exc}") from exc
    if brand_id not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand_id!r}")

    try:
        tokens = await yt_oauth.exchange_code_for_tokens(code, brand_id)
        await yt_oauth.persist_tokens(brand_id, tokens)
    except Exception as exc:
        log.exception("oauth.youtube.exchange_failed", brand=brand_id)
        return HTMLResponse(
            _html_page("YouTube connection failed",
                       f"Token exchange failed: <code>{_html_escape.escape(str(exc))}</code>"),
            status_code=502,
        )

    got_refresh = bool(tokens.get("refresh_token"))
    log.info("oauth.youtube.connected", brand=brand_id, has_refresh=got_refresh)
    return HTMLResponse(
        _html_page(
            "YouTube connected",
            f"Brand <code>{brand_id}</code> is connected to YouTube. "
            f"Refresh token stored: <code>{got_refresh}</code>. You can close this tab.",
        )
    )


@app.get("/internal/youtube/whoami", dependencies=[Depends(_require_jobs_auth)])
async def internal_youtube_whoami(brand: str = "glitch_executor") -> dict:
    """Verify the stored YouTube token reaches the channel (auth: x-jobs-token)."""
    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    from glitch_signal.oauth import youtube as yt_oauth

    token = await yt_oauth.get_fresh_access_token(brand)

    def _list_channels(access_token: str) -> list[dict]:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        yt = build("youtube", "v3", credentials=Credentials(token=access_token),
                   cache_discovery=False)
        r = yt.channels().list(part="snippet", mine=True).execute()
        return [{"id": it["id"], "title": it["snippet"]["title"]} for it in r.get("items", [])]

    channels = await asyncio.to_thread(_list_channels, token)
    return {"ok": True, "brand": brand, "channels": channels}


@app.get("/internal/buffer/channels", dependencies=[Depends(_require_jobs_auth)])
async def internal_buffer_channels(brand: str = "glitch_executor") -> dict:
    """List the brand's Buffer org + connected channels (auth: x-jobs-token)."""
    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    from glitch_signal.platforms import buffer

    return await buffer.list_channels(brand)


@app.post("/internal/buffer/test-post", dependencies=[Depends(_require_jobs_auth)])
async def internal_buffer_test_post(request: Request) -> dict:
    """Create a Buffer post to a service (auth: x-jobs-token).

    Body: {service?, text?, media_url?, mode?, brand?}. service = x/linkedin/tiktok/…
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    brand = body.get("brand", "glitch_executor")
    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    from glitch_signal.platforms import buffer

    post_id, status = await buffer.create_post(
        brand,
        body.get("service", "x"),
        text=body.get("text", ""),
        media_url=body.get("media_url"),
        mode=body.get("mode", "shareNow"),
    )
    return {"ok": True, "buffer_post_id": post_id, "status": status}


# ---------------------------------------------------------------------------
# Media generation (MEDIA-1) — deterministic recipe runner over MUapi
# ---------------------------------------------------------------------------
@app.get("/internal/media/recipes", dependencies=[Depends(_require_jobs_auth)])
async def internal_media_recipes() -> dict:
    """List the bundled generation recipes (auth: x-jobs-token)."""
    from glitch_signal.media.generation import list_recipes

    def _needs_llm(r) -> bool:
        return any(p.op == "llm" or p.prompt_mode == "llm" for p in r.phases)

    return {
        "ok": True,
        "recipes": [
            {
                "slug": r.slug,
                "kind": r.kind,
                "needs_composer": _needs_llm(r),
                "inputs": [
                    {"name": i.name, "required": i.required, "type": i.type} for i in r.inputs
                ],
                "description": r.description,
            }
            for r in list_recipes()
        ],
    }


@app.post("/internal/media/generate", dependencies=[Depends(_require_jobs_auth)])
async def internal_media_generate(request: Request) -> dict:
    """Run a media-generation recipe against MUapi (auth: x-jobs-token).

    Body: {recipe, inputs{...}, brand?}. Returns the finished hosted asset URL.
    Template-only recipes (e.g. muapi-product-video-ad-maker) run with no LLM;
    recipes whose prompts are LLM-authored return 422 until the composer is
    wired (MEDIA-2).
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    brand = body.get("brand", "glitch_executor")
    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    slug = body.get("recipe")
    if not slug:
        raise HTTPException(status_code=400, detail="recipe is required")

    from glitch_signal.media.generation import generate as media_generate, get_recipe
    from glitch_signal.media.generation.compose import llm_compose
    from glitch_signal.media.generation.engines.base import EngineError
    from glitch_signal.media.generation.spec import Brief

    try:
        get_recipe(slug)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    brief = Brief(brand_id=brand, recipe=slug, inputs=body.get("inputs", {}) or {})
    try:
        # engine: 'muapi' (default) or 'heygen'. The LLM composer handles prompt-authored recipes.
        asset = await media_generate(brief, engine=body.get("engine", "muapi"), compose=llm_compose)
    except EngineError as exc:
        msg = str(exc)
        code = 422 if "composer is required" in msg else 400
        raise HTTPException(status_code=code, detail=f"generation failed: {msg}")

    # Persist to the brand's Supabase bucket (muapi URLs expire). Opt out with store:false.
    if body.get("store", True):
        from glitch_signal.media.generation.storage import persist

        try:
            asset = await persist(asset, brand)
        except EngineError as exc:
            raise HTTPException(status_code=502, detail=f"generated but storage failed: {exc}")

    return {
        "ok": True,
        "url": asset.url,
        "kind": asset.kind,
        "engine": asset.engine,
        "recipe": asset.recipe,
        "source_url": asset.metadata.get("source_url"),
        "bucket": asset.metadata.get("bucket"),
    }


@app.post("/internal/media/ensure-bucket", dependencies=[Depends(_require_jobs_auth)])
async def internal_media_ensure_bucket(request: Request) -> dict:
    """Create the brand's media bucket if absent (auth: x-jobs-token). Body: {brand?}."""
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    brand = body.get("brand", "glitch_executor")
    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    from glitch_signal.media.generation.engines.base import EngineError
    from glitch_signal.media.generation.storage import bucket_for, ensure_bucket

    bucket = bucket_for(brand)
    try:
        await ensure_bucket(bucket)
    except EngineError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"ok": True, "brand": brand, "bucket": bucket}


# ---------------------------------------------------------------------------
# Media-serve — HMAC-signed short-lived URL for vendor fetch
# ---------------------------------------------------------------------------
# Used by platforms/zernio.py. The token is an HMAC-signed JSON payload
# that encodes the exact filesystem path + a 1-hour TTL, so a token
# issued for file A can't be used to fetch file B, and leaked tokens
# expire quickly. Only paths under VIDEO_STORAGE_PATH are served — the
# endpoint refuses absolute paths outside that tree.

_MEDIA_KIND = "media"



def _resolve_media_path(token: str) -> pathlib.Path:
    """Validate signed media token and return the on-disk path.

    Shared by GET and HEAD handlers. Raises HTTPException on any failure
    so both verbs return identical status codes to the caller.
    """
    try:
        payload = verify_state_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=f"Invalid media token: {exc}") from exc

    if payload.get("k") != _MEDIA_KIND:
        raise HTTPException(status_code=403, detail="Token is not a media token")

    raw_path = payload.get("p")
    if not raw_path:
        raise HTTPException(status_code=400, detail="Token missing path")

    # Resolve + confinement check: only paths under VIDEO_STORAGE_PATH are
    # served. Prevents traversal even if a token is crafted maliciously.
    path = pathlib.Path(raw_path).resolve()
    storage_root = pathlib.Path(settings().video_storage_path).resolve()
    try:
        path.relative_to(storage_root)
    except ValueError as exc:
        log.warning("media.fetch.path_escape_attempt", path=str(path))
        raise HTTPException(status_code=403, detail="Path outside media root") from exc

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Media not found")

    return path


@app.get("/media/fetch")
async def media_fetch(token: str) -> FileResponse:
    path = _resolve_media_path(token)
    log.info("media.fetch.served", path=str(path), bytes=path.stat().st_size)
    return FileResponse(
        path=str(path),
        media_type="video/mp4",
        filename=path.name,
    )


@app.head("/media/fetch")
async def media_fetch_head(token: str) -> Response:
    """HEAD pre-flight for vendors that validate media URLs before ingest.

    Buffer (and likely other partners) issue a HEAD request to `/media/fetch`
    before accepting the URL into a post. A 405 on HEAD gets reported back
    as "URL not accessible" and the post is rejected. This mirrors the GET
    validation (signed-token check + path confinement) without streaming
    bytes — just returns the headers the vendor needs to proceed.
    """
    path = _resolve_media_path(token)
    size = path.stat().st_size
    return Response(
        status_code=200,
        headers={
            "Content-Type": "video/mp4",
            "Content-Length": str(size),
            "Accept-Ranges": "bytes",
        },
    )


def _html_page(title: str, body_html: str) -> str:
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{title}</title>"
        "<style>body{font-family:ui-sans-serif,system-ui;background:#0a0a0f;color:#e6e6e6;"
        "display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}"
        ".card{max-width:560px;padding:32px;border:1px solid #222;border-radius:12px;"
        "background:#111}h1{margin:0 0 12px;font-size:18px;color:#00ff88}"
        "code{background:#222;padding:2px 6px;border-radius:4px}</style>"
        f"</head><body><div class=\"card\"><h1>{title}</h1><p>{body_html}</p></div></body></html>"
    )
