"""HeyGen Video Agent client — prompt shape, credit preflight, and poll/failure semantics.

Every failure case below is one that actually burned a render in production (2026-09-01/02) or
logged an unreadable reason; see `docs/vendors/heygen.md`.
"""
import pytest

from glitch_signal.agent.social import video
from glitch_signal.agent.social.spec import Idea

IDEA = Idea("risk", "Blow-ups are optional", ["use stops"], "k")


async def _noop_credit():
    return None


# ── prompt: HeyGen's own experiment-backed rules ──
def test_build_video_prompt_is_portrait_positive():
    p = video.build_video_prompt(IDEA)
    assert "portrait" in p.lower()
    assert "no b-roll" not in p.lower()          # positive framing only
    assert "Blow-ups are optional" in p


def test_build_video_prompt_leads_with_script_and_tone_not_timestamps():
    p = video.build_video_prompt(IDEA)
    assert "SCRIPT" in p and "Tone:" in p
    # "Don't over-structure" — per-scene timestamps made HeyGen's own renders sound robotic.
    assert "0-5s" not in p and "(0-" not in p
    # "Don't use question-driven scripts" — unnatural from a single presenter to camera.
    assert "?" not in p


def test_build_video_prompt_pins_the_presenter():
    # Left open, the agent picks a narrator gender at random and the brand's presenter changes
    # between posts. Stated affirmatively so it doesn't trip the no-negations rule.
    assert "male presenter" in video.build_video_prompt(IDEA).lower()


def test_build_video_prompt_respects_the_10k_cap():
    long_idea = Idea("risk", "Hook", ["point " * 400] * 20, "k")
    assert len(video.build_video_prompt(long_idea)) <= 10_000


def test_reference_urls_splits_env(monkeypatch):
    monkeypatch.setenv("GE_SOCIAL_REFERENCE_URLS", "https://a/1.png, https://a/2.png")
    urls = video.reference_urls("glitch_executor")   # ENV_PREFIX for glitch_executor is GE
    assert urls == ["https://a/1.png", "https://a/2.png"]


def test_session_options_omits_unset_keys(monkeypatch):
    # HeyGen rejects unrecognised/None fields with a 422, so an unset pin must be ABSENT.
    monkeypatch.setenv("GE_HEYGEN_BRAND_KIT_ID", "bk_1")
    monkeypatch.delenv("GE_HEYGEN_VOICE_ID", raising=False)
    opts = video.session_options("glitch_executor")
    assert opts["brand_kit_id"] == "bk_1" and "voice_id" not in opts


# ── credit preflight: PLAN CREDITS, not the USD wallet (renders bill credits: 26/clip) ──
async def test_preflight_raises_below_credit_floor(monkeypatch):
    monkeypatch.setattr(video, "credit_balance", lambda: _bal(10.0))
    with pytest.raises(video.HeyGenCreditError) as e:
        await video.preflight()
    assert "10" in str(e.value)


async def test_preflight_passes_on_a_healthy_credit_plan(monkeypatch):
    """Regression: the gate used to read the USD wallet, which sat at $1.05 on an account holding
    1,091 plan credits — it would have refused every render the plan could comfortably fund."""
    monkeypatch.setattr(video, "credit_balance", lambda: _bal(1091.0))
    await video.preflight()          # must not raise


async def test_preflight_proceeds_when_balance_unreadable(monkeypatch):
    # Fails OPEN on None: refusing every render on a transient profile-endpoint blip would be
    # worse than the underfunded-wallet case this guards.
    monkeypatch.setattr(video, "credit_balance", lambda: _bal(None))
    await video.preflight()


async def _bal(v):
    return v


async def test_generate_video_refuses_before_spending(monkeypatch):
    submitted = []

    async def _submit(prompt, file_urls, *, options=None):
        submitted.append(prompt)
        return "sess_1"

    async def _broke():
        raise video.HeyGenCreditError("wallet empty")

    with pytest.raises(video.HeyGenCreditError):
        await video.generate_video("ge", "p", [], submit=_submit, check_credit=_broke)
    assert submitted == []           # nothing was submitted, so nothing was billed


# ── happy path ──
async def test_generate_video_submits_polls_persists():
    seen = {}

    async def _submit(prompt, file_urls, *, options=None):
        seen["files"], seen["options"] = file_urls, options
        return "sess_1"

    async def _poll(session_id):
        seen["sess"] = session_id
        return "https://heygen/out.mp4"

    async def _persist(brand_id, url):
        return f"https://bucket/{brand_id}/out.mp4"

    out = await video.generate_video("ge", "prompt", ["https://a/1.png"], submit=_submit,
                                     poll=_poll, persist_url=_persist, check_credit=_noop_credit,
                                     options={"brand_kit_id": "bk_1"})
    assert out == "https://bucket/ge/out.mp4"
    assert seen["sess"] == "sess_1" and seen["files"] == ["https://a/1.png"]
    assert seen["options"] == {"brand_kit_id": "bk_1"}


# ── failure reporting: never log `failed: ''` again ──
def test_reason_prefers_documented_failure_fields():
    s = {"messages": [{"role": "model", "type": "text", "content": "ignore me"}]}
    v = {"failure_code": "insufficient_credit", "failure_message": "no funds"}
    assert video._reason(s, v) == "insufficient_credit no funds"


def test_reason_falls_back_to_error_message():
    # Live probe: a genuinely failed session and its video carried NEITHER documented field.
    s = {"messages": [{"role": "model", "type": "error", "content": "avatar lookup failed"}]}
    assert "avatar lookup failed" in video._reason(s, {})


def test_reason_falls_back_to_last_model_text():
    s = {"messages": [{"role": "model", "type": "text", "content": "I'm on it! Finding an avatar"}]}
    r = video._reason(s, {})
    assert "no failure detail" in r and "Finding an avatar" in r


def test_reason_is_never_empty():
    assert video._reason({}, {}).strip()


# ── poll: the SESSION is the authority, not the video ──
def _mock_heygen(monkeypatch, routes):
    """Serve `routes` (path-substring -> json body) to whatever httpx client `video` builds."""
    import httpx

    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        for frag, body in routes.items():
            if frag in str(request.url):
                return httpx.Response(200, json={"data": body})
        return httpx.Response(404, json={"data": {}})

    def factory(*a, **kw):
        kw.pop("transport", None)
        return real(*a, transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


async def _no_sleep(_s):
    return None


async def test_poll_fails_fast_when_session_dies_before_a_video_id(monkeypatch):
    """The 2026-09-01/02 shape: status `failed`, `progress` 0, `video_id` never assigned.

    Polling only the video meant spinning out the entire timeout on an already-dead run.
    """
    _mock_heygen(monkeypatch, {"/video-agents/": {
        "status": "failed", "progress": 0, "video_id": None,
        "messages": [{"role": "model", "type": "text", "content": "I'm on it! Finding an avatar"}],
    }})
    with pytest.raises(video.HeyGenError) as e:
        await video._default_poll("sess_1", sleep=_no_sleep, timeout_s=600)
    assert "failed" in str(e.value) and "Finding an avatar" in str(e.value)


async def test_poll_raises_on_unattended_waiting_for_input(monkeypatch):
    # `waiting_for_input` only resolves if somebody answers; a cron run never will.
    _mock_heygen(monkeypatch, {"/video-agents/": {
        "status": "waiting_for_input", "progress": 50, "video_id": None, "messages": [],
    }})
    with pytest.raises(video.HeyGenError) as e:
        await video._default_poll("sess_1", sleep=_no_sleep, timeout_s=600)
    assert "waiting for input" in str(e.value)


async def test_poll_returns_url_on_completion(monkeypatch):
    _mock_heygen(monkeypatch, {
        "/video-agents/": {"status": "completed", "progress": 100, "video_id": "v1", "messages": []},
        "/videos/": {"status": "completed", "video_url": "https://heygen/out.mp4"},
    })
    assert await video._default_poll("s", sleep=_no_sleep) == "https://heygen/out.mp4"


async def test_poll_surfaces_video_failure_code(monkeypatch):
    _mock_heygen(monkeypatch, {
        "/video-agents/": {"status": "generating", "video_id": "v1", "messages": []},
        "/videos/": {"status": "failed", "failure_code": "content_policy_violation",
                     "failure_message": "blocked"},
    })
    with pytest.raises(video.HeyGenError) as e:
        await video._default_poll("s", sleep=_no_sleep, timeout_s=60)
    assert "content_policy_violation" in str(e.value)
