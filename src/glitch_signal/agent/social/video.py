"""HeyGen Video Agent client (no avatar) — SOCIAL-4.

Self-contained: this is NOT a media-factory engine/recipe. It talks to HeyGen's Video Agent API
directly (prompt + reference files -> generated clip), persists the result to the brand's own
Supabase Storage bucket via `glitch_signal.media.generation.storage.upload_bytes`, and meters the
spend through the same `usage_events` choke point as the avatar engine.

Contract verified against developers.heygen.com AND probed live — see `docs/vendors/heygen.md`,
which is the knowledge base this module implements:

    POST {base}/v3/video-agents            -> {data: {session_id, status, video_id|null, created_at}}
    GET  {base}/v3/video-agents/{sid}      -> {data: {status, progress, video_id, messages[]}}
    GET  {base}/v3/videos/{video_id}       -> {data: {status, video_url, failure_code, failure_message}}
    GET  {base}/v2/user/remaining_quota    -> {data: {details: {plan_credit}}}   (no v3 equivalent)

Three production lessons are encoded here, each of which cost us real renders:

1. **Credit is checked BEFORE submitting — in PLAN CREDITS, not the USD wallet.** A Video Agent
   render bills plan credits (26 for a ~38s clip, from the account's own usage history), so the
   wallet balance is irrelevant to whether a render can run. An earlier version of this gate read
   the wallet and would have refused every render on an account with 1,091 credits available.
2. **The SESSION is the authority, not the video.** A session can fail before it is ever assigned a
   `video_id`; polling only the video means waiting out the whole timeout on a run that is already
   dead.
3. **Failure detail lives in `failure_code`/`failure_message`, and often nowhere at all.** We used to
   read `error`/`message`, which HeyGen does not define — every failure logged an empty reason.
   When the documented fields are absent too, the session's `messages` are the only diagnostic.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog

from glitch_signal.agent.social.spec import Idea

log = structlog.get_logger(__name__)

_API_BASE = os.environ.get("HEYGEN_API_BASE") or "https://api.heygen.com"
_API = f"{_API_BASE.rstrip('/')}/v3"
_MAX_FILES = 20          # HeyGen caps `files` at 20 attachments
_MAX_PROMPT = 10_000     # documented `prompt` maxLength

# A Video Agent render bills PLAN CREDITS, not the USD wallet. Measured from the account's own
# usage history: "Glitch Executor: The Payout Truth" (~38s) cost **26 credits**. Below one render's
# worth we refuse to submit rather than let HeyGen accept a session it cannot fund.
_MIN_CREDITS = 26.0

# Session statuses (GET session enum is a SUPERSET of the create enum — `waiting_for_input` and
# `reviewing` only ever appear on the read side).
_SESSION_DONE = "completed"
_SESSION_FAILED = "failed"
_SESSION_STUCK = "waiting_for_input"   # `chat`-mode pause; nobody is listening on a cron run
_VIDEO_TERMINAL_FAIL = ("failed", "error", "cancelled", "canceled")


class HeyGenError(RuntimeError):
    """A HeyGen render did not produce a video."""


class HeyGenCreditError(HeyGenError):
    """Refused before submit: the wallet cannot fund a render.

    Distinct from a generation failure — nothing was spent, and the fix is to top the wallet up
    rather than to retry.
    """


def _fmt_points(points: list[str]) -> str:
    """Key points as flowing narration, not a list.

    HeyGen's own prompt experiments found "stories beat lists" and that rigid segmentation makes
    delivery sound robotic, so these are joined into prose rather than bulleted.
    """
    return " ".join(p.strip().rstrip(".") + "." for p in points if p and p.strip())


def build_video_prompt(idea: Idea, *, seconds: int = 30) -> str:
    """A directorial brief in the shape HeyGen's own testing says works.

    HeyGen published the results of 14 controlled experiments on this exact endpoint. The rules that
    survived them, all of which this brief obeys:

    - **Script first.** The narration words matter more than any production instruction.
    - **Tone, not timestamps.** Per-scene `(0-5s)` blocking "make the delivery sound robotic".
    - **Positive framing only.** Restrictive instructions ("no stock footage", "do NOT…") make the
      agent play safe and produced visually flat results in their tests.
    - **No questions.** Question-driven scripts feel unnatural from a single presenter to camera.
    - **Don't over-prescribe visuals.** The agent composes well when left the room to.

    The presenter is described affirmatively rather than by exclusion, which both satisfies the
    positive-framing rule and pins the narrator's gender — left open, the agent picks one at random
    and the brand's presenter changes between posts.
    """
    script = f"{idea.hook.strip().rstrip('.')}. {_fmt_points(list(idea.key_points))}".strip()
    return (
        f"Make a {seconds}-second portrait video for a trading-tools brand.\n\n"
        "SCRIPT — narrate this closely, in this order:\n"
        f"{script}\n\n"
        "Tone: a working trader talking straight to camera — confident, sharp, honest, done with "
        "hype. Grounded and specific, the way someone explains something they have actually lived "
        "through. Energetic on the setup, slower and heavier on the point that matters.\n"
        "Presenter: one male presenter in his early thirties, visible and speaking to camera "
        "throughout, like a single-take message to a friend who trades.\n"
        "Look: dark, high-contrast, screen-lit — a real trading desk at night, deep charcoal and "
        "near-black with a single cool accent light. Restrained camera movement, real weight to "
        "everything that moves.\n"
        "Captions: one clean caption track following the spoken words, positioned clear of the "
        "bottom edge.\n"
        f"Duration: {seconds} seconds.\n"
        "Orientation: portrait."
    )[:_MAX_PROMPT]


def reference_urls(brand_id: str) -> list[str]:
    """Comma-separated `<PREFIX>_SOCIAL_REFERENCE_URLS`, capped at `_MAX_FILES`."""
    from glitch_signal.config import brand_env

    raw = brand_env("SOCIAL_REFERENCE_URLS", brand_id)
    return [u.strip() for u in raw.split(",") if u.strip()][:_MAX_FILES]


def session_options(brand_id: str) -> dict[str, str]:
    """Optional per-brand pins for the session, each omitted when unset.

    `brand_kit_id` (colors/fonts/logo) and `brand_glossary_id` (how "Glitch Executor" is
    pronounced) are what make successive renders look and sound like ONE brand rather than 30
    unrelated clips; `avatar_id`/`voice_id` pin the presenter; `style_id` picks a curated template.
    """
    from glitch_signal.config import brand_env

    keys = ("avatar_id", "voice_id", "style_id", "brand_kit_id", "brand_glossary_id")
    out = {}
    for k in keys:
        v = (brand_env(f"HEYGEN_{k.upper()}", brand_id) or "").strip()
        if v:
            out[k] = v
    return out


def _heygen_key() -> str:
    """Mirror `HeyGenEngine._key()` exactly: env var, not `settings()`."""
    return (os.environ.get("HEYGEN_API_KEY") or "").strip()


def _heygen_headers() -> dict[str, str]:
    return {"X-Api-Key": _heygen_key(), "Content-Type": "application/json"}


def _min_credits() -> float:
    try:
        return float(os.environ.get("HEYGEN_MIN_CREDITS") or _MIN_CREDITS)
    except ValueError:
        return _MIN_CREDITS


async def credit_balance() -> float | None:
    """Remaining PLAN CREDITS, or None if unreadable.

    ⚠️ Read from the legacy `GET /v2/user/remaining_quota` deliberately. `GET /v3/users/me` is the
    documented replacement but returns only the USD `wallet` for this account — it does not expose
    the credit pool at all, and no v3 endpoint does (`/v3/users/me/credits`, `/v3/credits`,
    `/v3/users/me/usage` all 404). So the endpoint HeyGen removes on **2026-10-31** is currently the
    only source of the number that decides whether a render can run. Re-check for a v3 equivalent
    before that date.

    `details.plan_credit` is the render budget (verified against the account UI: 1,091 remaining).
    The top-level `remaining_quota` is a DIFFERENT, much smaller API-specific pool (63) — reading it
    as the render budget is what the previous version of this code got wrong.
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{_API_BASE.rstrip('/')}/v2/user/remaining_quota",
                            headers=_heygen_headers())
            r.raise_for_status()
            d = ((r.json() or {}).get("data") or {}).get("details") or {}
        return float(d["plan_credit"])
    except Exception:  # noqa: BLE001 — an unreadable balance must not block a render
        return None


async def preflight() -> None:
    """Raise `HeyGenCreditError` when the PLAN CREDITS cannot fund a render.

    Fails CLOSED only on a balance we actually read: an unreadable balance (None) proceeds, because
    refusing every render on a transient endpoint blip would be worse than the thing this guards.
    """
    bal = await credit_balance()
    if bal is None:
        return
    floor = _min_credits()
    if bal < floor:
        raise HeyGenCreditError(
            f"heygen plan credits {bal:.0f} below the {floor:.0f} a render costs — refusing to "
            "submit (see docs/vendors/heygen.md)"
        )


async def _default_submit(prompt: str, file_urls: list[str], *, options: dict | None = None) -> str:
    import httpx

    body: dict[str, Any] = {
        "prompt": prompt[:_MAX_PROMPT],
        "orientation": "portrait",
        "mode": "generate",
        "files": [{"type": "url", "url": u} for u in file_urls[:_MAX_FILES]],
    }
    body.update(options or {})
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{_API}/video-agents", headers=_heygen_headers(), json=body)
        r.raise_for_status()
        return (r.json() or {}).get("data", {})["session_id"]


def _reason(session: dict, video: dict | None = None) -> str:
    """Best available failure reason, in descending order of authority.

    HeyGen documents `failure_code`/`failure_message` on a failed video, but live probing showed
    both absent on a genuinely failed session AND its video — so the session's own messages (newest
    first, `type: "error"` preferred) are the fallback, and an explicit marker is the last resort.
    Anything is better than the empty string this used to log.
    """
    for src in (video or {}, session):
        code, msg = src.get("failure_code"), src.get("failure_message")
        if code or msg:
            return " ".join(str(p) for p in (code, msg) if p)
    msgs = session.get("messages") or []
    for m in msgs:
        if m.get("type") == "error" and m.get("content"):
            return str(m["content"])[:300]
    for m in msgs:
        if m.get("role") == "model" and m.get("content"):
            return f"no failure detail from heygen; last agent message: {str(m['content'])[:200]}"
    return "no failure detail from heygen (no failure_code, failure_message, or session messages)"


async def _default_poll(session_id: str, *, sleep: Any = asyncio.sleep, timeout_s: int = 900) -> str:
    """Poll session -> video until a URL, a failure, or the deadline.

    The SESSION is checked every cycle, not just until a `video_id` appears: a session that fails
    before it is assigned a video is otherwise invisible, and the whole timeout gets spent waiting
    for a video that will never exist. HeyGen advises a 10–30s interval and says generation runs
    5–10x the finished clip's length, so a 30s render is ~3–5 minutes.
    """
    import httpx

    headers = _heygen_headers()
    waited = 0
    async with httpx.AsyncClient(timeout=60) as c:
        while waited < timeout_s:
            r = await c.get(f"{_API}/video-agents/{session_id}", headers=headers)
            r.raise_for_status()
            s = (r.json() or {}).get("data", {})
            status = str(s.get("status", "")).lower()
            video_id = s.get("video_id")

            if status == _SESSION_FAILED:
                raise HeyGenError(f"heygen session {session_id} failed: {_reason(s)}")
            if status == _SESSION_STUCK:
                raise HeyGenError(
                    f"heygen session {session_id} is waiting for input, but this run is "
                    f"unattended (mode=generate): {_reason(s)}"
                )

            if video_id:
                r = await c.get(f"{_API}/videos/{video_id}", headers=headers)
                r.raise_for_status()
                v = (r.json() or {}).get("data", {})
                vstatus = str(v.get("status", "")).lower()
                if vstatus == "completed" and v.get("video_url"):
                    return v["video_url"]
                if vstatus in _VIDEO_TERMINAL_FAIL:
                    raise HeyGenError(f"heygen video {video_id} {vstatus}: {_reason(s, v)}")

            await sleep(10)
            waited += 10
    raise TimeoutError(f"heygen session {session_id} timed out after {timeout_s}s")


async def _default_persist(brand_id: str, url: str) -> str:
    """Download the HeyGen mp4 and re-host it via the real storage helper (STORAGE-1).

    `upload_bytes(data, brand_id, *, ext=, content_type=, prefix=, client=) -> str` is the real
    signature (data first, `ext` not `suffix`, no leading dot) — confirmed by reading storage.py.
    """
    import httpx

    from glitch_signal.media.generation.storage import upload_bytes

    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.get(url)
        r.raise_for_status()
        data = r.content
    return await upload_bytes(data, brand_id, ext="mp4", content_type="video/mp4", prefix="social_video")


async def _meter(brand_id: str, session_id: str) -> None:
    """Attribute this HeyGen Video Agent call to the brand (COST-METER). Never raises."""
    try:
        from glitch_signal.analytics.cost.meter import record_usage
        from glitch_signal.analytics.cost.pricing import heygen_cost

        credits, cost = heygen_cost("video-agent")
        await record_usage(
            brand_id=brand_id,
            vendor="heygen",
            operation="video_agent.generate",
            model="video-agent",
            units={"credits": credits, "session_id": session_id},
            cost_usd=cost,
            request_id=session_id,
        )
    except Exception:  # noqa: BLE001 — metering never breaks generation
        pass


async def generate_video(
    brand_id: str,
    prompt: str,
    file_urls: list[str],
    *,
    submit: Any = None,
    poll: Any = None,
    persist_url: Any = None,
    on_session: Any = None,
    check_credit: Any = None,
    options: dict | None = None,
) -> str:
    """Preflight credit, POST the Video Agent, poll, persist to the brand bucket, return the URL.

    `on_session(session_id)` (optional, sync) is invoked as soon as HeyGen ACCEPTS the render, so a
    caller that later abandons the poll still knows which session it left running.
    """
    submit = submit or _default_submit
    poll = poll or _default_poll
    persist_url = persist_url or _default_persist
    check_credit = check_credit or preflight

    # Before anything is spent or scheduled: an underfunded wallet fails every render at progress 0
    # with no reason attached, so this turns an opaque nightly failure into a nameable one.
    await check_credit()

    session_id = await submit(prompt, file_urls, options=options or {})
    # Meter at ACCEPT, not at completed-poll. HeyGen starts (and charges for) the render the moment
    # it accepts the session, and the caller bounds this coroutine with `asyncio.wait_for` — so
    # metering after the poll silently LOSES the spend of every render we time out on. record_usage
    # is request_id-idempotent on session_id, so accounting for it here is safe and exactly-once.
    await _meter(brand_id, session_id)
    if on_session is not None:
        on_session(session_id)
    # Surface the session id on the cancellation path too: a timed-out render is still running (and
    # already billed) vendor-side, and this is the only handle for reconciling it.
    try:
        heygen_url = await poll(session_id)
    except (asyncio.CancelledError, TimeoutError):
        log.warning("social.video_abandoned", session_id=session_id, brand_id=brand_id)
        raise
    return await persist_url(brand_id, heygen_url)
