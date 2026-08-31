from glitch_signal.agent.cron import capabilities


async def test_social_capability_registered_and_calls_run_campaign(monkeypatch):
    assert "social_campaign" in capabilities.names()
    seen = {}

    async def _fake_run(brand_id, **k):
        seen["brand"] = brand_id

        class R:  # minimal CampaignResult stand-in
            idea = None
            posts = []
            skipped_reason = "test"

        return R()

    monkeypatch.setattr("glitch_signal.agent.social.campaign.run_campaign", _fake_run)
    fn = capabilities.get("social_campaign")
    out = await fn("ge", {})
    assert seen["brand"] == "ge" and isinstance(out, dict)
