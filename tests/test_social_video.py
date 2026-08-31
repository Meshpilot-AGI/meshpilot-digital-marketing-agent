from glitch_signal.agent.social import video
from glitch_signal.agent.social.spec import Idea


def test_build_video_prompt_is_portrait_positive():
    p = video.build_video_prompt(Idea("risk", "Blow-ups are optional", ["use stops"], "k"))
    assert "portrait" in p.lower()
    assert "no b-roll" not in p.lower()          # positive framing only
    assert "Blow-ups are optional" in p


def test_reference_urls_splits_env(monkeypatch):
    monkeypatch.setenv("GE_SOCIAL_REFERENCE_URLS", "https://a/1.png, https://a/2.png")
    urls = video.reference_urls("glitch_executor")   # ENV_PREFIX for glitch_executor is GE
    assert urls == ["https://a/1.png", "https://a/2.png"]


async def test_generate_video_submits_polls_persists():
    seen = {}
    async def _submit(prompt, file_urls): seen["files"] = file_urls; return "sess_1"
    async def _poll(session_id): seen["sess"] = session_id; return "https://heygen/out.mp4"
    async def _persist(brand_id, url): return f"https://bucket/{brand_id}/out.mp4"
    out = await video.generate_video("ge", "prompt", ["https://a/1.png"],
                                     submit=_submit, poll=_poll, persist_url=_persist)
    assert out == "https://bucket/ge/out.mp4"
    assert seen["sess"] == "sess_1" and seen["files"] == ["https://a/1.png"]
