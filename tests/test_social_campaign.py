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
        async def reserve_campaign(self, b, idea, **k): return "camp-1"
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


async def test_reserve_conflict_skips_before_paid_work(monkeypatch):
    """HARDEN #1: a DB dedup conflict at reserve time skips cleanly and does NO paid work."""
    monkeypatch.setattr(campaign, "_social_on", lambda: True)
    class _Store:
        async def recent_dedup_keys(self, b, **k): return set()
        async def reserve_campaign(self, b, idea, **k): return None       # unique(brand,dedup) conflict
        async def finalize_campaign(self, cid, status, cost, **k): pass
    async def boom(brand_id, idea): raise AssertionError("paid work ran despite dedup conflict")
    d = _deps(store_mod=_Store())
    d.generate_image = boom
    d.generate_video = boom
    res = await campaign.run_campaign("ge", deps=d)
    assert res.skipped_reason == "duplicate idea (already reserved)" and not res.posts


async def test_budget_recheck_skips_video(monkeypatch):
    """HARDEN #5: the per-action budget re-check skips the (paid) video when the cap is hit,
    preserving image-only progress."""
    monkeypatch.setattr(campaign, "_social_on", lambda: True)
    seq = iter([(True, ""), (True, ""), (False, "over cap")])   # precondition, image ok, video denied
    async def budget_check(brand_id, **k): return next(seq)
    vid = {"n": 0}
    async def gen_vid(brand_id, idea):
        vid["n"] += 1
        return "v"
    res = await campaign.run_campaign("ge", deps=_deps(budget_check=budget_check, generate_video=gen_vid))
    assert vid["n"] == 0
    assert {p.platform for p in res.posts} == {"x", "linkedin", "facebook"}   # image-only


async def test_caption_failure_finalizes_paid_campaign(monkeypatch):
    """HARDEN #7: a caption/fact failure after paid media still finalizes the campaign (failed +
    reason), never aborts without recording the paid work."""
    monkeypatch.setattr(campaign, "_social_on", lambda: True)
    finals: dict = {}
    class _Store:
        async def recent_dedup_keys(self, b, **k): return set()
        async def reserve_campaign(self, b, idea, **k): return "camp-1"
        async def finalize_campaign(self, cid, status, cost, **k):
            finals["status"] = status
            finals["reason"] = k.get("failure_reason")
    async def captions(brand_id, idea, **k): raise RuntimeError("caption LLM down")
    res = await campaign.run_campaign("ge", deps=_deps(captions=captions, store_mod=_Store()))
    assert res.skipped_reason and "caption/facts failed" in res.skipped_reason
    assert finals["status"] == "failed" and "caption" in (finals["reason"] or "")
    assert not res.posts


# ── dry run: produce the creative, never publish ────────────────────────────────────────────────
async def test_dry_run_never_calls_fan_out(monkeypatch):
    """The safety property is STRUCTURAL, not conditional: a preview must not be able to reach a
    platform in any flag state, so fan_out is simply never called."""
    monkeypatch.setattr(campaign, "_social_enabled", lambda: True)
    async def boom(*a, **k):
        raise AssertionError("fan_out ran during a dry run")
    res = await campaign.run_campaign("ge", deps=_deps(fan_out=boom), dry_run=True)
    assert res.posts == [] and res.image_url == "https://cdn/img.png"


async def test_dry_run_does_not_reserve_or_burn_the_dedup_key(monkeypatch):
    """Previewing an idea must leave it available for the real run."""
    monkeypatch.setattr(campaign, "_social_enabled", lambda: True)
    calls = {"reserve": 0, "finalize": 0}
    class _Store:
        async def recent_dedup_keys(self, b, **k): return set()
        async def reserve_campaign(self, b, idea, **k):
            calls["reserve"] += 1
            return "camp-1"
        async def finalize_campaign(self, cid, status, cost, **k):
            calls["finalize"] += 1
    await campaign.run_campaign("ge", deps=_deps(store_mod=_Store()), dry_run=True)
    assert calls == {"reserve": 0, "finalize": 0}


async def test_dry_run_still_runs_while_publishing_is_disabled(monkeypatch):
    """The whole point of a preview is judging output BEFORE enabling publishing."""
    monkeypatch.setattr(campaign, "_social_on", lambda: False)        # publish gate CLOSED
    monkeypatch.setattr(campaign, "_social_enabled", lambda: True)    # social switch open
    res = await campaign.run_campaign("ge", deps=_deps(), dry_run=True)
    assert res.image_url and res.posts == []


async def test_dry_run_is_off_by_default(monkeypatch):
    """A normal run must be unaffected — publishing still happens when it is meant to."""
    monkeypatch.setattr(campaign, "_social_on", lambda: True)
    res = await campaign.run_campaign("ge", deps=_deps())
    assert len(res.posts) == 5


class _FetchResp:
    def __init__(self, content, status=200):
        self.content = content
        self.status_code = status

    def raise_for_status(self):
        pass


class _FetchClient:
    def __init__(self, content):
        self._content = content

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **k):
        return _FetchResp(self._content)


async def test_fetch_image_returns_none_for_corrupt_image_bytes(monkeypatch):
    """Image.open() only reads the header — it does not decode pixels — so a download truncated
    mid-file still opens successfully and must be caught HERE, inside the fail-soft fetch, not left
    to raise later during layout rendering (which would abort the whole card instead of degrading
    to no logo)."""
    from io import BytesIO

    from PIL import Image as _Image

    buf = BytesIO()
    _Image.new("RGB", (200, 200), (10, 20, 30)).save(buf, format="PNG")
    truncated = buf.getvalue()[: len(buf.getvalue()) // 2]     # valid header, missing pixel data

    monkeypatch.setattr("httpx.AsyncClient", lambda **k: _FetchClient(truncated))
    result = await campaign._fetch_image("https://cdn.example/broken.png")
    assert result is None


async def test_fetch_image_returns_a_usable_image_on_success(monkeypatch):
    from io import BytesIO

    from PIL import Image as _Image

    buf = BytesIO()
    _Image.new("RGBA", (16, 16), (1, 2, 3, 255)).save(buf, format="PNG")
    monkeypatch.setattr("httpx.AsyncClient", lambda **k: _FetchClient(buf.getvalue()))
    result = await campaign._fetch_image("https://cdn.example/good.png")
    assert result is not None
    assert result.size == (16, 16)
