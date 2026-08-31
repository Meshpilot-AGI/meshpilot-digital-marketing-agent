from __future__ import annotations

from dataclasses import dataclass, field

# Fixed media mapping (spec): one image fans to these, one video fans to those.
IMAGE_PLATFORMS = ("x", "linkedin", "facebook")
VIDEO_PLATFORMS = ("tiktok", "instagram")
IMAGE_RECIPE = "higgsfield-soul-image"     # existing Higgsfield recipe (image)
# NB: video is produced by the HeyGen Video Agent client (agent/social/video.py), NOT a
# media-factory recipe — so there is no VIDEO_RECIPE constant.


@dataclass(frozen=True)
class Idea:
    angle: str
    hook: str
    key_points: list[str]
    dedup_key: str


@dataclass(frozen=True)
class PostDraft:
    platform: str
    media_kind: str        # "image" | "video"
    media_url: str
    caption: str


@dataclass
class PlatformResult:
    platform: str
    status: str            # posted | held | failed | skipped
    verdict: str | None = None
    platform_post_id: str | None = None
    post_url: str | None = None
    error: str | None = None


@dataclass
class CampaignResult:
    idea: Idea | None
    image_url: str | None
    video_url: str | None
    posts: list[PlatformResult] = field(default_factory=list)
    cost_usd: float = 0.0
    skipped_reason: str | None = None
