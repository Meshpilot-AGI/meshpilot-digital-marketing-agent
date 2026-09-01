from __future__ import annotations

from dataclasses import dataclass, field

# Fixed media mapping (spec): one image fans to these, one video fans to those.
IMAGE_PLATFORMS = ("x", "linkedin", "facebook")
VIDEO_PLATFORMS = ("tiktok", "instagram")
# The image model for the conceptual/poster routes. nano-banana renders legible type and holds a
# consistent look across unrelated topics when given the brand's art direction — verified live on
# this account against the old Higgsfield path, which produced generic stock from a bare brief.
IMAGE_MODEL = "nano-banana-pro"
# NB: video is produced by the HeyGen Video Agent client (agent/social/video.py), NOT a
# media-factory recipe — so there is no VIDEO_RECIPE constant.


@dataclass(frozen=True)
class Idea:
    angle: str
    hook: str
    key_points: list[str]
    dedup_key: str
    # What KIND of post this is — the agent decides, and `plan.route_for` turns it into a renderer.
    # Routing on the content rather than defaulting to one path is what keeps the pipeline from
    # being hardcoded to a single creative treatment.
    asset_kind: str = "statement"


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


def derive_status(posts: list[PlatformResult]) -> str:
    """Aggregate campaign status from the FULL result set (fixes 'all-failed → held').

    `pending` (Buffer 'sending', not yet reconciled to terminal) counts as delivered-in-flight,
    not a failure. Returns one of: posted | pending | held | failed | partial | mixed | skipped.
    """
    if not posts:
        return "skipped"
    total = len(posts)
    n = {s: sum(1 for p in posts if p.status == s)
         for s in ("posted", "pending", "held", "failed", "skipped")}
    for uniform in ("posted", "pending", "held", "failed", "skipped"):
        if n[uniform] == total:
            return uniform
    delivered = n["posted"] + n["pending"]          # in-flight or done, not failed/held
    if delivered and delivered < total:
        return "partial"                             # some delivered, some held/failed/skipped
    return "mixed"                                    # only non-delivered outcomes, but not uniform
