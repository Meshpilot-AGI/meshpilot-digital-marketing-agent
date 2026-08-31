from glitch_signal.agent.social import campaign
from glitch_signal.agent.social.spec import Idea, PlatformResult


def _deps(**over):
    async def ideate(brand_id, **k): return Idea("a", "h", ["p"], "k1")
    async def captions(brand_id, idea, **k): return {"image": "ci", "video": "cv"}
    async def gen_img(brand_id, idea): return "https://cdn/img.png"
    async def gen_vid(brand_id, idea): return "https://cdn/vid.mp4"
    async def review(goal, output, *, facts="", **k): return {"verdict": "pass", "notes": ""}
    async def brand_facts(brand_id, **k): return ""
    async def budget_check(brand_id, **k): return (True, "")
    async def fan_out(brand_id, cid, drafts, verdicts, **k):
        return [PlatformResult(platform=d.platform, status="posted") for d in drafts]
    class _Store:
        async def recent_dedup_keys(self, b, **k): return set()
        async def create_campaign(self, b, idea, **k): return "camp-1"
        async def finalize_campaign(self, cid, status, cost, **k): self.final = (status, cost)
    async def spend_now(brand_id): return 0.0
    d = campaign.RunDeps(ideate=ideate, captions=captions, generate_image=gen_img,
                         generate_video=gen_vid, review=review, brand_facts=brand_facts,
                         budget_check=budget_check, fan_out=fan_out, store_mod=_Store(),
                         remember=lambda *a, **k: None,
                         have_constitution=lambda: True, spend_now=spend_now)
    for key, val in over.items():
        setattr(d, key, val)
    return d


async def test_preconditions_off_is_noop(monkeypatch):
    monkeypatch.setattr(campaign, "_social_on", lambda: False)
    res = await campaign.run_campaign("ge", deps=_deps())
    assert res.skipped_reason and not res.posts


async def test_happy_path_posts_five(monkeypatch):
    monkeypatch.setattr(campaign, "_social_on", lambda: True)
    res = await campaign.run_campaign("ge", deps=_deps())
    assert len(res.posts) == 5 and {p.platform for p in res.posts} == {
        "x", "linkedin", "facebook", "tiktok", "instagram"}


async def test_escalate_holds(monkeypatch):
    monkeypatch.setattr(campaign, "_social_on", lambda: True)
    async def review(goal, output, *, facts="", **k): return {"verdict": "escalate", "notes": "no"}
    async def fan_out(brand_id, cid, drafts, verdicts, **k):
        return [PlatformResult(platform=d.platform,
                               status="held" if verdicts[d.platform] == "escalate" else "posted")
                for d in drafts]
    res = await campaign.run_campaign("ge", deps=_deps(review=review, fan_out=fan_out))
    assert all(p.status == "held" for p in res.posts)


async def test_dedup_skips(monkeypatch):
    monkeypatch.setattr(campaign, "_social_on", lambda: True)
    async def ideate(brand_id, **k): return None    # collided/none
    res = await campaign.run_campaign("ge", deps=_deps(ideate=ideate))
    assert res.skipped_reason == "no fresh idea" and not res.posts


async def test_both_media_fail_skips(monkeypatch):
    monkeypatch.setattr(campaign, "_social_on", lambda: True)
    async def boom(brand_id, idea): raise RuntimeError("engine down")
    res = await campaign.run_campaign("ge", deps=_deps(generate_image=boom, generate_video=boom))
    assert res.skipped_reason == "media generation failed" and not res.posts


async def test_conscience_empty_verdict_holds_when_constitution_loaded(monkeypatch):
    """FIX 1 (CRITICAL): {} from the critic (LLM error/unparseable/no constitution-loaded-but-
    somehow-empty) must HOLD every post when a constitution IS loaded — never fall through to
    'pass' and publish ungated content."""
    monkeypatch.setattr(campaign, "_social_on", lambda: True)
    async def review(goal, output, *, facts="", **k): return {}
    def fan_out_records(calls):
        async def fan_out(brand_id, cid, drafts, verdicts, **k):
            calls.append(verdicts)
            return [PlatformResult(platform=d.platform,
                                   status="held" if verdicts[d.platform] != "pass" else "posted")
                    for d in drafts]
        return fan_out
    calls: list[dict] = []
    res = await campaign.run_campaign(
        "ge", deps=_deps(review=review, have_constitution=lambda: True, fan_out=fan_out_records(calls)))
    assert all(p.status == "held" for p in res.posts)
    assert all(v == "escalate" for v in calls[0].values())


async def test_conscience_review_raises_holds_when_constitution_loaded(monkeypatch):
    """FIX 1 (CRITICAL): a critic exception (timeout/rate-limit/model-access failure) with a
    constitution loaded must HOLD, not publish."""
    monkeypatch.setattr(campaign, "_social_on", lambda: True)
    async def review(goal, output, *, facts="", **k): raise RuntimeError("critic timeout")
    async def fan_out(brand_id, cid, drafts, verdicts, **k):
        return [PlatformResult(platform=d.platform,
                               status="held" if verdicts[d.platform] != "pass" else "posted")
                for d in drafts]
    res = await campaign.run_campaign(
        "ge", deps=_deps(review=review, have_constitution=lambda: True, fan_out=fan_out))
    assert all(p.status == "held" for p in res.posts)


async def test_no_constitution_passes_without_calling_review(monkeypatch):
    """No constitution loaded → documented allow (verdict='pass'), and the critic is never called."""
    monkeypatch.setattr(campaign, "_social_on", lambda: True)
    calls = {"n": 0}
    async def review(goal, output, *, facts="", **k):
        calls["n"] += 1
        return {"verdict": "escalate", "notes": "should never run"}
    res = await campaign.run_campaign(
        "ge", deps=_deps(review=review, have_constitution=lambda: False))
    assert all(p.status == "posted" for p in res.posts)
    assert calls["n"] == 0


async def test_cost_usd_is_run_delta(monkeypatch):
    """FIX 2 (IMPORTANT): CampaignResult.cost_usd is the spend delta observed across the run,
    not a hardcoded 0.0."""
    monkeypatch.setattr(campaign, "_social_on", lambda: True)
    spends = iter([0.0, 1.5])
    async def spend_now(brand_id): return next(spends)
    res = await campaign.run_campaign("ge", deps=_deps(spend_now=spend_now))
    assert res.cost_usd == 1.5
