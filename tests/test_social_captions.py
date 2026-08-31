from glitch_signal.agent.social import captions
from glitch_signal.agent.social.spec import Idea


async def test_write_captions_returns_two_variants():
    calls = []
    async def _complete(prompt, *, system=None, model=None, tier=None, timeout_s=90):
        calls.append(prompt)
        return "Trade the plan, not the P&L. #propfirm"
    idea = Idea(angle="risk", hook="Blow-ups are optional", key_points=["stops"], dedup_key="k")
    out = await captions.write_captions("ge", idea, complete=_complete)
    assert set(out) == {"image", "video"}
    assert all(0 < len(v) <= 2200 for v in out.values())
    assert len(calls) >= 2    # one per variant
