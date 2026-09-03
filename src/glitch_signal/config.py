"""Central configuration for Glitch Social Media Agent.

All settings are loaded from .env (or environment variables).
Call settings() anywhere — the result is cached after first load.

Brand configs live in brand/configs/<brand_id>.json (gitignored). Each file
is validated against brand/schema/brand.config.schema.json and merged into
settings().brands. Legacy brand.config.json at repo root is still honoured
and registered as the default brand for backward compatibility.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# The local-dev fallback DSN. Treated as a sentinel: if `signal_db_url` still
# equals this, it was never explicitly set, so `database_url` (Supabase /
# FastAPI Cloud's DATABASE_URL) takes over.
_LOCAL_DB_DEFAULT = "postgresql+asyncpg://signal:changeme@127.0.0.1:5432/glitch_signal"


def _to_asyncpg_url(url: str) -> str:
    """Normalize a Postgres DSN to the SQLAlchemy asyncpg driver.

    Accepts `postgres://`, `postgresql://`, or an already-qualified
    `postgresql+asyncpg://` and returns the asyncpg form unchanged in the
    last case. Query params are preserved here and stripped by
    `_asyncpg_connect_args` where asyncpg needs them as connect kwargs.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


def _asyncpg_connect_args(url: str) -> tuple[str, dict[str, Any]]:
    """Split asyncpg-incompatible bits out of a DSN into connect kwargs.

    Returns `(clean_url, connect_args)`:
    - `sslmode=` (libpq syntax asyncpg doesn't accept) → `ssl=True` and the
      param is dropped from the URL. Managed Postgres (Supabase) requires TLS.
    - Supabase's transaction pooler (`pooler.supabase.com` or port 6543 runs
      pgbouncer in transaction mode) can't use prepared statements, so asyncpg
      needs `statement_cache_size=0`.
    """
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    connect_args: dict[str, Any] = {}

    sslmode = query.pop("sslmode", None)
    host = parts.hostname or ""
    if sslmode in {"require", "verify-ca", "verify-full", "prefer", "allow"} or host.endswith(
        ".supabase.com"
    ) or host.endswith(".supabase.co"):
        # "require" = TLS on, but do NOT verify the cert chain. Supabase's
        # pooler presents a self-signed root, so full verification (ssl=True)
        # fails; "require" matches libpq sslmode=require behaviour.
        connect_args["ssl"] = "require"

    if host.endswith("pooler.supabase.com") or parts.port == 6543:
        connect_args["statement_cache_size"] = 0

    clean = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )
    return clean, connect_args


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Databases ---
    signal_db_url: str = _LOCAL_DB_DEFAULT
    # Supabase / FastAPI Cloud convention. Used as the DB source when
    # SIGNAL_DB_URL is left at its local default (i.e. not explicitly set).
    # A plain `postgresql://…` DSN; normalized to the asyncpg driver at use.
    database_url: str = ""
    # Read-only access to glitchexecutor DB for Phase 2 Scout
    glitch_ro_url: str = ""

    def _raw_db_url(self) -> str:
        """The chosen raw DSN: an explicit SIGNAL_DB_URL wins; otherwise
        Supabase's DATABASE_URL; otherwise the local default."""
        if self.signal_db_url and self.signal_db_url != _LOCAL_DB_DEFAULT:
            return self.signal_db_url
        if self.database_url:
            return self.database_url
        return self.signal_db_url

    def resolved_db_url(self) -> str:
        """asyncpg-driver DSN, ready for create_async_engine (SSL/pooler
        params moved to db_connect_args)."""
        clean, _ = _asyncpg_connect_args(_to_asyncpg_url(self._raw_db_url()))
        return clean

    def db_connect_args(self) -> dict[str, Any]:
        """asyncpg connect kwargs (ssl / statement_cache_size) for this DSN."""
        _, connect_args = _asyncpg_connect_args(_to_asyncpg_url(self._raw_db_url()))
        return connect_args

    # --- LLMs ---
    anthropic_api_key: str = ""
    google_api_key: str = ""
    openai_api_key: str = ""
    openai_smart_model: str = "gpt-4o"
    openai_cheap_model: str = "gpt-4o-mini"
    # --- Amazon Bedrock (all internal text LLM; customers bring own Claude Code/Codex) ---
    platform_llm_via_bedrock: bool = False
    bedrock_region: str = "us-east-2"
    bedrock_chat_premium_model: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    bedrock_chat_cheap_model: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    vertex_project: str = ""
    vertex_location: str = "us-central1"


    # --- Video models ---
    kling_api_key: str = ""
    kling_api_url: str = "https://api.klingai.com"
    runway_api_key: str = ""    # Phase 2
    veo_api_key: str = ""       # Phase 2
    hailuo_api_key: str = ""    # Phase 2

    # --- Image generation (Replicate) ---
    replicate_api_token: str = ""
    replicate_image_model: str = "recraft-ai/recraft-v3"

    # --- Image generation (fal.ai) — primary provider, faster + cheaper ---
    fal_api_key: str = ""
    fal_image_model: str = "fal-ai/flux/schnell"

    # --- Image generation (Leonardo.ai) — poster/typography-style backgrounds ---
    # Used for slide + quote-card backgrounds. We never ask Leonardo to render
    # real text — text is overlaid in Pillow. Leonardo Phoenix is the
    # poster/illustration model; Vision XL is more photoreal. Phoenix is
    # the default because we want abstract editorial-poster look, not photos.
    # Model IDs: https://docs.leonardo.ai/reference/list_models_v3
    leonardo_api_key: str = ""
    leonardo_model_id: str = "de7d3faf-762f-48e0-b3b7-9d0ac3a3fcf3"  # Leonardo Phoenix 1.0
    leonardo_base_url: str = "https://cloud.leonardo.ai/api/rest/v1"

    # --- Sheet-driven posting (scheduled from a Google Sheet) ---
    # When set, the scheduler reads this sheet and fires queued posts at the
    # configured cadence. Columns are managed by sheet_posting.reader.
    #
    # The original implementation used one tab named `queue`. As of April
    # 2026 we split per-brand into separate tabs ("brand" and "founder")
    # so each account has its own editable view. Legacy single-tab callers
    # still work — set glitch_posts_worksheet alone and leave the per-brand
    # ones empty.
    glitch_posts_sheet_id: str = ""
    glitch_posts_worksheet: str = "queue"
    glitch_posts_brand_worksheet: str = ""
    glitch_posts_founder_worksheet: str = ""
    # Minimum gap between two posts on the same (brand, platform) pair.
    glitch_posts_min_interval_minutes: int = 240  # 4 hours
    # Max posts per (brand, platform) per UTC calendar day.
    glitch_posts_daily_cap: int = 2

    # --- Platforms (Phase 1: YouTube) ---
    youtube_client_secrets_file: str = "credentials/youtube_client_secrets.json"
    youtube_channel_id: str = ""
    # Phase 2
    twitter_api_key: str = ""
    twitter_api_secret: str = ""
    twitter_access_token: str = ""
    twitter_access_token_secret: str = ""
    twitter_bearer_token: str = ""
    ig_access_token: str = ""
    ig_user_id: str = ""

    # --- Meta (Facebook / Instagram) Graph API ---
    # Version is a platform constant (not per-brand). Per-brand creds
    # (page id, IG user id, system-user token) resolve via brand_env().
    # Meta platform is on v26.0 (confirmed via the DevTools API). Verified before bumping: the page
    # node, the IG user node and /{ig}/media all behave identically on v21 and v26, the app reports
    # zero deprecations, and the insights-metric probe returns the same result on v21/v23/v26.
    # Override with META_GRAPH_API_VERSION to roll back without a deploy.
    meta_graph_api_version: str = "v26.0"

    # --- YouTube OAuth2 (per-brand: <PREFIX>_YOUTUBE_CLIENT_ID/SECRET via brand_env) ---
    # Redirect URI must exactly match the one registered on the OAuth client.
    youtube_redirect_uri: str = "https://api.meshpilot.app/oauth/youtube/callback"
    # Full pragmatic channel control for the agent: upload videos, manage the
    # account (videos/playlists/channel), and force-ssl (read/write incl comments
    # + moderation). All restricted scopes — fine under the 100-user cap while
    # the consent screen is unverified.
    youtube_oauth_scopes: str = (
        "https://www.googleapis.com/auth/youtube.upload "
        "https://www.googleapis.com/auth/youtube "
        "https://www.googleapis.com/auth/youtube.force-ssl"
    )

    # --- Storage ---
    video_storage_path: str = "/var/lib/glitch-signal/videos"

    # --- Runtime ---
    public_base_url: str = "https://signal.meshpilot.app"
    dispatch_mode: str = "live"   # dry_run | live
    log_level: str = "INFO"
    scheduler_tick_ms: int = 30_000
    scheduler_stuck_after_ms: int = 300_000   # 5 min

    # --- Scout ---
    github_token: str = ""
    github_org: str = "glitch-exec-labs"
    github_repos: str = ""  # csv of repo names; empty = all org repos

    # --- Google Drive (drive_footage content source) ---
    # Service-account JSON path. SA email must have Viewer on each brand's
    # Drive folder. Empty = drive_scout is disabled.
    google_drive_sa_json: str = ""

    # --- Brand ---
    brand_config_path: str = "brand.config.json"          # legacy single-file (still supported)
    brand_configs_dir: str = "brand/configs"              # multi-brand dir
    default_brand_id: str = "glitch_executor"

    # --- OAuth + token storage ---
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    auth_encryption_key: str = ""

    # --- TikTok Content Posting API ---
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_redirect_uri: str = "https://meshpilot.app/oauth/tiktok/callback"
    tiktok_api_base: str = "https://open.tiktokapis.com"
    tiktok_auth_base: str = "https://www.tiktok.com"
    tiktok_default_scopes: str = "user.info.basic,video.upload,video.publish"
    tiktok_post_status_timeout_s: int = 180

    # --- MuAPI (multi-model image/video gen for the influencer pipeline) ---
    # Same provider the cockpit creative studio uses. submit→poll contract.
    muapi_api_key: str = ""
    muapi_api_base: str = "https://api.muapi.ai/api/v1"

    # --- HeyGen (second media provider: avatar / talking-head video, v3) ------
    # Global infra key (like MUAPI). submit (POST /v3/videos) → poll GET /v3/videos/{id}.
    heygen_api_key: str = ""
    heygen_api_base: str = "https://api.heygen.com"

    # --- Higgsfield (third media provider: image/video/3D/audio) ---
    # SDK credential = "<key>:<secret>". Global infra (one Higgsfield account).
    higgsfield_api_key: str = ""
    higgsfield_api_secret: str = ""
    # Webhook signing secret (whsec_…) for POST /webhooks/heygen — HMAC-SHA256 of the raw
    # body. Empty → the receiver fails closed (rejects), since we never trust unverified events.
    heygen_webhook_secret: str = ""

    # --- CF / origin hardening (mirrors leaselens; see docs) -----------------
    # Origin shared-secret gate: Cloudflare injects `origin_auth_header` with this value
    # on api.meshpilot.app once proxied; the app then requires it on /internal + /jobs so a
    # direct-to-origin hit (bypassing the WAF) is 403'd. Unset = fail-open (no outage risk).
    origin_shared_secret: str | None = None
    origin_auth_header: str = "x-origin-auth"
    # TrustedHostMiddleware allowlist (comma-separated). "*" = allow all (keeps FastAPI
    # Cloud health probes from being 400'd; host filtering happens at the CF edge).
    trusted_hosts: str = "*"
    # CORS allowlist (comma-separated). Empty = no browser origin (internal API by default).
    cors_allow_origins: str = ""
    # Raw-ASGI request body cap (JSON only → 2 MiB is generous headroom).
    max_request_body_bytes: int = 2 * 1024 * 1024
    # In-app rate limiting (per-instance speed bump; real enforcer is the CF WAF).
    rate_limit_enabled: bool = True
    rate_limit_window_s: int = 60
    rate_limit_per_ip: int = 120        # per client IP, per window
    rate_limit_global: int = 3000       # constant-keyed global backstop, per window
    # #98: back the limiter with Postgres so it enforces fleet-wide (not per-worker). Off by default
    # — it adds a DB round-trip per request, and CF WAF is the real control; opt in per-env.
    rate_limit_shared: bool = False

    # --- Agent policy (AGENT-POLICY) — deterministic gate on tool calls ---
    # Publishing kill-switch: while False, every publish/post tool is denied regardless of
    # brand. Flip to True (per env) ONLY when posting is intentionally enabled.
    agent_publish_enabled: bool = False
    # --- Email (EMAIL-1) — the agent's outbound mail channel via Resend ---
    resend_api_key: str = ""
    resend_webhook_secret: str = ""   # Svix whsec_… — verifies POST /resend/webhook
    resend_from: str = ""             # agent-wide default From (per-brand: <PREFIX>_RESEND_FROM)
    # Email kill-switch (mirrors agent_publish_enabled): while False the agent's `send_email`
    # tool is denied by the policy gate. Sending stays OFF until deliberately enabled.
    agent_email_enabled: bool = False
    agent_max_emails_per_run: int = 5        # per-loop-run cap (policy gate, via counts)
    agent_email_brand_daily_cap: int = 50    # per-brand/day cap (send path; 0 = unlimited)
    # --- Discovery (CaptAPI) — trending social content signals ---
    captapi_key: str = ""                    # capt_live_… (Bearer); the discover_trending tool
    redditapis_token: str = ""       # redditapis.com — Reddit discovery reads ($0.002/call), TARGET-1
    zernio_api_key: str = ""         # zernio.com — OAuth social surface: subreddit rules, posting
    # Discovery kill-switch (mirrors agent_email_enabled): while False the agent's
    # `discover_trending` tool is denied by the policy gate. Stays OFF (no external pulls) until
    # deliberately enabled — the ability ships inert.
    agent_discovery_enabled: bool = False
    agent_max_discovery_per_run: int = 5     # per-loop-run cap (policy gate, via counts)
    # --- Web tools (web_search / web_fetch) ---
    # Web kill-switches (mirror agent_discovery_enabled): while False, the agent's `web_search` /
    # `web_fetch` tools are denied by the policy gate. Outbound web access + LLM-plugin cost stay
    # OFF until deliberately enabled — the ability ships inert (#191).
    agent_web_search_enabled: bool = False
    agent_web_fetch_enabled: bool = False
    # SCOPE: default toolset for an un-specified run (Discord/bare). `chat` = safe read+plan only;
    # a pipeline/operator run passes a broader scope (discovery/content/orm/full).
    agent_default_scope: str = "chat"
    # Per-run cost budget: max paid media generations the agent may run in a single loop.
    agent_max_media_per_run: int = 3
    # DELIBERATION (Phase 1/2) — advisory metacognition passes wrapped around a run, default OFF.
    # Reckoning: record an expectation before acting, self-assess vs actual after (fault attribution).
    # Conscience: an independent critic reviews the run's outward output against agent/CONSCIENCE.md.
    # Both only annotate the episode + run result (they block nothing) and each is one cheap Haiku call.
    agent_reckoning_enabled: bool = False
    agent_conscience_enabled: bool = False
    # SOCIAL-CAMPAIGN — master switch (default OFF: ships inert) + per-run post cap (the 5 platforms).
    agent_social_enabled: bool = False
    agent_social_max_posts_per_run: int = 5
    # HeyGen Video Agent render deadline for a social run. Kept well under the cron capability
    # timeout so a slow video times out to IMAGE-ONLY (fail-soft) instead of the cron killing the
    # whole run and losing image progress.
    agent_social_video_timeout_s: int = 1500   # a resumed HeyGen render measured ~555s
    # PIPELINE: when False, the `content` pipeline runs caption-first (scope `content_draft`, no paid
    # media) — it drafts copy + a media brief. Flip True to have content runs also generate the media
    # (scope `content`, MUapi/Higgsfield, bounded by agent_max_media_per_run).
    agent_content_media_enabled: bool = False
    # Hard ceiling on agent-loop steps (COST-METER INC-3) — clamps any caller/payload max_steps so an
    # unbounded value can't drive recursive cost blow-up. Applied at the single runner choke point.
    agent_max_steps_ceiling: int = 12
    # Per-brand DAILY spend cap in USD (COST-METER INC-3). 0 = unlimited. Per-brand override via
    # brand_env("DAILY_BUDGET_USD"). When today's metered spend >= cap, agent runs + paid media are denied.
    agent_brand_daily_budget_usd: float = 0.0
    # Interactive API docs (Swagger /docs, /redoc, /openapi.json). OFF by default so the full
    # API surface isn't published to the public internet in production; flip on per env locally.
    enable_api_docs: bool = False
    # Self-cron kill-switch (AGENT-CRON): while False, the scheduler fires no jobs and the
    # agent's `schedule` tool is denied. Flip to True to enable self-scheduling.
    # SEO kill-switch (SEO-4). While False the scheduled `seo_publish` capability refuses
    # before authoring anything. Ships OFF: autonomous publishing into a site repo is
    # opt-in per deployment, not a default.
    agent_seo_enabled: bool = False

    agent_cron_enabled: bool = False
    # Max active agent-owned scheduled jobs per brand (self-scheduling creator-cap).
    agent_cron_max_jobs_per_brand: int = 20
    # Consecutive scheduled-job failures before the job auto-disables.
    agent_cron_max_failures: int = 3

    # --- ElevenLabs (TTS for YouTube Shorts pipeline) ---
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # Rachel (default)
    elevenlabs_model: str = "eleven_turbo_v2_5"        # ~80% cheaper, fast

    # --- Make.com (automation platform) ---
    # Zone-bound. us1 / us2 / eu1 / eu2 — do NOT mix zones across base URL
    # and token; a token issued on us2 is rejected by us1 and vice versa.
    make_base_url: str = "https://us2.make.com"
    make_api_base: str = "https://us2.make.com/api/v2"
    make_org_id: str = ""
    make_api_token: str = ""

    # --- LinkedIn direct API (Marketing Developer Platform) ---
    # The sheet-posting pipeline routes LinkedIn rows through LinkedIn's
    # native /rest/posts + /rest/documents endpoints, returning the real
    # urn:li:share:... synchronously, and supports comment read/reply on
    # company-page posts (r_organization_social).
    #
    # Scopes required for full functionality:
    #   w_member_social         — post on the founder's profile
    #   w_organization_social   — post on the company page
    #   r_organization_social   — read comments on company-page posts
    #   rw_organization_admin   — verify admin role on the company at OAuth
    # Comment read on the founder's *personal* posts requires r_member_social
    # (Community Management API for Members) which is a separate approval.
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_redirect_uri: str = ""
    linkedin_access_token: str = ""
    linkedin_refresh_token: str = ""
    # API version pinned to a known-good release; bump when migrating.
    # Format: YYYYMM. See linkedin/marketing/versioning docs.
    linkedin_api_version: str = "202604"
    # Pre-cached URNs so we don't have to call /v2/userinfo on every post.
    # Founder = Tejas's Person URN; brand_org = Glitch Executor company URN.
    linkedin_founder_person_urn: str = ""
    linkedin_brand_org_urn: str = "urn:li:organization:111931921"

    # --- Buffer (primary multi-platform publisher, GraphQL) ---
    # Buffer forwards our signed asset URL untouched, so TikTok AI-voice
    # audio plays on every surface. See platforms/buffer.py for the full
    # diagnosis. A Buffer post lands asynchronously: the publisher flips the
    # ScheduledPost to `awaiting_webhook` and the reconcile sweep polls
    # Buffer's status until it finalizes.
    buffer_api_token: str = ""
    # NB: the /jobs + /internal auth token is NOT a global setting — it is per-brand,
    # read via brand_env("JOBS_AUTH_TOKEN") (i.e. <PREFIX>_JOBS_AUTH_TOKEN), and it fails CLOSED
    # (503 when unset). See server._require_jobs_auth. (The old global `jobs_auth_token` field was
    # dead — never read — and removed 2026-08-29.)
    # How long a ScheduledPost may sit in `awaiting_webhook` before the
    # reconcile sweep polls the publisher for a terminal status.
    webhook_reconcile_after_s: int = 600   # 10 min

    # --- Post-publish analytics pull cadence ---
    # The scheduler's
    # _pull_post_analytics tick writes a MetricsSnapshot every
    # analytics_pull_interval_s once the post is at least
    # analytics_first_pull_after_s old (so metrics have time to accrue).
    analytics_first_pull_after_s: int = 3_600     # 1 hour
    analytics_pull_interval_s: int = 86_400        # 24 hours
    analytics_sweep_batch: int = 10

    # --- Media cleanup ---
    # Raw Drive footage is client-owned; we don't need to keep the local
    # copy after publish. The _cleanup_posted_media scheduler tick deletes
    # the local file (plus any ffmpeg transform siblings like
    # .strip_audio.mp4) this many minutes after the PublishedPost is
    # written. 60 min default = 1 hour grace for re-upload or manual
    # inspection if anything went sideways.
    media_cleanup_after_minutes: int = 60
    media_cleanup_batch: int = 50

    # --- Media-serve public base URL ---
    # Zernio fetches videos from this host when posts are published via
    # the zernio_* publishers. An nginx location block on this hostname
    # proxies /media/* to the FastAPI app on 127.0.0.1:3111.
    media_public_base_url: str = "https://meshpilot.app"

    # --- Retry windows (ms) ---
    publish_retry_1_ms: int = 1_800_000   # 30 min
    publish_retry_2_ms: int = 7_200_000   # 2 h
    orm_review_window_s: int = 7_200      # 2 h

    @property
    def github_repo_list(self) -> list[str]:
        if not self.github_repos:
            return []
        return [r.strip() for r in self.github_repos.split(",") if r.strip()]

    @property
    def is_dry_run(self) -> bool:
        return self.dispatch_mode.strip().lower() == "dry_run"


@lru_cache
def settings() -> Settings:
    return Settings()


# ---------------------------------------------------------------------------
# Brand config registry — loaded once, keyed by brand_id
# ---------------------------------------------------------------------------

_brand_registry: dict[str, dict] | None = None


def _load_brand_registry() -> dict[str, dict]:
    """Discover and load every brand config file under brand/configs/.

    Precedence (highest first):
      1. Files under brand_configs_dir (one file per brand, stem = brand_id).
      2. Legacy brand.config.json at repo root, registered as default brand.
      3. Built-in defaults (glitch_executor only) — tolerated, warned about.

    Each loaded config is normalised to include a 'brand_id' field matching
    the filename stem. Files whose internal brand_id disagrees with the stem
    are rejected loudly.
    """
    s = settings()
    registry: dict[str, dict] = {}

    configs_dir = pathlib.Path(s.brand_configs_dir)
    if configs_dir.is_dir():
        for path in sorted(configs_dir.glob("*.json")):
            stem = path.stem
            if stem.startswith("."):
                continue
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Invalid JSON in brand config {path}: {exc}"
                ) from exc

            internal_id = data.get("brand_id")
            if internal_id and internal_id != stem:
                raise RuntimeError(
                    f"Brand config {path} has brand_id={internal_id!r} "
                    f"but filename stem is {stem!r}. These must match."
                )
            data.setdefault("brand_id", stem)
            registry[stem] = data

    # Legacy single-file fallback (pre-multi-brand deployments).
    legacy_path = pathlib.Path(s.brand_config_path)
    if not registry and legacy_path.exists():
        try:
            legacy = json.loads(legacy_path.read_text())
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Invalid JSON in legacy {legacy_path}: {exc}"
            ) from exc
        legacy.setdefault("brand_id", s.default_brand_id)
        legacy.setdefault("display_name", legacy.get("brand", {}).get("name", s.default_brand_id))
        legacy.setdefault("timezone", "UTC")
        registry[s.default_brand_id] = legacy

    # Built-in safety net so tests and fresh clones run without setup.
    if not registry:
        logger.warning(
            "No brand configs found at %s/*.json or %s — falling back to "
            "built-in Glitch Executor defaults. Drop a real config at "
            "%s/%s.json for production.",
            s.brand_configs_dir,
            s.brand_config_path,
            s.brand_configs_dir,
            s.default_brand_id,
        )
        registry[s.default_brand_id] = _default_brand_config()

    # Default brand must be present.
    if s.default_brand_id not in registry:
        raise RuntimeError(
            f"default_brand_id={s.default_brand_id!r} has no matching config "
            f"file. Available brands: {sorted(registry.keys())}"
        )

    return registry


def _brands() -> dict[str, dict]:
    global _brand_registry
    if _brand_registry is None:
        _brand_registry = _load_brand_registry()
    return _brand_registry


def brand_ids() -> list[str]:
    """All configured brand ids, sorted."""
    return sorted(_brands().keys())


def brand_config(brand_id: str | None = None) -> dict:
    """Return the config dict for brand_id, or the default brand if None.

    Kept backward-compatible: existing callers that pass no argument still
    get the same single-brand config they used to read from brand.config.json.

    Previously also stamped `hub_canonical_brand_id`, resolved from the v1 monorepo's hub DB. That
    hub is gone — `POSTGRES_BRAIN_URL` is configured in neither prod nor local env, so the startup
    audit always reported `hub_unreachable`, the value was always None, and nothing ever read it.
    Removed with `shared_context.py` (2026-09-02).
    """
    registry = _brands()
    key = brand_id or settings().default_brand_id
    if key not in registry:
        raise KeyError(
            f"Unknown brand_id {key!r}. Configured brands: {sorted(registry.keys())}"
        )
    cfg = registry[key]
    return cfg


def brand_env_prefix(brand_id: str | None = None) -> str | None:
    """The env-key prefix declared by a brand's config (e.g. "GE"), or None."""
    prefix = brand_config(brand_id).get("env_prefix")
    return prefix or None


def brand_env(name: str, brand_id: str | None = None, default: str = "") -> str:
    """Resolve a per-brand credential/config value from the environment.

    This is the ONE way capabilities read project-scoped secrets. Every value
    is looked up as ``<ENV_PREFIX>_<name>`` where the prefix comes from the
    brand's config (`env_prefix`). There are no global keys: a project brings
    its own `<TAG>_*` set, and a new project just declares its own prefix.

    Returns `default` when the brand declares no prefix or the var is unset.

        brand_env("META_APP_ID")               # -> os.environ["GE_META_APP_ID"]
        brand_env("BUFFER_API_KEY", "acme")     # -> os.environ["ACME_BUFFER_API_KEY"]
    """
    prefix = brand_env_prefix(brand_id)
    if not prefix:
        return default
    return os.environ.get(f"{prefix}_{name}", default)


def brand_env_or_default(name: str, brand_id: str | None = None, default: str = "") -> str:
    """Per-brand value, falling back to the agent-wide default (the unprefixed env var).

    A project brings its own `<PREFIX>_<name>`; when it doesn't, the agent uses its own default
    (e.g. the MeshPilot Meta app: `SYSTEM_USER_TOKEN` / `META_PAGE_ID` / `META_IG_USER_ID`).
    """
    return brand_env(name, brand_id) or os.environ.get(name, default)


# Which publisher handles each target: three publishers — Buffer (TikTok / X /
# LinkedIn), Meta (Facebook / Instagram), and YouTube direct. Targets with no
# entry here (threads / pinterest / bluesky / reddit) have no publisher and are
# dropped until a real one exists for them.
_PUBLISH_PRIORITY = {
    "tiktok":    ["buffer_tiktok"],
    "x":         ["buffer_x"],
    "linkedin":  ["buffer_linkedin"],
    "facebook":  ["meta_facebook"],
    "instagram": ["meta_instagram"],
    "youtube":   ["youtube_shorts"],
}


def resolve_publish_platform(brand_id: str, target: str = "tiktok") -> str:
    """Return the platform key a brand should publish to for `target`.

    Walks the priority list and returns the first key whose brand config
    has `enabled=true`.

    Raises RuntimeError if nothing is enabled for this target.
    """
    cfg = brand_config(brand_id)
    platforms = cfg.get("platforms", {}) or {}
    priority = _PUBLISH_PRIORITY.get(target, [])
    for key in priority:
        block = platforms.get(key) or {}
        if block.get("enabled"):
            return key
    raise RuntimeError(
        f"Brand {brand_id!r} has no enabled publisher for target {target!r}. "
        f"Checked: {priority}. Enable one in brand/configs/{brand_id}.json."
    )


def _reset_brand_registry_for_tests() -> None:
    """Test-only: force the registry to be reloaded on next access."""
    global _brand_registry
    _brand_registry = None


def _default_brand_config() -> dict[str, Any]:
    s = settings()
    return {
        "brand_id": s.default_brand_id,
        "display_name": "Glitch Social Media Agent",
        # Per-project env-key prefix. Every credential this brand uses is read
        # as <ENV_PREFIX>_<KEY> (e.g. GE_META_APP_ID). A new project declares
        # its own prefix in its brand config; there are no global keys.
        "env_prefix": "GE",
        "timezone": "UTC",
        "content_source": "ai_generated",
        "brand": {
            "name": "Glitch Social Media Agent",
            "accent_color": "#00ff88",
            "base_color": "#0a0a0f",
            "watermark_path": "assets/brand/mascot-128.png",
            "voice": "technical, direct, no marketing hype, no emoji walls",
        },
        "video_model_routing": {
            "phase": 1,
            "model_map": {
                "cinematic": "kling_2",
                "realistic": "kling_2",
                "text_in_video": "kling_2",
                "fast": "kling_2",
            },
        },
        "orm_guardrails": {
            "hard_stop_phrases": [
                "loss",
                "money lost",
                "lost $",
                "lost ₹",
                "SEC",
                "SEBI",
                "FINRA",
                "regulatory",
                "illegal",
                "guarantee",
                "promise",
                "certain returns",
                "lawyer",
                "legal action",
                "lawsuit",
            ],
            "competitor_names": [],
            "auto_respond_tiers": ["positive", "neutral_faq", "neutral_technical"],
            "review_window_seconds": {"negative_mild": 7200},
            "escalate_tiers": ["negative_severe", "legal_flag"],
            "ignore_tiers": ["spam"],
            "min_confidence_threshold": 0.7,
        },
        "platforms": {
            "youtube": {
                "enabled": True,
                "privacy_status": "public",
                "default_tags": ["shorts", "algotrading", "tradingbot", "glitchexecutor"],
                "category_id": "28",
            }
        },
        "default_hashtags": [],
        "voice_prompt_path": None,
    }
