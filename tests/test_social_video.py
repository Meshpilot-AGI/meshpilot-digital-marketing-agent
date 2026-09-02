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


def test_style_paragraph_has_all_six_parts_heygen_asks_for():
    """HeyGen's prescribed anatomy: name, palette, art direction, motion, transitions, vibe.

    Hyperframes authors every scene in code rather than picking a template, so describing the look
    is the lever that actually moves the output — their guide says to spend the prompt here.
    """
    para = video.style_paragraph(None, {"bg": "#0a0d12", "fg": "#FFFFFF", "accent": "#93FF00"})
    for part in ("STYLE", "Palette:", "Art direction:", "Motion:", "Transitions:", "Vibe:"):
        assert part in para, f"style paragraph is missing {part!r}"


def test_style_paragraph_uses_the_brands_own_tokens():
    # Same bg/fg/accent the image cards render with, so a campaign's post and video agree.
    para = video.style_paragraph(None, {"bg": "#111111", "fg": "#EEEEEE", "accent": "#FF0090"})
    assert "#111111" in para and "#EEEEEE" in para and "#FF0090" in para


def test_style_paragraph_falls_back_to_neutral_defaults():
    # Open-core: an unconfigured brand must still get a usable look, with no brand baked in.
    para = video.style_paragraph(None, None)
    assert "Palette:" in para and "#" in para


def test_style_paragraph_is_positively_framed():
    """Restrictive instructions made HeyGen's own test renders visually flat, so a look is pinned
    by describing what IS there."""
    para = video.style_paragraph(None, None).lower()
    for banned in ("do not", "don't", "avoid", "never use", " no ", "without any"):
        assert banned not in para, f"style paragraph uses restrictive framing: {banned!r}"


def test_build_video_prompt_carries_the_style_paragraph():
    p = video.build_video_prompt(IDEA, tokens={"accent": "#93FF00"})
    assert "STYLE" in p and "#93FF00" in p


def test_build_video_prompt_takes_presenter_and_audience_from_the_brand():
    """Both were hardcoded ("a working trader", "one male presenter in his early thirties"), which
    made every brand a prop-firm brand. They now come from the brand's positioning row."""
    from glitch_signal.agent.social.plan import BrandVoice

    voice = BrandVoice.from_brand(
        {"audience": "new parents choosing a pram", "presenter": "one woman in her forties"}, {})
    p = video.build_video_prompt(IDEA, voice=voice)
    assert "new parents choosing a pram" in p
    assert "one woman in her forties" in p
    assert "trader" not in p.lower() and "trading" not in p.lower()


def test_build_video_prompt_has_a_neutral_presenter_default():
    p = video.build_video_prompt(IDEA)
    assert "trading" not in p.lower() and "male presenter" not in p.lower()

def test_build_video_prompt_respects_the_10k_cap():
    long_idea = Idea("risk", "Hook", ["point " * 400] * 20, "k")
    assert len(video.build_video_prompt(long_idea)) <= 10_000


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


async def test_poll_returns_url_on_completion(monkeypatch):
    _mock_heygen(monkeypatch, {
        "/video-agents/": {"status": "completed", "progress": 100, "video_id": "v1", "messages": []},
        "/videos/": {"status": "completed", "video_url": "https://heygen/out.mp4"},
    })
    assert await video._default_poll("s", sleep=_no_sleep) == "https://heygen/out.mp4"


async def test_poll_resumes_a_failed_session_instead_of_abandoning_it(monkeypatch):
    """`failed` is TRANSIENT. Observed live: failed -> thinking -> generating -> completed.

    Raising on the first `failed` is what produced a month of empty campaigns — the render carried
    on vendor-side and completed with nobody listening.
    """
    import httpx

    states = [
        {"status": "failed", "progress": 0, "video_id": None, "messages": []},
        {"status": "thinking", "progress": 0, "video_id": "v1", "messages": []},
        {"status": "generating", "progress": 31, "video_id": "v1", "messages": []},
        {"status": "completed", "progress": 100, "video_id": "v1", "messages": []},
    ]
    pos = {"i": 0}
    resumed = []

    async def _resume(sid):
        resumed.append(sid)

    def handler(request):
        if "/video-agents/" in str(request.url):
            cur = states[min(pos["i"], len(states) - 1)]
            pos["i"] += 1                      # advance on every poll, like the real session
            return httpx.Response(200, json={"data": cur})
        done = pos["i"] >= len(states)
        return httpx.Response(200, json={"data": {
            "status": "completed" if done else "processing",
            "video_url": "https://heygen/out.mp4" if done else None}})

    real = httpx.AsyncClient

    def factory(*a, **kw):
        kw.pop("transport", None)
        return real(*a, transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    out = await video._default_poll("s1", sleep=_no_sleep, timeout_s=300, resume=_resume)
    assert out == "https://heygen/out.mp4"
    assert resumed == ["s1"]          # nudged once out of `failed`, then it recovered on its own


async def test_poll_gives_up_after_the_resume_budget(monkeypatch):
    _mock_heygen(monkeypatch, {"/video-agents/": {
        "status": "failed", "progress": 0, "video_id": None,
        "messages": [{"role": "model", "type": "error", "content": "hard stop"}]}})
    tries = []

    async def _resume(sid):
        tries.append(sid)

    with pytest.raises(video.HeyGenError) as e:
        await video._default_poll("s1", sleep=_no_sleep, timeout_s=600, resume=_resume,
                                  max_resumes=2)
    assert len(tries) == 2 and "2 resume attempts" in str(e.value)
    assert "hard stop" in str(e.value)


def test_campaign_attaches_no_files_to_a_render():
    """Operator, 2026-09-02: stop attaching platform screenshots and logos.

    HeyGen does not treat `files` as style reference — it drops the literal images into the B-roll,
    so posts came back showing raw product screenshots and other companies' marks. Brand identity
    comes from `brand_kit_id` instead. This asserts the pipeline sends an empty attachment list, so
    the behaviour cannot creep back in.
    """
    import inspect

    from glitch_signal.agent.social import campaign

    src = inspect.getsource(campaign._default_deps)
    assert "reference_urls" not in src, "the video path must not attach reference files"
    assert "video.generate_video(brand_id, prompt, []," in src, "file_urls must be an empty list"


async def test_poll_nudges_a_session_stalled_in_a_healthy_looking_state(monkeypatch):
    """A session sat in `thinking` at progress 0 for 25+ minutes — no `failed`, so nudging only on
    `failed`/`waiting_for_input` never touched it and it just burned the deadline."""
    import httpx

    calls = {"n": 0}
    resumed = []

    async def _resume(sid):
        resumed.append(sid)

    def handler(request):
        if "/video-agents/" in str(request.url):
            calls["n"] += 1
            # Never moves: same status, same progress, no video_id.
            return httpx.Response(200, json={"data": {
                "status": "thinking", "progress": 0, "video_id": None, "messages": []}})
        return httpx.Response(200, json={"data": {"status": "processing"}})

    real = httpx.AsyncClient

    def factory(*a, **kw):
        kw.pop("transport", None)
        return real(*a, transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    with pytest.raises(video.HeyGenError) as e:
        await video._default_poll("s1", sleep=_no_sleep, timeout_s=3000, resume=_resume,
                                  max_resumes=2, stall_s=100)
    assert resumed == ["s1", "s1"]                  # nudged on the stall, not on a status word
    assert "no progress for" in str(e.value)


async def test_poll_does_not_nudge_a_slow_but_moving_render(monkeypatch):
    """A real render sat in `thinking` for 285s before moving. Progress that CHANGES is healthy —
    nudging it would interrupt a working render."""
    import httpx

    progress = {"p": 0}
    resumed = []

    async def _resume(sid):
        resumed.append(sid)

    def handler(request):
        if "/video-agents/" in str(request.url):
            progress["p"] += 1                       # moves every poll, slowly
            done = progress["p"] > 12
            return httpx.Response(200, json={"data": {
                "status": "completed" if done else "generating",
                "progress": progress["p"], "video_id": "v1", "messages": []}})
        done = progress["p"] > 12
        return httpx.Response(200, json={"data": {
            "status": "completed" if done else "processing",
            "video_url": "https://heygen/out.mp4" if done else None}})

    real = httpx.AsyncClient

    def factory(*a, **kw):
        kw.pop("transport", None)
        return real(*a, transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    out = await video._default_poll("s1", sleep=_no_sleep, timeout_s=3000, resume=_resume,
                                    stall_s=30)
    assert out == "https://heygen/out.mp4"
    assert resumed == []                             # never interrupted


# ── captions: most social video is watched muted ──
def test_caption_line_asks_for_one_word_synced_track():
    """Renders carried a persistent headline card but no word-synced track, so the spoken argument
    was lost with the sound off — which is how most of the feed watches."""
    line = video.caption_line({"accent": "#93FF00"})
    assert "single word-by-word" in line
    assert "#93FF00" in line                      # accent from the brand's own tokens
    assert "safe area" in line                    # platform UI must not cover it


def test_caption_line_separates_captions_from_headline_cards_by_position():
    """The v1 UGC lane found that asking for a word-by-word track AND beat overlays renders both at
    once and they collide. Separating them by POSITION keeps both — the headline cards are part of
    the look — without a prohibition, which would break the positive-framing rule."""
    line = video.caption_line(None).lower()
    assert "lower third" in line and "upper two-thirds" in line
    for banned in ("do not", "don't", "avoid", "never", " no "):
        assert banned not in line, f"caption spec uses restrictive framing: {banned!r}"


def test_build_video_prompt_carries_the_caption_spec():
    p = video.build_video_prompt(IDEA, tokens={"accent": "#93FF00"})
    assert "word-by-word" in p and "safe area" in p
