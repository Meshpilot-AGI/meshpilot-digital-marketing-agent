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
# How many times a flapping or stalled session is nudged before we call it dead.
_MAX_RESUMES = 3
# No change in (status, progress, video_id) for this long counts as a stall. Sized above the longest
# LEGITIMATE quiet stretch we have measured — a real render sat in `thinking` for 285s before moving
# to `generating` — so a slow-but-healthy render is never nudged out of turn.
_STALL_S = 420


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


def style_paragraph(voice: Any = None, tokens: dict | None = None) -> str:
    """The style paragraph — the single highest-leverage part of a Video Agent prompt.

    Video Agent composes scenes with **Hyperframes**, HeyGen's HTML-to-video engine: every stat,
    caption treatment and transition is authored in code rather than picked from a template set. So
    the agent can render any look you can *describe* — which is why HeyGen's own guide says to spend
    the prompt here. Their prescribed anatomy, all six parts of which this builds:

        a NAME for the style · the exact PALETTE · ART DIRECTION · how things MOVE ·
        what the TRANSITIONS are · one closing line for the VIBE

    Everything is phrased affirmatively. HeyGen's experiments found restrictive instructions ("no
    stock footage", "do NOT…") make the agent play safe and produced visually flat results, so a
    look is pinned by describing what IS there, never by listing what isn't.

    Colours come from the brand's own visual tokens — the same `bg`/`fg`/`accent` the image cards
    render with, so a post and a video from the same campaign agree. Nothing here is brand-specific:
    an unconfigured brand gets the neutral defaults.
    """
    t = tokens or {}
    bg = str(t.get("bg") or "#0B0E14")
    fg = str(t.get("fg") or "#F2F4F8")
    accent = str(t.get("accent") or "#4ADE80")
    name = str(t.get("style_name") or "Night Desk — Terminal Minimal")
    direction = str(getattr(voice, "style", "") or
                    "a real working desk after hours, screen-lit and high contrast")
    return (
        f'STYLE — "{name}":\n'
        f"Palette: {bg} ground, {fg} type, and {accent} as the one accent — reserved for the single "
        "number or word that carries the point, so it lands the way a highlight does.\n"
        f"Art direction: {direction}. Matte surfaces, shallow depth of field, screen light as the "
        "dominant source, generous negative space around the type.\n"
        "Motion: restrained and physical — slow push-ins, real weight behind anything that moves, "
        "type that settles into place and stays still while it is read.\n"
        "Transitions: hard cuts on the beat, with an occasional slow dissolve where the argument "
        "turns.\n"
        "Vibe: composed and expensive — it should read as a professional instrument someone "
        "actually works with."
    )


def caption_line(tokens: dict | None = None) -> str:
    """The caption spec — what makes a post readable with the sound off.

    Most social video is watched muted, so a viewer who cannot follow the narration scrolls. The
    renders we have seen carry a persistent headline card ("STOP BLOWING ACCOUNTS") but no
    word-synced track, so the spoken argument is lost without audio.

    The v1 monorepo's UGC lane learned across 22 iterations that asking for a word-by-word track AND
    beat-styled overlays makes the agent render both at once and they collide. Rather than dropping
    either — the headline cards are a real part of the look — this separates them by POSITION, which
    also keeps to the positive-framing rule that a bare prohibition would break.
    """
    accent = str((tokens or {}).get("accent") or "#4ADE80")
    return (
        "Captions: a single word-by-word caption track that reveals each word as it is spoken — "
        f"white type with {accent} on the one number or term that carries the point, held in the "
        "lower third inside the safe area so the platform's own UI stays clear of it. Any headline "
        "or stat card sits in the upper two-thirds, well above the caption band, so the two read as "
        "separate layers."
    )


def build_video_prompt(idea: Idea, *, seconds: int = 30, voice: Any = None,
                       tokens: dict | None = None) -> str:
    """A directorial brief in the shape HeyGen's own testing says works.

    HeyGen published the results of 14 controlled experiments on this exact endpoint. The rules that
    survived them, all of which this brief obeys:

    - **Script first.** The narration words matter more than any production instruction.
    - **Lead with duration**, and set the orientation explicitly.
    - **A style paragraph, not scene blocking.** See `style_paragraph` — with Hyperframes authoring
      every scene in code, describing the look is what actually moves the output.
    - **Tone, not timestamps.** Per-scene `(0-5s)` blocking "make the delivery sound robotic".
    - **Positive framing only.** Restrictive instructions make the agent play safe and produced
      visually flat results in their tests.
    - **No questions.** Question-driven scripts feel unnatural from a single presenter to camera.

    The presenter is described affirmatively rather than by exclusion, which both satisfies the
    positive-framing rule and pins the narrator — left open, the agent picks one at random and the
    brand's presenter changes between posts.
    """
    script = f"{idea.hook.strip().rstrip('.')}. {_fmt_points(list(idea.key_points))}".strip()
    audience = str(getattr(voice, "audience", "") or "the people this brand serves")
    presenter = str(getattr(voice, "presenter", "")
                    or "one presenter, visible and speaking to camera throughout")
    return (
        f"Make a {seconds}-second portrait video.\n\n"
        "SCRIPT — narrate this closely, in this order:\n"
        f"{script}\n\n"
        f"Tone: speaking straight to camera to {audience} — confident, sharp, honest, done with "
        "hype. Grounded and specific, the way someone explains something they have actually lived "
        "through. Energetic on the setup, slower and heavier on the point that matters.\n"
        f"Presenter: {presenter}.\n\n"
        f"{style_paragraph(voice, tokens)}\n\n"
        f"{caption_line(tokens)}\n"
        f"Duration: {seconds} seconds.\n"
        "Orientation: portrait."
    )[:_MAX_PROMPT]


# `files` (product screenshots, platform logos) is deliberately NOT used on the video path.
# HeyGen does not treat attachments as *style* reference — it drops the literal images into the
# B-roll, so posts came out showing raw screenshots and other companies' logos. Brand identity now
# comes from `brand_kit_id` (palette, fonts, logo), which the agent composes with instead of
# pasting. Operator call, 2026-09-02: "stop attaching the platform photos and logos, just use the
# brand thing."


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


async def _default_resume(session_id: str) -> None:
    """Nudge a stalled/failed session back into motion.

    Any follow-up message resumes the agent — there is no `auto_proceed` flag — so a plain
    "continue" both answers a `waiting_for_input` clarification and restarts a `failed` run.
    """
    import httpx

    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{_API}/video-agents/{session_id}", headers=_heygen_headers(),
                         json={"message": "Please continue and generate the video."})
        r.raise_for_status()


async def _default_stop(session_id: str) -> None:
    """Halt a session we are giving up on. Never raises.

    HeyGen counts **10 concurrent jobs** per account across Video Agent sessions, avatar renders and
    translations. A session abandoned mid-flight keeps holding its slot, so a few stuck nightly runs
    would quietly starve everything else. Best-effort: failing to stop must not mask the real error.
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{_API}/video-agents/{session_id}/stop", headers=_heygen_headers())
            r.raise_for_status()
    except Exception:  # noqa: BLE001
        log.warning("social.video_stop_failed", session_id=session_id)


async def _default_poll(session_id: str, *, sleep: Any = asyncio.sleep, timeout_s: int = 1500,
                        resume: Any = None, max_resumes: int = _MAX_RESUMES,
                        stall_s: int = _STALL_S, stop: Any = None) -> str:
    """Poll session -> video until a URL, exhausted resumes, or the deadline.

    Two things go wrong with a Video Agent session, and neither is visible from the status word
    alone, so this watches for **motion** rather than trusting any single state:

    1. **`failed` is TRANSIENT, not terminal.** Observed live:
       `failed -> thinking -> generating (2 -> 31 -> 97) -> completed`, flapping back through
       `failed` mid-run. The old code raised on the first `failed` and abandoned a render that then
       completed vendor-side with nobody listening — that is why a video we had already been billed
       for went uncollected (2026-08-31) and why five nightly runs produced nothing.
    2. **A session can stall in a HEALTHY-looking state.** One sat in `thinking` at `progress: 0`
       for 25+ minutes. Nudging only on `failed`/`waiting_for_input` never touches it, so it just
       burns the deadline.

    So a nudge fires when the session is `failed`/`waiting_for_input`, OR when
    `(status, progress, video_id)` has not changed for `stall_s`. Any follow-up message resumes the
    agent — there is no `auto_proceed` — and both cases use the same `max_resumes` budget.

    ⚠️ A nudge reliably revives a **`failed`** session (three recovered live). It does **not** unstick
    a session hard-stalled in `thinking` at `progress: 0` — one was nudged and sat unmoved for
    195s+. The stall rule still earns its place there: it bounds the wait and reports
    "no progress for Ns" instead of an anonymous timeout, and the session is stopped on the way out
    so it stops holding one of the account's 10 concurrent job slots.

    The VIDEO's status is never terminal on its own either (it mirrors the session's flapping), so
    it is read only to collect the finished URL.
    """
    import httpx

    resume = resume or _default_resume
    stop = stop or _default_stop
    headers = _heygen_headers()
    waited = resumes = still_for = 0
    seen: tuple | None = None
    async with httpx.AsyncClient(timeout=60) as c:
        while waited < timeout_s:
            r = await c.get(f"{_API}/video-agents/{session_id}", headers=headers)
            r.raise_for_status()
            s = (r.json() or {}).get("data", {})
            status = str(s.get("status", "")).lower()
            video_id = s.get("video_id")

            if video_id:
                r = await c.get(f"{_API}/videos/{video_id}", headers=headers)
                r.raise_for_status()
                v = (r.json() or {}).get("data", {})
                if str(v.get("status", "")).lower() == "completed" and v.get("video_url"):
                    return v["video_url"]

            sig = (status, s.get("progress"), video_id)
            still_for = 0 if sig != seen else still_for + 10
            seen = sig

            broken = status in (_SESSION_FAILED, _SESSION_STUCK)
            if broken or still_for >= stall_s:
                why = status if broken else f"no progress for {still_for}s"
                if resumes >= max_resumes:
                    await stop(session_id)   # release the concurrency slot before bailing
                    raise HeyGenError(
                        f"heygen session {session_id} still stuck ({why}) after {resumes} resume "
                        f"attempts: {_reason(s)}")
                resumes += 1
                log.info("social.video_resumed", session_id=session_id, reason=why,
                         attempt=resumes, progress=s.get("progress"))
                await resume(session_id)
                still_for = 0

            await sleep(10)
            waited += 10
    await stop(session_id)       # same reasoning on the deadline path
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
