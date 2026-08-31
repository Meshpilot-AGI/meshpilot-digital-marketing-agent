from glitch_signal.agent.social.spec import (
    IMAGE_PLATFORMS,
    IMAGE_RECIPE,
    VIDEO_PLATFORMS,
    CampaignResult,
    Idea,
    PlatformResult,
)


def test_platform_partition_covers_five_no_youtube():
    all_platforms = set(IMAGE_PLATFORMS) | set(VIDEO_PLATFORMS)
    assert all_platforms == {"x", "linkedin", "facebook", "tiktok", "instagram"}
    assert "youtube" not in all_platforms
    assert set(IMAGE_PLATFORMS).isdisjoint(VIDEO_PLATFORMS)  # each platform one medium


def test_dataclasses_construct():
    idea = Idea(angle="a", hook="h", key_points=["p"], dedup_key="k")
    r = CampaignResult(idea=idea, image_url=None, video_url=None, posts=[])
    assert r.cost_usd == 0.0 and r.skipped_reason is None
    pr = PlatformResult(platform="x", status="posted")
    assert pr.verdict is None and pr.error is None
    assert IMAGE_RECIPE == "higgsfield-soul-image"
