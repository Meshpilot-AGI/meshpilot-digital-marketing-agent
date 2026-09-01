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
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlmodel import select

from glitch_signal import __version__
from glitch_signal.config import brand_env, brand_ids, settings
from glitch_signal.crypto import verify_state_token
from glitch_signal.db.models import ScheduledPost, VideoJob
from glitch_signal.db.session import _session_factory

log = structlog.get_logger(__name__)

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifecycle (replaces the deprecated @app.on_event startup/shutdown). `_on_startup` /
    `_on_shutdown` are defined below — resolved at run time, not import time."""
    await _on_startup()
    try:
        yield
    finally:
        await _on_shutdown()


# Interactive docs expose the entire route map (incl. /internal + /jobs shapes). Keep them OFF in
# production; enable only when ENABLE_API_DOCS=true (local/dev). openapi_url gates /docs + /redoc too.
_docs_on = bool(getattr(settings(), "enable_api_docs", False))
app = FastAPI(
    title="Glitch Social Media Agent",
    version=__version__,
    description="Autonomous social video + ORM agent for Glitch Executor.",
    lifespan=lifespan,
    docs_url="/docs" if _docs_on else None,
    redoc_url="/redoc" if _docs_on else None,
    openapi_url="/openapi.json" if _docs_on else None,
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
            shared=s.rate_limit_shared,   # #98: Postgres-backed fleet-wide limiter when enabled
        )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=s.max_request_body_bytes)
    app.add_middleware(
        OriginAuthMiddleware,
        secret=s.origin_shared_secret,
        header=s.origin_auth_header,
    )


_install_middleware()

_graph = None


_OAUTH_KEEPALIVE_PROVIDERS = ("heygen",)
_OAUTH_KEEPALIVE_INTERVAL_S = 1800   # every 30 min
_OAUTH_KEEPALIVE_MIN_REMAINING_S = 2000  # refresh when < ~33 min of a ~60 min token remains


async def _oauth_keepalive() -> None:
    """Periodically refresh OAuth-backed MCP tokens so the rotating refresh chain never goes stale.
    Refresh-on-demand (get_bearer) covers active use; this covers long idle. Fail-soft."""
    from glitch_signal.agent.mcp.oauth import get_bearer

    while True:
        await asyncio.sleep(_OAUTH_KEEPALIVE_INTERVAL_S)
        for provider in _OAUTH_KEEPALIVE_PROVIDERS:
            try:
                await get_bearer(provider, min_remaining_s=_OAUTH_KEEPALIVE_MIN_REMAINING_S)
            except Exception as exc:  # noqa: BLE001 — no token stored / transient; never crash the loop
                log.info("oauth.keepalive_skipped provider=%s reason=%s", provider, str(exc)[:120])


async def _on_startup() -> None:
    global _graph

    # #98: the origin gate + IP-trust both fail open without ORIGIN_SHARED_SECRET — warn loudly so a
    # prod deploy without it (Cloudflare not enforced) is visible rather than silent.
    from glitch_signal.config import settings as _settings
    if not _settings().origin_shared_secret:
        log.warning("origin.gate.disabled — ORIGIN_SHARED_SECRET unset; origin-auth + IP trust fail open")

    # Build LangGraph
    from glitch_signal.agent.graph import get_graph
    _graph = get_graph()

    # Start scheduler
    from glitch_signal.scheduler.queue import start as start_scheduler
    start_scheduler()

    # Keep OAuth-backed MCP tokens (e.g. HeyGen: ~1h access + rotating refresh) alive 24/7,
    # so the agent's MCP client always resolves a fresh Bearer even when idle.
    asyncio.create_task(_oauth_keepalive())

    # Mesh Pilot brand-drift audit: log every locally-configured brand
    # against the hub `core.brands` table. Observation-only — never
    # blocks boot, even if the hub DB is unreachable.
    from glitch_signal.shared_context import audit_brand_registry_against_hub
    try:
        await audit_brand_registry_against_hub(brand_ids())
    except Exception as exc:  # pragma: no cover — pure diagnostic
        log.warning("signal.brand_drift audit_failed reason=%s", exc)

    log.info("glitch_signal.started", version=__version__, port=3111)


async def _on_shutdown() -> None:
    from glitch_signal.scheduler.queue import stop as stop_scheduler
    stop_scheduler()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/healthz")
async def healthz() -> dict:
    factory = _session_factory()
    async with factory() as session:
        pending_veto_r = await session.exec(
            select(ScheduledPost).where(ScheduledPost.status == "pending_veto")
        )
        queued_r = await session.exec(
            select(ScheduledPost).where(ScheduledPost.status == "queued")
        )
        dispatching_r = await session.exec(
            select(VideoJob).where(VideoJob.status == "dispatched")
        )

    return {
        "status": "ok",
        "service": "glitch-signal",
        "version": __version__,
        "dispatch_mode": settings().dispatch_mode,
        "queue": {
            "pending_veto": len(pending_veto_r.all()),
            "queued_to_publish": len(queued_r.all()),
            "shots_in_flight": len(dispatching_r.all()),
        },
    }


import re as _re

from sqlalchemy import text as _sqltext

_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_WAITLIST_INSERT = _sqltext(
    "INSERT INTO waitlist (email, source, user_agent) VALUES (:email, :source, :ua) "
    "ON CONFLICT (lower(email)) DO NOTHING"
)


@app.post("/waitlist")
async def waitlist_signup(request: Request) -> dict:
    """Public marketing-site waitlist capture (#99). Body: {email, source?}. Idempotent per email.

    Public + unauthenticated (it's a signup); protected by the app's rate-limit middleware and a
    strict server-side email check. Persists to the `waitlist` table.
    """
    from glitch_signal.db.session import _engine

    body = await _json(request)
    email = str(body.get("email", "")).strip().lower()
    if not email or len(email) > 254 or not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="a valid email is required")
    source = str(body.get("source", "") or "")[:120] or None
    ua = (request.headers.get("user-agent") or "")[:300] or None
    try:
        async with _engine().begin() as conn:
            await conn.execute(_WAITLIST_INSERT, {"email": email, "source": source, "ua": ua})
    except Exception as exc:  # noqa: BLE001
        log.warning("waitlist.insert_failed", error=str(exc)[:200])
        raise HTTPException(status_code=503, detail="could not record signup, please try again")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Manual triggers
# ---------------------------------------------------------------------------

import hmac as _hmac


async def _json(request: Request) -> dict:
    """Best-effort JSON body → dict (empty dict on no/invalid body)."""
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


async def _require_jobs_auth(request: Request, x_jobs_token: str = Header(default="")) -> None:
    """Gate the manual /jobs/* and /internal/* triggers (bug-2, 2026-06-10).

    These dispatch unbounded background LLM/video/Drive pipelines and are served on the public
    signal.meshpilot.app vhost, so this fails CLOSED: we require a matching x-jobs-token header
    (constant-time) against the target brand's `<PREFIX>_JOBS_AUTH_TOKEN`, and if that token is unset
    we DENY with 503 (misconfiguration) rather than open the control surface to the internet.
    """
    # Brand-scope the token check (#95): validate against the TARGET brand's
    # <PREFIX>_JOBS_AUTH_TOKEN (from the ?brand= query param) rather than always the default brand —
    # otherwise the default brand's token authorizes actions on every brand (BFLA). Endpoints without
    # a brand query fall back to the default brand (unchanged). Fail CLOSED: a missing token denies.
    brand = request.query_params.get("brand")
    if brand and brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    expected = brand_env("JOBS_AUTH_TOKEN", brand)
    if not expected:
        log.error("jobs.auth.misconfigured — <PREFIX>_JOBS_AUTH_TOKEN unset; denying")
        raise HTTPException(status_code=503, detail="jobs auth not configured")
    if not _hmac.compare_digest(x_jobs_token or "", expected):
        raise HTTPException(status_code=401, detail="invalid or missing x-jobs-token")


def _authorized_brand(request: Request, body: dict | None = None) -> str:
    """Resolve the brand a /internal|/jobs handler may act on (BFLA fix, #95).

    Derive it from the SAME source `_require_jobs_auth` validated the token against — the
    `?brand=` query param (default brand when absent) — NEVER the request body. A caller holding
    one brand's jobs token (or the default brand's, with no `?brand=`) must not be able to start
    actions for another brand by naming it in the body. Mirrors the PIPELINE endpoints.

    If the body carries a `brand` that differs from the authorized query brand, reject with 400
    rather than silently acting on the wrong one. Behavior is unchanged for the single-brand
    (glitch_executor default) case: no query brand + no body brand → the default brand, as before.

    The no-query default is `settings().default_brand_id` — the SAME brand `_require_jobs_auth`
    authenticated against when `?brand=` is absent, so a deployment with a non-`glitch_executor`
    default resolves to its authenticated brand instead of 400-ing.
    """
    brand = request.query_params.get("brand") or settings().default_brand_id
    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    if body is not None:
        body_brand = body.get("brand")
        if body_brand is not None and body_brand != brand:
            raise HTTPException(
                status_code=400,
                detail="body 'brand' must match the authorized ?brand= query param",
            )
    return brand


def _authorized_path_brand(request: Request, brand_id: str) -> str:
    """Cross-check a PATH `{brand_id}` against the brand the token actually authorized (#95).

    `_require_jobs_auth` validates `x-jobs-token` against the brand in `?brand=` (the default brand
    when absent). A handler that then acts on a brand taken from the URL PATH is authorizing one
    brand and operating on another — the same BFLA shape #95 closed for body-supplied brands, just
    arriving through the path instead. With no `?brand=` at all, the default brand's token would
    authorize a request against ANY brand's path segment.

    The path segment is kept (it is the public URL shape) but must now MATCH the authorized brand;
    a mismatch is 403 — authenticated, but not authorized for this brand — rather than 400, which
    would read as a malformed request.
    """
    authorized = _authorized_brand(request)
    if brand_id != authorized:
        raise HTTPException(
            status_code=403,
            detail="path brand does not match the authorized ?brand= query param",
        )
    return authorized


@app.post("/internal/facebook/test-post", dependencies=[Depends(_require_jobs_auth)])
async def internal_facebook_test_post(request: Request) -> dict:
    """Publish one post to a brand's Facebook Page (verification / manual).

    Body: {message?, link?, image_url?, video_url?}. Auth: x-jobs-token. The target brand comes from
    the authorized `?brand=` (default brand when absent), NOT a body field — a body `brand_id` is
    accepted only if it matches (else 400), so one brand's token can't publish as another (#95).
    Credentials resolve per-brand via brand_env.
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    brand = _authorized_brand(request, {"brand": body.get("brand_id")})
    from glitch_signal.platforms.facebook import publish_facebook

    post_id, permalink = await publish_facebook(
        brand_id=brand,
        message=body.get("message"),
        link=body.get("link"),
        image_url=body.get("image_url"),
        video_url=body.get("video_url"),
    )
    return {"ok": True, "post_id": post_id, "permalink": permalink}


@app.post("/internal/instagram/test-post", dependencies=[Depends(_require_jobs_auth)])
async def internal_instagram_test_post(request: Request) -> dict:
    """Publish one post to a brand's Instagram account (verification / manual).

    Body: {caption?, image_url?, video_url?}. Auth: x-jobs-token. The target brand comes from the
    authorized `?brand=` (default brand when absent), NOT a body field — a body `brand_id` is accepted
    only if it matches (else 400), so one brand's token can't publish as another (#95). Meta requires a
    PUBLIC media URL (e.g. a STORAGE-1 Supabase URL); IG needs image_url or video_url. Credentials
    resolve per-brand via brand_env.
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    brand = _authorized_brand(request, {"brand": body.get("brand_id")})
    from glitch_signal.platforms.instagram import publish_instagram

    media_id, permalink = await publish_instagram(
        brand_id=brand,
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

    Body: {kind: fact|episode, content, key?, metadata?, importance?, source?}. Brand is authorized via `?brand=` (default brand when absent); a body `brand` must match it (#95).
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    brand = _authorized_brand(request, body)
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

    Body: {query, k?, kinds?} → ranked memories with fused/semantic/lexical scores. Brand is authorized via `?brand=` (default brand when absent); a body `brand` must match it (#95).
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    brand = _authorized_brand(request, body)
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


@app.get("/internal/agent/memory/review", dependencies=[Depends(_require_jobs_auth)])
async def internal_agent_memory_review(request: Request, kind: str | None = None, limit: int = 100) -> dict:
    """Operator review queue: list a brand's memories, flagging whether each currently passes the
    verified-provenance gate (auth: x-jobs-token). There is no write path that sets operator-verified
    provenance other than POST /internal/agent/memory/verify below — this route is how an operator
    finds what needs it. Brand is authorized via `?brand=` (default brand when absent), never a path
    or body value (#95)."""
    brand = _authorized_brand(request)
    if kind is not None and kind not in ("fact", "episode"):
        raise HTTPException(status_code=400, detail="kind must be 'fact' or 'episode'")
    from glitch_signal.agent.memory import is_verified_provenance, list_memories

    mems = await list_memories(brand, kind=kind, limit=limit)
    return {
        "ok": True,
        "memories": [
            {
                "id": m.id, "kind": m.kind, "key": m.key, "content": m.content,
                "metadata": m.metadata, "importance": m.importance, "source": m.source,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "verified": is_verified_provenance(m.source, m.metadata),
            }
            for m in mems
        ],
    }


@app.post("/internal/agent/memory/verify", dependencies=[Depends(_require_jobs_auth)])
async def internal_agent_memory_verify(request: Request) -> dict:
    """Grant operator-verified provenance to one or more memory ids (auth: x-jobs-token).

    THIS is the trust-conferring write path `recall(verified_only=True)` / `is_verified_provenance()`
    require — the agent's own tools (source=agent_loop / curator) can never call it. Body:
    {ids: [memory_id, ...]}. Brand is authorized via `?brand=` (default brand when absent); a body
    `brand` must match it, and the update itself is brand-scoped in the DB layer, so one brand's
    token can never verify another brand's memory (#95).
    """
    body = await _json(request)
    brand = _authorized_brand(request, body)
    ids = body.get("ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i for i in ids):
        raise HTTPException(status_code=400, detail="ids (non-empty list of memory id strings) is required")
    from glitch_signal.agent.memory import set_verified

    verified_ids = await set_verified(brand, ids, verified_by="operator")
    return {"ok": True, "verified": verified_ids, "not_found": sorted(set(ids) - set(verified_ids))}


@app.post("/internal/agent/memory/unverify", dependencies=[Depends(_require_jobs_auth)])
async def internal_agent_memory_unverify(request: Request) -> dict:
    """Revoke operator-verified provenance from one or more memory ids (auth: x-jobs-token) — the
    operator taking trust back. Body: {ids: [memory_id, ...]}. Brand is authorized via `?brand=`
    (default brand when absent); a body `brand` must match it, and the update is brand-scoped in the
    DB layer (#95)."""
    body = await _json(request)
    brand = _authorized_brand(request, body)
    ids = body.get("ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i for i in ids):
        raise HTTPException(status_code=400, detail="ids (non-empty list of memory id strings) is required")
    from glitch_signal.agent.memory import unset_verified

    revoked_ids = await unset_verified(brand, ids, revoked_by="operator")
    return {"ok": True, "unverified": revoked_ids, "not_found": sorted(set(ids) - set(revoked_ids))}


@app.post("/internal/brand/{brand_id}/documents", dependencies=[Depends(_require_jobs_auth)])
async def internal_brand_document_upload(request: Request, brand_id: str,
                                         file: UploadFile = File(...),
                                         kind: str = Form("doc")) -> dict:
    """Upload a brand document (PDF/text) to the Anthropic Files API and record it (auth: x-jobs-token).

    Multipart: file=<the document>, kind?=doc|style_guide|brief|deck. The file_id is stored per-brand
    so `read_brand_doc` can ground the agent in it. Only PDF or text/* accepted, ≤25MB.
    """
    brand_id = _authorized_path_brand(request, brand_id)
    data = await file.read()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="file too large (max 25MB)")
    mime = file.content_type or "application/octet-stream"
    if not (mime == "application/pdf" or mime.startswith("text/")):
        raise HTTPException(status_code=415, detail="only PDF or text/* documents are supported")
    from glitch_signal.agent import documents, files
    rec = await files.upload_file(data, file.filename or "document", mime)
    row = await documents.add(brand_id, rec["id"], rec.get("filename") or (file.filename or "document"),
                              mime_type=rec.get("mime_type"), size_bytes=rec.get("size_bytes"), kind=kind)
    return {"ok": True, "doc_id": row["id"], "file_id": rec["id"], "filename": row["filename"]}


@app.get("/internal/brand/{brand_id}/documents", dependencies=[Depends(_require_jobs_auth)])
async def internal_brand_document_list(request: Request, brand_id: str) -> dict:
    """List a brand's uploaded documents (auth: x-jobs-token, brand-scoped)."""
    brand_id = _authorized_path_brand(request, brand_id)
    from glitch_signal.agent import documents
    return {"ok": True, "documents": await documents.list_for_brand(brand_id)}


@app.delete("/internal/brand/{brand_id}/documents/{doc_id}", dependencies=[Depends(_require_jobs_auth)])
async def internal_brand_document_delete(request: Request, brand_id: str, doc_id: str) -> dict:
    """Delete a brand document (row + the Anthropic file). Brand-scoped (auth: x-jobs-token)."""
    brand_id = _authorized_path_brand(request, brand_id)
    from glitch_signal.agent import documents, files
    file_id = await documents.delete(brand_id, doc_id)
    if file_id is None:
        raise HTTPException(status_code=404, detail="document not found for this brand")
    await files.delete_file(file_id)
    return {"ok": True, "deleted": doc_id, "file_id": file_id}


async def _run_agent_bg(run_id: str, brand: str, goal: str, max_steps: int, scope: str) -> None:
    from glitch_signal.agent.loop import run as agent_run
    from glitch_signal.agent.loop import runs as run_store
    try:
        res = await agent_run(brand, goal, max_steps=max_steps, scope=scope)
        await run_store.finish_run(run_id, res)
    except Exception as exc:  # noqa: BLE001
        await run_store.fail_run(run_id, str(exc))


@app.post("/internal/agent/run", dependencies=[Depends(_require_jobs_auth)])
async def internal_agent_run(request: Request) -> dict:
    """Start an agent-loop run for a goal (auth: x-jobs-token).

    Body: {goal, max_steps?, scope?}. Brand is authorized via `?brand=` (default brand when absent); a body `brand` must match it (#95). The loop runs in the BACKGROUND (LLM round-trips
    exceed the edge request timeout), recalling memory, planning, and calling capability-tools —
    but publishing is DISABLED (AGENT-POLICY). `scope` (default `agent_default_scope`) bounds the
    offered toolset (SCOPE). Returns `{ok, run_id, status, scope}`; poll GET /internal/agent/run/{id}.
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
    brand = _authorized_brand(request, body)
    goal = body.get("goal")
    if not goal:
        raise HTTPException(status_code=400, detail="goal is required")

    # SCOPE: bound the run's toolset (default `chat` = safe read+plan). A pipeline/operator run
    # passes a broader scope (e.g. discovery/content/full).
    from glitch_signal.config import settings as _settings
    raw_scope = body.get("scope")
    if raw_scope is not None and not isinstance(raw_scope, str):  # reject synchronously, not in the bg task
        raise HTTPException(status_code=400, detail="scope must be a string")
    scope = raw_scope or getattr(_settings(), "agent_default_scope", "chat")

    run_id = _uuid.uuid4().hex
    await run_store.create_run(run_id, brand, goal)  # row exists before we return
    asyncio.create_task(_run_agent_bg(run_id, brand, goal, int(body.get("max_steps", 5)), scope))
    return {"ok": True, "run_id": run_id, "status": "running", "scope": scope}


@app.get("/internal/agent/routing/metrics", dependencies=[Depends(_require_jobs_auth)])
async def internal_agent_routing_metrics() -> dict:
    """Per-model routing metrics for THIS worker (calls, errors, error_rate, EWMA latency) + the tier
    table (ROUTER). In-process, so per-worker — durable per-model spend lives in usage_events."""
    from glitch_signal.agent.loop import routing
    return {"ok": True, **routing.metrics()}


@app.get("/internal/agent/routing/audit", dependencies=[Depends(_require_jobs_auth)])
async def internal_agent_routing_audit(request: Request) -> dict:
    """Data-grounded ROUTER audit (jobs-auth): flags a tier's primary not serving (fallback firing)
    + per-model cost/call drift from usage_events. `?days=` / `?baseline_days=` optional. Also
    runnable nightly via the `routing_audit` cron capability."""
    from glitch_signal.agent.loop.audit import routing_audit
    qp = request.query_params

    def _pos_int(name: str, default: int, hi: int) -> int:
        raw = qp.get(name)
        if raw is None:
            return default
        try:
            v = int(raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{name} must be an integer")
        if not 1 <= v <= hi:
            raise HTTPException(status_code=400, detail=f"{name} must be between 1 and {hi}")
        return v

    res = await routing_audit(days=_pos_int("days", 1, 30), baseline_days=_pos_int("baseline_days", 7, 90))
    return {"ok": True, **res}


@app.get("/internal/agent/run/{run_id}", dependencies=[Depends(_require_jobs_auth)])
async def internal_agent_run_status(run_id: str) -> dict:
    """Poll an agent run started via POST /internal/agent/run (reads the shared agent_runs table)."""
    from glitch_signal.agent.loop import runs as run_store

    rec = await run_store.get_run(run_id)
    if rec is None:
        return {"ok": True, "run_id": run_id, "status": "unknown"}
    return {"ok": True, **rec}


@app.post("/internal/agent/pipeline/{name}", dependencies=[Depends(_require_jobs_auth)])
async def internal_agent_pipeline(name: str, request: Request) -> dict:
    """Kick off a PIPELINE run now (auth: x-jobs-token) — a deliberate, scoped agent run.

    Brand comes from the `?brand=` query param — the brand `_require_jobs_auth` validated the token
    against — NOT the request body, so one brand's jobs token cannot target another (#95). Resolves
    the named pipeline (discovery/content/orm) to its current scope + goal, checks its required
    kill-switches (409 if any are off), and starts a BACKGROUND run. This is the only place a
    capability turns on for real — the scope bounds the toolset, publishing stays disabled regardless.
    Returns {ok, run_id, pipeline, scope, status}; poll GET /internal/agent/run/{id}.
    """
    import uuid as _uuid

    from glitch_signal.agent.loop import pipelines
    from glitch_signal.agent.loop import runs as run_store

    p = pipelines.resolve(name)
    if p is None:
        raise HTTPException(status_code=404, detail=f"unknown pipeline {name!r}; options: {pipelines.names()}")

    brand = _authorized_brand(request)   # ?brand= (default-brand when absent); never the body
    missing = p.missing_requirements()
    if missing:
        raise HTTPException(status_code=409, detail=f"pipeline {p.name!r} requires: {', '.join(missing)}")

    goal = p.render_goal(brand)
    run_id = _uuid.uuid4().hex
    await run_store.create_run(run_id, brand, goal)
    asyncio.create_task(_run_agent_bg(run_id, brand, goal, p.max_steps, p.scope))
    return {"ok": True, "run_id": run_id, "pipeline": p.name, "scope": p.scope, "status": "running"}


@app.post("/internal/agent/pipeline/{name}/schedule", dependencies=[Depends(_require_jobs_auth)])
async def internal_agent_pipeline_schedule(name: str, request: Request) -> dict:
    """Seed a pipeline's recurring schedule as a cron job (auth: x-jobs-token).

    Brand comes from `?brand=` (the authorized brand), not the body (#95). Seeds a
    `payload_kind=pipelineTurn` cron job (owner `pipeline:<brand>`, name `pipeline:<pipeline>`) at the
    pipeline's cadence carrying ONLY the pipeline NAME — the run re-resolves the pipeline (scope, goal,
    requirements) at each fire, so kill-switches and the content media opt-in are honored live, never
    frozen at seed time. Idempotent per (brand, pipeline): a re-seed updates the existing job instead
    of 500-ing on the unique index. The scheduler fires it only when `agent_cron_enabled` (409 while
    off). Returns {ok, job_id, created, pipeline, scope, schedule}.
    """
    from datetime import datetime, timezone

    from glitch_signal.agent.cron import store as cron_store
    from glitch_signal.agent.loop import pipelines

    p = pipelines.resolve(name)
    if p is None:
        raise HTTPException(status_code=404, detail=f"unknown pipeline {name!r}; options: {pipelines.names()}")
    from glitch_signal.config import settings as _settings
    if not getattr(_settings(), "agent_cron_enabled", False):
        raise HTTPException(status_code=409, detail="scheduling is disabled (agent_cron_enabled is off)")

    brand = _authorized_brand(request)   # ?brand= (default-brand when absent); never the body
    owner, job_name = f"pipeline:{brand}", f"pipeline:{p.name}"
    payload = {"pipeline": p.name}       # NAME only — resolved live at each fire (not a frozen snapshot)
    now = datetime.now(timezone.utc)
    existing = [j for j in await cron_store.list_jobs(brand, owner=owner) if j.get("name") == job_name]
    if existing:                          # idempotent re-seed: update in place, don't collide on the unique index
        job_id = str(existing[0]["id"])
        await cron_store.update_job(job_id, {"schedule": p.schedule, "schedule_kind": p.schedule_kind,
                                             "payload": payload, "enabled": True}, now=now, brand_id=brand)
        created = False
    else:
        job_id = await cron_store.create_job(
            brand_id=brand, name=job_name, owner=owner,
            schedule_kind=p.schedule_kind, schedule=p.schedule,
            payload_kind="pipelineTurn", payload=payload, now=now)
        created = True
    return {"ok": True, "job_id": job_id, "created": created, "pipeline": p.name, "scope": p.scope,
            "schedule_kind": p.schedule_kind, "schedule": p.schedule}


@app.post("/internal/agent/curate", dependencies=[Depends(_require_jobs_auth)])
async def internal_agent_curate(request: Request) -> dict:
    """Distill a brand's recent episodes into durable lessons (AGENT-LEARN; auth: x-jobs-token).

    Body: {limit?}. Brand is authorized via `?brand=` (default brand when absent); a body `brand` must match it (#95). Reads uncurated episodes, asks the LLM to distill them into durable
    facts (upserted by a stable key), and marks those episodes curated. One LLM call — synchronous.
    """
    from glitch_signal.agent.learn import curate as agent_curate

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    brand = _authorized_brand(request, body)
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


@app.get("/internal/analytics/budget", dependencies=[Depends(_require_jobs_auth)])
async def internal_analytics_budget(brand: str = "glitch_executor") -> dict:
    """Per-brand budget status + a simple spend anomaly flag (COST-METER INC-3; auth: x-jobs-token).

    Shows today's metered spend vs the brand's daily cap, plus an anomaly flag when today's run-rate
    is running well above yesterday's same-time spend (early-warning for a cost spike).
    """
    from datetime import datetime, timedelta, timezone

    from glitch_signal.analytics.cost import budget as cost_budget
    from glitch_signal.analytics.cost import spend_summary

    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    now = datetime.now(timezone.utc)
    status = await cost_budget.budget_status(brand, now=now)
    # anomaly: today-so-far vs yesterday up to the same wall-clock time
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    y_start, y_end = day_start - timedelta(days=1), now - timedelta(days=1)
    anomaly = None
    try:
        today = float((status.get("spent_usd") or 0.0))
        yest = float((await spend_summary(brand, y_start, y_end)).get("total_usd", 0.0))
        spike = today > 3 * yest and today > 1.0  # 3x prior day and materially non-trivial
        anomaly = {"today_usd": round(today, 6), "yesterday_to_now_usd": round(yest, 6), "spike": bool(spike)}
    except Exception:  # noqa: BLE001
        anomaly = {"error": "anomaly read failed"}
    return {"ok": True, "steps_ceiling": cost_budget.steps_ceiling(), "anomaly": anomaly, **status}


@app.get("/internal/analytics/spend", dependencies=[Depends(_require_jobs_auth)])
async def internal_analytics_spend(brand: str = "glitch_executor", days: int = 30) -> dict:
    """Per-brand spend across all vendors over the last `days` (COST-METER; auth: x-jobs-token).

    Reads the self-metered `usage_events` — one row per model/media call, costed from the price
    book. Amounts are estimates until INC-2 reconciles them against each vendor's real balance.
    """
    from datetime import datetime, timedelta, timezone

    from glitch_signal.analytics.cost import spend_summary

    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    days = max(1, min(int(days), 365))
    to_ts = datetime.now(timezone.utc)
    from_ts = to_ts - timedelta(days=days)
    summary = await spend_summary(brand, from_ts, to_ts)
    return {"ok": True, "days": days, "estimated": True, **summary}


@app.post("/internal/cron/jobs", dependencies=[Depends(_require_jobs_auth)])
async def internal_cron_create(request: Request) -> dict:
    """Create a self-cron job (AGENT-CRON; auth: x-jobs-token).

    Body: {brand, name, schedule_kind: at|every|cron, schedule:{at|every_ms|cron_expr,tz?},
    payload_kind: agentTurn|capability, payload:{goal,max_steps}|{name,args}, enabled?, pacing?,
    delete_after_run?}. Owner is `operator`.
    """
    from datetime import datetime, timezone

    from glitch_signal.agent.cron import store as cron_store

    body = await _json(request)
    brand = _authorized_brand(request, body)
    for field in ("name", "schedule_kind", "schedule", "payload_kind"):
        if not body.get(field):
            raise HTTPException(status_code=400, detail=f"{field} is required")
    try:
        job_id = await cron_store.create_job(
            brand_id=brand, name=str(body["name"]), owner="operator",
            schedule_kind=str(body["schedule_kind"]), schedule=body["schedule"],
            payload_kind=str(body["payload_kind"]), payload=body.get("payload", {}) or {},
            pacing=body.get("pacing") or {}, enabled=bool(body.get("enabled", True)),
            delete_after_run=bool(body.get("delete_after_run", body.get("schedule_kind") == "at")),
            now=datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001 — validation errors → 400
        raise HTTPException(status_code=400, detail=str(exc)[:200])
    return {"ok": True, "id": job_id}


@app.get("/internal/cron/jobs", dependencies=[Depends(_require_jobs_auth)])
async def internal_cron_list(brand: str = "glitch_executor") -> dict:
    from glitch_signal.agent.cron import store as cron_store

    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    jobs = await cron_store.list_jobs(brand)
    return {"ok": True, "brand": brand, "jobs": jobs, "count": len(jobs)}


@app.get("/internal/cron/jobs/{job_id}", dependencies=[Depends(_require_jobs_auth)])
async def internal_cron_get(job_id: str, brand: str = "glitch_executor") -> dict:
    from glitch_signal.agent.cron import store as cron_store

    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    job = await cron_store.get_job(job_id, brand_id=brand, with_runs=20)  # brand-scoped (#95)
    if job is None:
        raise HTTPException(status_code=404, detail="no such job")
    return {"ok": True, "job": job}


@app.patch("/internal/cron/jobs/{job_id}", dependencies=[Depends(_require_jobs_auth)])
async def internal_cron_update(job_id: str, request: Request, brand: str = "glitch_executor") -> dict:
    """Patch a job: {enabled?, payload?, pacing?, schedule_kind?+schedule?} (reschedule needs both)."""
    from datetime import datetime, timezone

    from glitch_signal.agent.cron import store as cron_store

    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    patch = await _json(request)
    try:
        job = await cron_store.update_job(job_id, patch, now=datetime.now(timezone.utc), brand_id=brand)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)[:200])
    if job is None:
        raise HTTPException(status_code=404, detail="no such job")
    return {"ok": True, "job": job}


@app.delete("/internal/cron/jobs/{job_id}", dependencies=[Depends(_require_jobs_auth)])
async def internal_cron_delete(job_id: str, brand: str = "glitch_executor") -> dict:
    from glitch_signal.agent.cron import store as cron_store

    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    deleted = await cron_store.delete_job(job_id, brand_id=brand)  # brand-scoped (#95)
    if not deleted:
        raise HTTPException(status_code=404, detail="no such job")
    return {"ok": True, "id": job_id, "deleted": True}


@app.post("/internal/cron/jobs/{job_id}/run", dependencies=[Depends(_require_jobs_auth)])
async def internal_cron_run(job_id: str, brand: str = "glitch_executor") -> dict:
    """Force one run now, out-of-band (preserves the natural next slot)."""
    from glitch_signal.agent.cron import service as cron_service

    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    run_id = await cron_service.run_now(job_id, brand_id=brand)  # brand-scoped (#95)
    if run_id is None:
        raise HTTPException(status_code=404, detail="no such job")
    return {"ok": True, "id": job_id, "run_id": run_id, "status": "running"}


@app.get("/internal/cron/runs", dependencies=[Depends(_require_jobs_auth)])
async def internal_cron_runs(job_id: str, brand: str = "glitch_executor", limit: int = 20) -> dict:
    from glitch_signal.agent.cron import store as cron_store

    if brand not in brand_ids():
        raise HTTPException(status_code=400, detail=f"Unknown brand: {brand!r}")
    job = await cron_store.get_job(job_id, brand_id=brand, with_runs=max(1, min(int(limit), 100)))
    if job is None:
        raise HTTPException(status_code=404, detail="no such job")
    return {"ok": True, "job_id": job_id, "runs": job.get("recent_runs", [])}


@app.post("/internal/analytics/reconcile", dependencies=[Depends(_require_jobs_auth)])
async def internal_analytics_reconcile(request: Request) -> dict:
    """Run balance-delta reconciliation across credit vendors now (COST-METER INC-2; auth: x-jobs-token).

    Body: {vendors?: ["muapi","heygen","higgsfield"]}. Snapshots each vendor's balance, diffs it
    against the previous snapshot, and compares that true spend to our summed usage_events for the
    window. Account-level (no per-brand). Also runnable as the `reconcile` cron capability.
    """
    from glitch_signal.analytics.cost import reconcile

    body = await _json(request)
    summary = await reconcile.run(body.get("vendors"))
    return {"ok": True, **summary}


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

    # idempotency: HeyGen may redeliver on retry — dedup fleet-wide via Postgres (#98)
    from glitch_signal.middleware.shared_state import webhook_seen
    if await webhook_seen("heygen", eid):
        return Response(status_code=200)

    try:
        event = _json.loads(raw or b"{}")
    except Exception:
        event = {}
    log.info("heygen.webhook", event_type=event.get("event_type"), event_id=eid,
             video_id=((event.get("event_data") or {}).get("video_id")))
    # Video completion is currently obtained by the HeyGen engine's own poll; this receiver
    # verifies + logs (and is the hook point for push-based completion handling later).
    return Response(status_code=200)


@app.post("/resend/webhook")
async def resend_webhook(request: Request):
    """Receive Resend email events (delivered / bounced / complained / opened / clicked).

    Public (Resend calls it) but Svix-signed: verified with RESEND_WEBHOOK_SECRET
    (`whsec_…`) via the Svix scheme — HMAC-SHA256 over `{svix-id}.{svix-timestamp}.{body}`,
    key = base64-decoded secret, signature header = space-separated `v1,<b64>` entries.
    We reject unverified/stale deliveries, dedup on svix-id (fleet-wide, #98), then ack fast.
    Exempt from origin-auth (not /internal|/jobs) and from the rate limiter (see middleware).
    """
    import base64
    import hashlib
    import hmac
    import json as _json
    import time as _time

    from fastapi import Response

    secret = (settings().resend_webhook_secret or "").strip()
    raw = await request.body()
    svix_id = request.headers.get("svix-id", "")
    svix_ts = request.headers.get("svix-timestamp", "")
    svix_sig = request.headers.get("svix-signature", "")

    if not secret:  # fail closed — never trust an unverified event
        log.warning("resend.webhook.no_secret")
        return Response(status_code=503)
    if not (svix_id and svix_ts and svix_sig):
        return Response("missing signature headers", status_code=400)
    try:
        if abs(_time.time() - int(svix_ts)) > 300:  # ~5 min replay window
            return Response("stale timestamp", status_code=400)
    except ValueError:
        return Response("bad timestamp", status_code=400)

    try:
        key = base64.b64decode(secret[len("whsec_"):] if secret.startswith("whsec_") else secret)
    except Exception:
        log.warning("resend.webhook.bad_secret")
        return Response(status_code=503)
    signed = f"{svix_id}.{svix_ts}.".encode() + raw
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    provided = [p.split(",", 1)[1] for p in svix_sig.split() if "," in p]
    if not any(hmac.compare_digest(expected, p) for p in provided):
        return Response("bad signature", status_code=401)

    # idempotency: Resend/Svix redeliver on retry — dedup fleet-wide via Postgres (#98)
    from glitch_signal.middleware.shared_state import webhook_seen
    if await webhook_seen("resend", svix_id):
        return Response(status_code=200)

    try:
        event = _json.loads(raw or b"{}")
    except Exception:
        event = {}
    data = event.get("data") or {}
    log.info("resend.webhook", event_type=event.get("type"), svix_id=svix_id,
             email_id=data.get("email_id"), to=data.get("to"))
    # Verified + logged. Bounce/complaint → suppression-list + agent-memory feedback is EMAIL-2.
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

    Body: {service?, text?, media_url?, mode?}. service = x/linkedin/tiktok/… Brand is authorized via `?brand=` (default brand when absent); a body `brand` must match it (#95).
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    brand = _authorized_brand(request, body)
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

    Body: {recipe, inputs{...}}. Returns the finished hosted asset URL. Brand is authorized via `?brand=` (default brand when absent); a body `brand` must match it (#95).
    Template-only recipes (e.g. muapi-product-video-ad-maker) run with no LLM;
    recipes whose prompts are LLM-authored return 422 until the composer is
    wired (MEDIA-2).
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    brand = _authorized_brand(request, body)
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
        # engine: explicit override, else the recipe's declared engine (muapi/heygen).
        asset = await media_generate(brief, engine=body.get("engine"), compose=llm_compose)
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


@app.post("/internal/social/preview", dependencies=[Depends(_require_jobs_auth)])
async def internal_social_preview(request: Request) -> dict:
    """Produce one campaign's creative WITHOUT publishing it (auth: x-jobs-token).

    Exists so the operator can judge what the agent would post before letting it post — which means
    it has to work while `agent_publish_enabled` is off. It cannot publish: the dry-run path never
    calls the fan-out, so there is no flag state in which this endpoint reaches a platform. It also
    skips the campaign reservation, so previewing an idea does not burn its dedup key.
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    brand = _authorized_brand(request, body)

    from glitch_signal.agent.social.campaign import run_campaign

    res = await run_campaign(brand, dry_run=True)
    return {
        "ok": True,
        "dry_run": True,
        "brand": brand,
        "idea": ({"angle": res.idea.angle, "hook": res.idea.hook,
                  "asset_kind": res.idea.asset_kind, "key_points": res.idea.key_points}
                 if res.idea else None),
        "image_url": res.image_url,
        "video_url": res.video_url,
        "cost_usd": res.cost_usd,
        "note": res.skipped_reason,
    }


@app.post("/internal/media/ensure-bucket", dependencies=[Depends(_require_jobs_auth)])
async def internal_media_ensure_bucket(request: Request) -> dict:
    """Create the brand's media bucket if absent (auth: x-jobs-token). Brand is authorized via `?brand=` (default brand when absent); a body `brand` must match it (#95)."""
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    brand = _authorized_brand(request, body)
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
