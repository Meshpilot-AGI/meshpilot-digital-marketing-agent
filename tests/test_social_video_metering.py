"""REVIEW #2 / #5: a locally timed-out HeyGen render is still running (and billed) vendor-side."""
import asyncio

import pytest

from glitch_signal.agent.social import campaign, video


async def _funded():
    """Skip the wallet preflight — these tests are about metering, not funding."""
    return None


async def test_meters_at_accept_not_after_the_poll(monkeypatch):
    """The caller bounds generate_video with asyncio.wait_for. Metering after the poll therefore
    LOSES the spend of every render we time out on — HeyGen bills from acceptance."""
    metered: list[tuple[str, str]] = []

    async def _meter(brand_id, session_id):
        metered.append((brand_id, session_id))

    monkeypatch.setattr(video, "_meter", _meter)

    async def submit(prompt, urls, *, options=None):
        return "sess-1"

    async def poll(session_id):
        await asyncio.sleep(10)        # never completes within the caller's deadline
        return "http://never"

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            video.generate_video("ge", "p", [], submit=submit, poll=poll, check_credit=_funded), timeout=0.05)

    # The render was accepted and charged — the spend is attributed even though we abandoned it.
    assert metered == [("ge", "sess-1")]


async def test_on_session_hook_fires_at_accept(monkeypatch):
    """usage_events (via _meter, request_id=session_id) is the durable reconcile handle; on_session
    gives an in-process caller the same id without waiting for the poll."""
    monkeypatch.setattr(video, "_meter", lambda *a, **k: _noop())
    seen: list[str] = []

    async def submit(prompt, urls, *, options=None):
        return "sess-2"

    async def poll(session_id):
        return "http://done"

    async def persist(brand_id, url):
        return "http://stored"

    out = await video.generate_video("ge", "p", [], submit=submit, poll=poll, check_credit=_funded,
                                     persist_url=persist, on_session=seen.append)
    assert seen == ["sess-2"] and out == "http://stored"


async def _noop():
    return None


def test_video_deadline_is_clamped_under_the_cron_capability_cap(monkeypatch):
    """REVIEW #5: a configured timeout at/above the capability cap defeats the fail-soft fallback —
    the outer cron wait_for kills the whole run before we can demote to image-only."""
    from glitch_signal.agent.cron.service import CAPABILITY_TIMEOUT_S

    class _S:
        agent_social_video_timeout_s = 99_999

    monkeypatch.setattr(campaign, "settings", lambda: _S(), raising=False)
    monkeypatch.setattr("glitch_signal.config.settings", lambda: _S())
    assert campaign._video_deadline_s() < CAPABILITY_TIMEOUT_S


def test_sane_configured_timeout_is_left_alone(monkeypatch):
    class _S:
        agent_social_video_timeout_s = 300

    monkeypatch.setattr("glitch_signal.config.settings", lambda: _S())
    assert campaign._video_deadline_s() == 300


def test_absurdly_small_timeout_is_floored(monkeypatch):
    class _S:
        agent_social_video_timeout_s = 0

    monkeypatch.setattr("glitch_signal.config.settings", lambda: _S())
    assert campaign._video_deadline_s() == campaign._VIDEO_DEADLINE_MIN_S
