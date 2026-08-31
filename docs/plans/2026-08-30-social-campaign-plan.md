# SOCIAL-CAMPAIGN Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, conscience-gated `social_campaign` capability that finds one content idea for a brand, generates a Higgsfield image + a HeyGen video, and publishes one post to each of X, LinkedIn, TikTok (Buffer) + Facebook, Instagram (Meta) — no YouTube, no human in the loop — running on the existing self-cron.

**Architecture:** A Python orchestrator (`agent/social/`) calls the LLM only for the idea, captions, and the video prompt; everything exact/safe (media mapping, the conscience hold, per-platform fan-out, dedup, cost, idempotency) is deterministic code. Image = Higgsfield via the media factory; video = HeyGen **Video Agent** (prompt+files → B-roll/subtitles, no avatar) via a self-contained client. Ships inert behind `agent_social_enabled`.

**Tech Stack:** Python 3.11 / `uv`, FastAPI, SQLModel + Supabase-native SQL migrations, pytest (asyncio auto mode). Reuses the media factory (Higgsfield **image** recipe), `agent/loop/conscience.py`, `agent/memory/store.py`, `platforms/{buffer,facebook,instagram}.py`, `analytics/cost/budget.py`, `agent/loop/llm.py`, `agent/cron/capabilities.py`, `media/generation/storage` (bucket host for the HeyGen output). HeyGen **Video Agent** is called directly (self-contained client), not via the factory's avatar engine.

**Spec:** `docs/plans/2026-08-30-social-campaign.md` (read it — this plan implements it).

## Global Constraints

- Python **≥ 3.11**; dependency-manage with `uv` (`uv run pytest -q`, `uv run ruff check`).
- **No new prod flags flipped** in this lane. Ships **inert**: `agent_social_enabled` default `False`.
- Every commit **SSH-signed**, authored `Tejas Karan Agrawal <help.nuraveda@gmail.com>`. Lane branch `lane/social-campaign` off `production`; PR into `production`.
- All new DB tables enable **RLS** (deny-all, service-role only) and use naive-UTC (`datetime.now(timezone.utc)`), matching `supabase/migrations/` convention.
- Tests are **network-free**: inject fakes for LLM, media engines, conscience, publishers, budget, and DB (`FakeEngine` from `tests/test_agent_memory.py`). `asyncio_mode = "auto"` — plain `async def test_...`, no marker.
- **Conscience hard-gate**: verdict `escalate` → post is `held`, never published. LLM/critic errors resolve **toward not posting** (held).
- Media mapping is fixed: **video → TikTok + Instagram**, **image → X + LinkedIn + Facebook**.
- **Additive & isolated (do NOT hardcode the agent to this task).** This is ONE capability among many. Do **not** modify `agent/loop/runner.py`, scopes, the general tool registry, or any other capability. The only allowed shared-surface changes are the two config flags (Task 2), the one cron-registry entry (Task 9), and the one migration (Task 3). All other code lives under `src/glitch_signal/agent/social/`. Reuse shared building blocks (media factory, conscience, memory, publishers, budget, LLM) as-is — never special-case them for social. With the flag off, the agent behaves exactly as before.

---

### Task 1: Package skeleton + `spec.py` dataclasses

**Files:**
- Create: `src/glitch_signal/agent/social/__init__.py`
- Create: `src/glitch_signal/agent/social/spec.py`
- Test: `tests/test_social_spec.py`

**Interfaces:**
- Produces: `Idea(angle: str, hook: str, key_points: list[str], dedup_key: str)`; `PostDraft(platform: str, media_kind: str, media_url: str, caption: str)`; `PlatformResult(platform: str, status: str, verdict: str | None = None, platform_post_id: str | None = None, post_url: str | None = None, error: str | None = None)`; `CampaignResult(idea: Idea | None, image_url: str | None, video_url: str | None, posts: list[PlatformResult], cost_usd: float = 0.0, skipped_reason: str | None = None)`. Constants: `IMAGE_PLATFORMS = ("x", "linkedin", "facebook")`, `VIDEO_PLATFORMS = ("tiktok", "instagram")`, `IMAGE_RECIPE = "higgsfield-soul-image"`. (No `VIDEO_RECIPE` — video comes from the HeyGen Video Agent client in Task 4.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_social_spec.py
from glitch_signal.agent.social.spec import (
    Idea, PostDraft, PlatformResult, CampaignResult,
    IMAGE_PLATFORMS, VIDEO_PLATFORMS, IMAGE_RECIPE,
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_social_spec.py -q`
Expected: FAIL — `ModuleNotFoundError: glitch_signal.agent.social`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/glitch_signal/agent/social/__init__.py
"""SOCIAL-CAMPAIGN — deterministic, conscience-gated multi-platform posting."""
```

```python
# src/glitch_signal/agent/social/spec.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_social_spec.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/glitch_signal/agent/social/__init__.py src/glitch_signal/agent/social/spec.py tests/test_social_spec.py
git commit -m "feat(social): campaign dataclasses + fixed platform/media mapping"
```

---

### Task 2: Config flags

**Files:**
- Modify: `src/glitch_signal/config.py` (add two fields beside the other `agent_*` flags, ~line 300-328)
- Test: `tests/test_social_config.py`

**Interfaces:**
- Produces: `settings().agent_social_enabled: bool` (default `False`), `settings().agent_social_max_posts_per_run: int` (default `5`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_social_config.py
from glitch_signal.config import Settings


def test_social_flags_default_off_and_capped():
    s = Settings()
    assert s.agent_social_enabled is False              # ships inert
    assert s.agent_social_max_posts_per_run == 5        # the five platforms
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_social_config.py -q`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'agent_social_enabled'`.

- [ ] **Step 3: Write minimal implementation**

Add beside the existing `agent_*` flags in `config.py` (e.g. after `agent_conscience_enabled`):

```python
    # SOCIAL-CAMPAIGN — master switch (default OFF: ships inert) + per-run post cap (the 5 platforms).
    agent_social_enabled: bool = False
    agent_social_max_posts_per_run: int = 5
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_social_config.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/glitch_signal/config.py tests/test_social_config.py
git commit -m "feat(social): agent_social_enabled + per-run cap flags (default off)"
```

---

### Task 3: Migration + `store.py` (persistence, dedup, idempotency)

**Files:**
- Create: `supabase/migrations/20260831000000_social_campaign.sql`
- Create: `src/glitch_signal/agent/social/store.py`
- Test: `tests/test_social_store.py`

**Interfaces:**
- Consumes: `Idea`, `PlatformResult` (Task 1); `FakeEngine` (tests/test_agent_memory.py).
- Produces:
  - `async recent_dedup_keys(brand_id: str, *, limit: int = 20, engine=None) -> set[str]`
  - `async create_campaign(brand_id: str, idea: Idea, *, image_url: str | None, video_url: str | None, engine=None) -> str` (returns `campaign_id`)
  - `async already_posted(campaign_id: str, platform: str, *, engine=None) -> bool` (idempotency)
  - `async record_post(campaign_id: str, r: PlatformResult, media_kind: str, caption: str, *, engine=None) -> None`
  - `async finalize_campaign(campaign_id: str, status: str, cost_usd: float, *, engine=None) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_social_store.py
from glitch_signal.agent.social import store
from glitch_signal.agent.social.spec import Idea, PlatformResult
from tests.test_agent_memory import FakeEngine, _Result, _Row


async def test_create_campaign_inserts_and_returns_id():
    eng = FakeEngine()
    eng.queue(_Result(rows=[("camp-1",)]))
    idea = Idea(angle="a", hook="h", key_points=["p"], dedup_key="k1")
    cid = await store.create_campaign("ge", idea, image_url="u.png", video_url="v.mp4", engine=eng)
    assert cid == "camp-1"
    sql, params = eng.calls[0]
    assert "insert into social_campaign" in sql.lower()
    assert params["brand"] == "ge" and params["dedup_key"] == "k1"


async def test_recent_dedup_keys_returns_set():
    eng = FakeEngine()
    eng.queue(_Result(rows=[_Row({"dedup_key": "k1"}), _Row({"dedup_key": "k2"})]))
    keys = await store.recent_dedup_keys("ge", limit=10, engine=eng)
    assert keys == {"k1", "k2"}


async def test_already_posted_true_when_row_exists():
    eng = FakeEngine()
    eng.queue(_Result(rows=[("x",)]))
    assert await store.already_posted("camp-1", "x", engine=eng) is True


async def test_record_post_writes_row():
    eng = FakeEngine()
    eng.queue(_Result(rowcount=1))
    r = PlatformResult(platform="x", status="posted", verdict="pass",
                       platform_post_id="p1", post_url="http://x")
    await store.record_post("camp-1", r, media_kind="image", caption="c", engine=eng)
    sql, params = eng.calls[0]
    assert "insert into social_post" in sql.lower()
    assert params["platform"] == "x" and params["status"] == "posted"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_social_store.py -q`
Expected: FAIL — `ModuleNotFoundError: ...social.store`.

- [ ] **Step 3: Write the migration**

```sql
-- supabase/migrations/20260831000000_social_campaign.sql
-- SOCIAL-CAMPAIGN: coordinated multi-platform posts (dedup + per-platform idempotency).
create table if not exists social_campaign (
  id          uuid primary key default gen_random_uuid(),
  brand_id    text not null,
  dedup_key   text not null,
  idea        jsonb not null,
  image_url   text,
  video_url   text,
  status      text not null default 'draft',   -- draft|posted|partial|held|failed|skipped
  cost_usd    numeric,
  created_at  timestamptz not null default now()
);
create index if not exists social_campaign_brand_created on social_campaign (brand_id, created_at desc);
create index if not exists social_campaign_brand_dedup on social_campaign (brand_id, dedup_key);
alter table social_campaign enable row level security;

create table if not exists social_post (
  id               uuid primary key default gen_random_uuid(),
  campaign_id      uuid not null references social_campaign(id) on delete cascade,
  platform         text not null,
  media_kind       text not null,               -- image|video
  caption          text,
  verdict          text,                         -- pass|concerns|escalate
  status           text not null,                -- posted|held|failed|skipped
  platform_post_id text,
  post_url         text,
  error            text,
  created_at       timestamptz not null default now(),
  unique (campaign_id, platform)                 -- idempotency
);
alter table social_post enable row level security;
```

- [ ] **Step 4: Write minimal implementation**

```python
# src/glitch_signal/agent/social/store.py
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from sqlalchemy import text

from glitch_signal.agent.social.spec import Idea, PlatformResult
from glitch_signal.db.session import _engine


async def recent_dedup_keys(brand_id: str, *, limit: int = 20, engine: Any = None) -> set[str]:
    eng = engine or _engine()
    async with eng.connect() as conn:
        rows = (await conn.execute(
            text("SELECT dedup_key FROM social_campaign WHERE brand_id = :brand "
                 "ORDER BY created_at DESC LIMIT :k"),
            {"brand": brand_id, "k": limit})).fetchall()
    return {r._mapping["dedup_key"] if hasattr(r, "_mapping") else r[0] for r in rows}


async def create_campaign(brand_id: str, idea: Idea, *, image_url: str | None,
                          video_url: str | None, engine: Any = None) -> str:
    eng = engine or _engine()
    async with eng.begin() as conn:
        row = (await conn.execute(
            text("INSERT INTO social_campaign (brand_id, dedup_key, idea, image_url, video_url) "
                 "VALUES (:brand, :dedup_key, CAST(:idea AS jsonb), :image_url, :video_url) "
                 "RETURNING id"),
            {"brand": brand_id, "dedup_key": idea.dedup_key, "idea": json.dumps(asdict(idea)),
             "image_url": image_url, "video_url": video_url})).first()
    return str(row[0])


async def already_posted(campaign_id: str, platform: str, *, engine: Any = None) -> bool:
    eng = engine or _engine()
    async with eng.connect() as conn:
        row = (await conn.execute(
            text("SELECT 1 FROM social_post WHERE campaign_id = CAST(:cid AS uuid) "
                 "AND platform = :p AND status = 'posted' LIMIT 1"),
            {"cid": campaign_id, "p": platform})).first()
    return row is not None


async def record_post(campaign_id: str, r: PlatformResult, media_kind: str, caption: str,
                      *, engine: Any = None) -> None:
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(
            text("INSERT INTO social_post (campaign_id, platform, media_kind, caption, verdict, "
                 "status, platform_post_id, post_url, error) VALUES (CAST(:cid AS uuid), :platform, "
                 ":media_kind, :caption, :verdict, :status, :ppid, :url, :error) "
                 "ON CONFLICT (campaign_id, platform) DO NOTHING"),
            {"cid": campaign_id, "platform": r.platform, "media_kind": media_kind,
             "caption": caption, "verdict": r.verdict, "status": r.status,
             "ppid": r.platform_post_id, "url": r.post_url, "error": r.error})


async def finalize_campaign(campaign_id: str, status: str, cost_usd: float,
                            *, engine: Any = None) -> None:
    eng = engine or _engine()
    async with eng.begin() as conn:
        await conn.execute(
            text("UPDATE social_campaign SET status = :s, cost_usd = :c "
                 "WHERE id = CAST(:cid AS uuid)"),
            {"s": status, "c": cost_usd, "cid": campaign_id})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_social_store.py -q`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add supabase/migrations/20260831000000_social_campaign.sql src/glitch_signal/agent/social/store.py tests/test_social_store.py
git commit -m "feat(social): social_campaign/social_post tables + store (dedup, idempotency)"
```

---

### Task 4: `video.py` — HeyGen Video Agent client (no avatar)

**Files:**
- Create: `src/glitch_signal/agent/social/video.py`
- Test: `tests/test_social_video.py`

**Interfaces:**
- Consumes: `Idea` (Task 1); `config.brand_env`; `media/generation/storage.persist` (or `upload_bytes`) for bucket hosting; the cost meter.
- Produces:
  - `build_video_prompt(idea: Idea) -> str` — natural story + tone + `orientation: portrait`, positive framing (per HeyGen guidance: no timestamps, no questions, no "no B-roll").
  - `reference_urls(brand_id: str) -> list[str]` — from `brand_env("SOCIAL_REFERENCE_URLS")` (comma-separated), capped at 20.
  - `async generate_video(brand_id: str, prompt: str, file_urls: list[str], *, submit=None, poll=None, persist_url=None) -> str` — POST the Video Agent, poll to completion, persist the result to the brand bucket, return the durable URL. `submit`/`poll`/`persist_url` are injectable for tests (defaults use httpx + the real bucket).

> HeyGen Video Agent API (verified from developers.heygen.com): `POST https://api.heygen.com/v3/video-agents` with header `X-Api-Key: $HEYGEN_API_KEY`, body `{"prompt": <=10000 chars, "orientation": "portrait", "mode": "generate", "files": [{"type":"url","url":...}]}` → `{"data": {"session_id", "video_id": null, ...}}`. Poll `GET /v3/video-agents/{session_id}` until `data.video_id` is set, then `GET /v3/videos/{video_id}` until `data.status == "completed"` → `data.video_url`. Render takes ~5–10× the clip length (fine on a background run). Confirm exact response nesting against the live API during implementation.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_social_video.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_social_video.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# src/glitch_signal/agent/social/video.py
from __future__ import annotations

import asyncio
from typing import Any

import structlog

from glitch_signal.agent.social.spec import Idea

log = structlog.get_logger(__name__)

_API = "https://api.heygen.com/v3"
_MAX_FILES = 20


def build_video_prompt(idea: Idea) -> str:
    body = f"{idea.hook}. " + " ".join(idea.key_points)
    return (
        f"{body}\n\n"
        "Tone: confident, sharp, honest — a trader done with hype, talking straight to camera's "
        "audience. Energetic but grounded.\n"
        "Use the attached brand assets and product screenshots for on-brand B-roll and overlays.\n"
        "Orientation: portrait."
    )[:10000]


def reference_urls(brand_id: str) -> list[str]:
    from glitch_signal.config import brand_env
    raw = brand_env("SOCIAL_REFERENCE_URLS", brand_id)
    return [u.strip() for u in raw.split(",") if u.strip()][:_MAX_FILES]


async def _default_submit(prompt: str, file_urls: list[str]) -> str:
    import httpx
    from glitch_signal.config import settings
    key = (getattr(settings(), "heygen_api_key", "") or "").strip()  # or os.environ["HEYGEN_API_KEY"]
    body = {"prompt": prompt[:10000], "orientation": "portrait", "mode": "generate",
            "files": [{"type": "url", "url": u} for u in file_urls[:_MAX_FILES]]}
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{_API}/video-agents", headers={"X-Api-Key": key}, json=body)
        r.raise_for_status()
        return r.json()["data"]["session_id"]


async def _default_poll(session_id: str, *, sleep=asyncio.sleep, timeout_s: int = 1800) -> str:
    import httpx
    from glitch_signal.config import settings
    key = (getattr(settings(), "heygen_api_key", "") or "").strip()
    headers = {"X-Api-Key": key}
    waited = 0
    async with httpx.AsyncClient(timeout=60) as c:
        video_id = None
        while waited < timeout_s:
            if video_id is None:
                d = (await c.get(f"{_API}/video-agents/{session_id}", headers=headers)).json()["data"]
                video_id = d.get("video_id")
            if video_id:
                v = (await c.get(f"{_API}/videos/{video_id}", headers=headers)).json()["data"]
                status = str(v.get("status", "")).lower()
                if status == "completed":
                    return v["video_url"]
                if status == "failed":
                    raise RuntimeError(f"heygen video {video_id} failed")
            await sleep(10); waited += 10
    raise TimeoutError(f"heygen session {session_id} timed out after {timeout_s}s")


async def _default_persist(brand_id: str, url: str) -> str:
    # Download the HeyGen mp4 and re-host in the brand bucket (durable URL). Reuse the media
    # factory's storage helper; confirm the exact function name during implementation.
    from glitch_signal.media.generation.storage import upload_bytes
    import httpx
    async with httpx.AsyncClient(timeout=120) as c:
        data = (await c.get(url)).content
    return await upload_bytes(brand_id, data, content_type="video/mp4", suffix=".mp4")


async def generate_video(brand_id: str, prompt: str, file_urls: list[str], *,
                         submit=None, poll=None, persist_url=None) -> str:
    submit = submit or _default_submit
    poll = poll or _default_poll
    persist_url = persist_url or _default_persist
    session_id = await submit(prompt, file_urls)
    heygen_url = await poll(session_id)
    return await persist_url(brand_id, heygen_url)
```

> **Verify during implementation:** (a) `HEYGEN_API_KEY` access — confirm whether it's on `settings()` or read from `os.environ` (mirror `media/generation/engines/heygen.py`); (b) the exact `storage` helper name/signature for uploading bytes to the brand bucket; (c) meter the HeyGen spend through the same `usage_events` choke point the avatar engine uses. Keep `video.py` self-contained — do NOT add an engine/recipe to the media factory.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_social_video.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/glitch_signal/agent/social/video.py tests/test_social_video.py
git commit -m "feat(social): HeyGen Video Agent client (prompt+files, no avatar)"
```

---

### Task 5: `ideate.py` — LLM idea + dedup

**Files:**
- Create: `src/glitch_signal/agent/social/ideate.py`
- Test: `tests/test_social_ideate.py`

**Interfaces:**
- Consumes: `Idea` (Task 1); `store.recent_dedup_keys` (Task 3); `agent/memory/store.recall`; `agent/loop/llm.complete`.
- Produces: `async propose_idea(brand_id: str, *, complete=None, recall=None, recent_keys: set[str] | None = None, engine=None) -> Idea | None`. Returns `None` when the LLM's idea collides with `recent_keys` or can't be parsed.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_social_ideate.py
import json
from glitch_signal.agent.social import ideate


async def _recall_stub(brand_id, query, *, k=8, kinds=None, verified_only=False, engine=None):
    return []


async def test_propose_idea_parses_llm_json():
    async def _complete(prompt, *, system=None, model=None, tier=None, timeout_s=90):
        return json.dumps({"angle": "risk mgmt", "hook": "Blow-ups are optional",
                           "key_points": ["stop-loss"], "dedup_key": "risk-mgmt-2026"})
    idea = await ideate.propose_idea("ge", complete=_complete, recall=_recall_stub, recent_keys=set())
    assert idea is not None and idea.dedup_key == "risk-mgmt-2026" and idea.angle == "risk mgmt"


async def test_propose_idea_dedups_recent():
    async def _complete(prompt, *, system=None, model=None, tier=None, timeout_s=90):
        return json.dumps({"angle": "a", "hook": "h", "key_points": [], "dedup_key": "seen"})
    idea = await ideate.propose_idea("ge", complete=_complete, recall=_recall_stub,
                                     recent_keys={"seen"})
    assert idea is None    # collides → skip
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_social_ideate.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# src/glitch_signal/agent/social/ideate.py
from __future__ import annotations

import json
import re
from typing import Any

import structlog

from glitch_signal.agent.social.spec import Idea

log = structlog.get_logger(__name__)

_PROMPT = (
    "You plan ONE social content idea for brand '{brand}'. Ground it in the trend notes and brand "
    "facts below. Reply with ONLY a JSON object: "
    '{{"angle": "<theme>", "hook": "<=12-word hook", "key_points": ["..."], '
    '"dedup_key": "<short-stable-slug-of-the-angle>"}}.\n\n'
    "--- TREND NOTES ---\n{notes}\n\n--- BRAND FACTS ---\n{facts}\n"
)


def _parse(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw or "", re.DOTALL)
    for cand in ([m.group(0)] if m else []) + [raw or ""]:
        try:
            v = json.loads(cand)
            if isinstance(v, dict):
                return v
        except Exception:  # noqa: BLE001
            continue
    return {}


async def propose_idea(brand_id: str, *, complete=None, recall=None,
                       recent_keys: set[str] | None = None, engine: Any = None) -> Idea | None:
    from glitch_signal.agent.loop import llm as agent_llm
    from glitch_signal.agent.memory.store import recall as mem_recall
    complete = complete or agent_llm.complete
    recall = recall or mem_recall
    recent_keys = recent_keys or set()
    try:
        notes = await recall(brand_id, "trending angle idea for content", k=6,
                             kinds=["episode", "fact"], engine=engine)
        facts = await recall(brand_id, "brand identity product audience", k=6,
                             kinds=["fact"], verified_only=True, engine=engine)
        notes_txt = "\n".join(f"- {m.content}" for m in notes)[:2000] or "(none)"
        facts_txt = "\n".join(f"- {m.content}" for m in facts)[:2000] or "(none)"
        raw = await complete(_PROMPT.format(brand=brand_id, notes=notes_txt, facts=facts_txt),
                             tier="complex", timeout_s=60)
    except Exception as exc:  # noqa: BLE001
        log.warning("social.ideate_failed", error=str(exc)[:200])
        return None
    obj = _parse(raw)
    key = str(obj.get("dedup_key", "")).strip()
    if not key or not obj.get("angle") or key in recent_keys:
        return None
    return Idea(angle=str(obj["angle"]), hook=str(obj.get("hook", "")),
                key_points=[str(p) for p in (obj.get("key_points") or [])], dedup_key=key)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_social_ideate.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/glitch_signal/agent/social/ideate.py tests/test_social_ideate.py
git commit -m "feat(social): LLM ideation grounded in notes+facts, deduped"
```

---

### Task 6: `captions.py` — LLM captions + polish

**Files:**
- Create: `src/glitch_signal/agent/social/captions.py`
- Test: `tests/test_social_captions.py`

**Interfaces:**
- Consumes: `Idea` (Task 1); `agent/loop/llm.complete`; the `polish_copy` tool fn (`agent/loop/tools.py`) — confirm its import path/name during implementation; if not cleanly importable, call `complete` with a polish instruction instead.
- Produces: `async write_captions(brand_id: str, idea: Idea, *, complete=None) -> dict[str, str]` → `{"image": <caption>, "video": <caption>}`, each trimmed to a safe length (≤ 2200 chars).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_social_captions.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_social_captions.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# src/glitch_signal/agent/social/captions.py
from __future__ import annotations

import structlog

from glitch_signal.agent.social.spec import Idea

log = structlog.get_logger(__name__)

_MAX = 2200

_SYS = ("Write a single social caption for brand '{brand}' in its established voice. No hashspam, "
        "no forbidden hype words, no invented claims/metrics. Return ONLY the caption text.")

_ASK = ("Angle: {angle}\nHook: {hook}\nKey points: {points}\nMedium: {medium}\n"
        "Write the caption for a {medium} post.")


async def _one(brand_id: str, idea: Idea, medium: str, complete) -> str:
    raw = await complete(
        _ASK.format(angle=idea.angle, hook=idea.hook,
                    points="; ".join(idea.key_points), medium=medium),
        system=_SYS.format(brand=brand_id), tier="complex", timeout_s=40)
    return (raw or idea.hook).strip()[:_MAX]


async def write_captions(brand_id: str, idea: Idea, *, complete=None) -> dict[str, str]:
    from glitch_signal.agent.loop import llm as agent_llm
    complete = complete or agent_llm.complete
    return {"image": await _one(brand_id, idea, "image", complete),
            "video": await _one(brand_id, idea, "video", complete)}
```

> During implementation, if `polish_copy` is cleanly importable from `agent/loop/tools.py`, run each caption through it before the length trim (mandatory content-policy pass, per spec §B.4). Otherwise the voice constraints in `_SYS` are the guard — note the deviation in the PR.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_social_captions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/glitch_signal/agent/social/captions.py tests/test_social_captions.py
git commit -m "feat(social): per-medium caption writing (voice-guarded)"
```

---

### Task 7: `publish.py` — deterministic fan-out + idempotency

**Files:**
- Create: `src/glitch_signal/agent/social/publish.py`
- Test: `tests/test_social_publish.py`

**Interfaces:**
- Consumes: `PostDraft`, `PlatformResult`, `IMAGE_PLATFORMS`, `VIDEO_PLATFORMS` (Task 1); `store.already_posted`, `store.record_post` (Task 3); publishers `platforms/buffer.create_post(brand_id, service, *, text, media_url)`, `platforms/facebook.publish_facebook(*, brand_id, message, image_url, video_url)`, `platforms/instagram.publish_instagram(*, brand_id, caption, image_url, video_url)`.
- Produces: `async publish_one(brand_id, campaign_id, draft: PostDraft, *, verdict: str, deps: Publishers, store_mod=None, engine=None) -> PlatformResult` and `async fan_out(brand_id, campaign_id, drafts: list[PostDraft], verdicts: dict[str, str], *, deps: Publishers, store_mod=None, engine=None) -> list[PlatformResult]`. `Publishers` is a small dataclass of the three callables (default-bound to the real ones) so tests inject fakes.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_social_publish.py
from glitch_signal.agent.social import publish
from glitch_signal.agent.social.spec import PostDraft


class _FakeStore:
    def __init__(self, posted=False):
        self._posted = posted
        self.recorded = []
    async def already_posted(self, cid, platform, *, engine=None):
        return self._posted
    async def record_post(self, cid, r, media_kind, caption, *, engine=None):
        self.recorded.append(r)


def _deps(calls):
    async def buffer_create(brand_id, service, *, text, media_url=None):
        calls.append(("buffer", service, media_url)); return ("bpost", "sending")
    async def fb(*, brand_id=None, message=None, image_url=None, video_url=None):
        calls.append(("fb", image_url, video_url)); return ("fbid", "http://fb")
    async def ig(*, brand_id=None, caption=None, image_url=None, video_url=None):
        calls.append(("ig", image_url, video_url)); return ("igid", "http://ig")
    return publish.Publishers(buffer_create=buffer_create, facebook=fb, instagram=ig)


async def test_fan_out_routes_each_platform_once_correct_medium():
    calls = []
    drafts = [
        PostDraft("x", "image", "img.png", "c"),
        PostDraft("linkedin", "image", "img.png", "c"),
        PostDraft("facebook", "image", "img.png", "c"),
        PostDraft("tiktok", "video", "vid.mp4", "c"),
        PostDraft("instagram", "video", "vid.mp4", "c"),
    ]
    verdicts = {d.platform: "pass" for d in drafts}
    st = _FakeStore()
    res = await publish.fan_out("ge", "camp-1", drafts, verdicts, deps=_deps(calls), store_mod=st)
    assert {r.platform for r in res} == {"x", "linkedin", "facebook", "tiktok", "instagram"}
    assert all(r.status == "posted" for r in res)
    assert ("buffer", "tiktok", "vid.mp4") in calls          # video via buffer
    assert ("fb", "img.png", None) in calls                  # image via meta
    assert ("ig", None, "vid.mp4") in calls                  # video via meta reels
    assert len(st.recorded) == 5


async def test_escalated_verdict_is_held_not_published():
    calls = []
    drafts = [PostDraft("x", "image", "img.png", "c")]
    st = _FakeStore()
    res = await publish.fan_out("ge", "camp-1", drafts, {"x": "escalate"},
                                deps=_deps(calls), store_mod=st)
    assert res[0].status == "held" and calls == []           # never published


async def test_idempotent_skip_when_already_posted():
    calls = []
    st = _FakeStore(posted=True)
    res = await publish.fan_out("ge", "camp-1", [PostDraft("x", "image", "i.png", "c")],
                                {"x": "pass"}, deps=_deps(calls), store_mod=st)
    assert res[0].status == "skipped" and calls == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_social_publish.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# src/glitch_signal/agent/social/publish.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import structlog

from glitch_signal.agent.social.spec import PlatformResult, PostDraft

log = structlog.get_logger(__name__)

_BUFFER_SERVICES = {"x", "linkedin", "tiktok"}   # everything else → Meta


@dataclass
class Publishers:
    buffer_create: Callable[..., Awaitable[tuple[str, str | None]]]
    facebook: Callable[..., Awaitable[tuple[str, str | None]]]
    instagram: Callable[..., Awaitable[tuple[str, str | None]]]


def _default_publishers() -> Publishers:
    from glitch_signal.platforms.buffer import create_post
    from glitch_signal.platforms.facebook import publish_facebook
    from glitch_signal.platforms.instagram import publish_instagram
    return Publishers(buffer_create=create_post, facebook=publish_facebook,
                      instagram=publish_instagram)


async def publish_one(brand_id: str, campaign_id: str, draft: PostDraft, *, verdict: str,
                      deps: Publishers, store_mod: Any = None, engine: Any = None) -> PlatformResult:
    from glitch_signal.agent.social import store as _store
    store_mod = store_mod or _store
    p = draft.platform
    if verdict == "escalate":
        r = PlatformResult(platform=p, status="held", verdict=verdict)
        await store_mod.record_post(campaign_id, r, draft.media_kind, draft.caption, engine=engine)
        return r
    if await store_mod.already_posted(campaign_id, p, engine=engine):
        return PlatformResult(platform=p, status="skipped", verdict=verdict)
    try:
        if p in _BUFFER_SERVICES:
            pid, _ = await deps.buffer_create(brand_id, p, text=draft.caption, media_url=draft.media_url)
            url = None
        elif p == "facebook":
            pid, url = await deps.facebook(brand_id=brand_id, message=draft.caption,
                                           image_url=draft.media_url)
        elif p == "instagram":
            pid, url = await deps.instagram(brand_id=brand_id, caption=draft.caption,
                                            video_url=draft.media_url)
        else:
            return PlatformResult(platform=p, status="failed", verdict=verdict,
                                  error=f"unknown platform {p!r}")
        r = PlatformResult(platform=p, status="posted", verdict=verdict,
                           platform_post_id=pid, post_url=url)
    except Exception as exc:  # noqa: BLE001 — one platform failing never aborts the rest
        log.warning("social.publish_failed", platform=p, error=str(exc)[:200])
        r = PlatformResult(platform=p, status="failed", verdict=verdict, error=str(exc)[:200])
    await store_mod.record_post(campaign_id, r, draft.media_kind, draft.caption, engine=engine)
    return r


async def fan_out(brand_id: str, campaign_id: str, drafts: list[PostDraft],
                  verdicts: dict[str, str], *, deps: Publishers | None = None,
                  store_mod: Any = None, engine: Any = None) -> list[PlatformResult]:
    deps = deps or _default_publishers()
    out: list[PlatformResult] = []
    for d in drafts:
        out.append(await publish_one(brand_id, campaign_id, d,
                                     verdict=verdicts.get(d.platform, "concerns"),
                                     deps=deps, store_mod=store_mod, engine=engine))
    return out
```

> **Verify during implementation:** the FB image/video kwargs and IG image-vs-video kwargs match `publish_facebook` / `publish_instagram` exactly (facebook.py:97, instagram.py:98). Instagram here always posts the video (Reels) per the mapping; Facebook always the image.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_social_publish.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/glitch_signal/agent/social/publish.py tests/test_social_publish.py
git commit -m "feat(social): deterministic per-platform fan-out + hold/idempotency"
```

---

### Task 8: `campaign.py` — orchestrator (`run_campaign`)

**Files:**
- Create: `src/glitch_signal/agent/social/campaign.py`
- Test: `tests/test_social_campaign.py`

**Interfaces:**
- Consumes: everything above; `agent/loop/conscience.review` + `brand_facts`; `analytics/cost/budget.check`; `media/generation.generate` + `persist` + `Brief`; `agent/memory/store.remember`; `config.settings`.
- Produces: `async run_campaign(brand_id: str, *, deps: RunDeps | None = None, engine=None) -> CampaignResult`. `RunDeps` bundles the injectable callables (ideate, captions, generate_media, review, brand_facts, budget_check, fan_out, store_mod) with real defaults.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_social_campaign.py
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
    d = campaign.RunDeps(ideate=ideate, captions=captions, generate_image=gen_img,
                         generate_video=gen_vid, review=review, brand_facts=brand_facts,
                         budget_check=budget_check, fan_out=fan_out, store_mod=_Store(),
                         remember=lambda *a, **k: None)
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_social_campaign.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# src/glitch_signal/agent/social/campaign.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import structlog

from glitch_signal.agent.social.spec import (
    CampaignResult, IMAGE_PLATFORMS, IMAGE_RECIPE, PostDraft, VIDEO_PLATFORMS,
)

log = structlog.get_logger(__name__)


def _social_on() -> bool:
    from glitch_signal.config import settings
    s = settings()
    return bool(getattr(s, "agent_social_enabled", False)
                and getattr(s, "agent_publish_enabled", False))


@dataclass
class RunDeps:
    ideate: Callable[..., Any]
    captions: Callable[..., Any]
    generate_image: Callable[..., Any]     # (brand_id, idea) -> url  (Higgsfield via media factory)
    generate_video: Callable[..., Any]     # (brand_id, idea) -> url  (HeyGen Video Agent client)
    review: Callable[..., Any]
    brand_facts: Callable[..., Any]
    budget_check: Callable[..., Any]
    fan_out: Callable[..., Any]
    store_mod: Any
    remember: Callable[..., Any]


def _default_deps() -> RunDeps:
    from glitch_signal.agent.loop import conscience
    from glitch_signal.agent.memory.store import remember
    from glitch_signal.agent.social import captions, ideate, publish, store, video
    from glitch_signal.analytics.cost import budget
    from glitch_signal.media.generation import generate as _generate
    from glitch_signal.media.generation.spec import Brief
    from glitch_signal.media.generation.storage import persist

    async def generate_image(brand_id: str, idea) -> str:
        asset = await _generate(Brief(brand_id=brand_id, recipe=IMAGE_RECIPE,
                                      inputs={"prompt": f"{idea.angle}: {idea.hook}"}))
        return (await persist(asset, brand_id)).url

    async def generate_video(brand_id: str, idea) -> str:
        return await video.generate_video(brand_id, video.build_video_prompt(idea),
                                          video.reference_urls(brand_id))

    async def _remember(brand_id, content):
        await remember(brand_id, "episode", content, source="social_campaign")

    return RunDeps(ideate=ideate.propose_idea, captions=captions.write_captions,
                   generate_image=generate_image, generate_video=generate_video,
                   review=conscience.review, brand_facts=conscience.brand_facts,
                   budget_check=budget.check, fan_out=publish.fan_out,
                   store_mod=store, remember=_remember)


async def run_campaign(brand_id: str, *, deps: RunDeps | None = None,
                       engine: Any = None) -> CampaignResult:
    d = deps or _default_deps()
    if not _social_on():
        return CampaignResult(idea=None, image_url=None, video_url=None,
                              skipped_reason="social/publish disabled")
    allowed, reason = await d.budget_check(brand_id)
    if not allowed:
        return CampaignResult(idea=None, image_url=None, video_url=None,
                              skipped_reason=f"budget: {reason}")

    recent = await d.store_mod.recent_dedup_keys(brand_id, engine=engine)
    idea = await d.ideate(brand_id, recent_keys=recent, engine=engine)
    if idea is None:
        return CampaignResult(idea=None, image_url=None, video_url=None,
                              skipped_reason="no fresh idea")

    # media — per-medium fail-soft (image = Higgsfield/factory; video = HeyGen Video Agent)
    image_url = video_url = None
    try:
        image_url = await d.generate_image(brand_id, idea)
    except Exception as exc:  # noqa: BLE001
        log.warning("social.image_failed", error=str(exc)[:200])
    try:
        video_url = await d.generate_video(brand_id, idea)
    except Exception as exc:  # noqa: BLE001
        log.warning("social.video_failed", error=str(exc)[:200])
    if not image_url and not video_url:
        return CampaignResult(idea=idea, image_url=None, video_url=None,
                              skipped_reason="media generation failed")

    caps = await d.captions(brand_id, idea)
    facts = await d.brand_facts(brand_id)

    drafts: list[PostDraft] = []
    if image_url:
        drafts += [PostDraft(p, "image", image_url, caps["image"]) for p in IMAGE_PLATFORMS]
    if video_url:
        drafts += [PostDraft(p, "video", video_url, caps["video"]) for p in VIDEO_PLATFORMS]

    # conscience gate per intended post → verdict map
    verdicts: dict[str, str] = {}
    for dr in drafts:
        try:
            v = await d.review(f"Social post for {brand_id} ({dr.platform})", dr.caption, facts=facts)
        except Exception:  # noqa: BLE001 — critic error → fail toward not posting
            v = {"verdict": "escalate"}
        verdicts[dr.platform] = str((v or {}).get("verdict") or "pass")  # {}=no constitution → allowed

    cid = await d.store_mod.create_campaign(brand_id, idea, image_url=image_url,
                                            video_url=video_url, engine=engine)
    posts = await d.fan_out(brand_id, cid, drafts, verdicts, engine=engine)

    posted = sum(1 for p in posts if p.status == "posted")
    status = ("posted" if posted == len(posts) and posts
              else "partial" if posted else "held")
    await d.store_mod.finalize_campaign(cid, status, 0.0, engine=engine)
    try:
        await d.remember(brand_id, f"social_campaign: {idea.angle} → {posted}/{len(posts)} posted")
    except Exception:  # noqa: BLE001
        pass
    return CampaignResult(idea=idea, image_url=image_url, video_url=video_url, posts=posts)
```

> **Note on `{}` conscience result:** `str((v or {}).get("verdict") or "pass")` maps a no-constitution `{}` to `pass` (allowed), per spec §B.5. If you chose fail-closed, change the default to `"escalate"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_social_campaign.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/glitch_signal/agent/social/campaign.py tests/test_social_campaign.py
git commit -m "feat(social): run_campaign orchestrator (preconditions→gate→fan-out)"
```

---

### Task 9: Register the `social_campaign` cron capability

**Files:**
- Modify: `src/glitch_signal/agent/cron/capabilities.py`
- Test: `tests/test_social_capability.py`

**Interfaces:**
- Consumes: `campaign.run_campaign` (Task 8); the `_REGISTRY: dict[str, CapFn]` + `get(name)` surface (`CapFn = Callable[[str, dict], Awaitable[dict]]`).
- Produces: registry entry `"social_campaign"` → `_cap_social_campaign(brand_id, args) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_social_capability.py
from glitch_signal.agent.cron import capabilities


async def test_social_capability_registered_and_calls_run_campaign(monkeypatch):
    assert "social_campaign" in capabilities.names()
    seen = {}
    async def _fake_run(brand_id, **k):
        seen["brand"] = brand_id
        class R:  # minimal CampaignResult stand-in
            idea = None; posts = []; skipped_reason = "test"
        return R()
    monkeypatch.setattr("glitch_signal.agent.social.campaign.run_campaign", _fake_run)
    fn = capabilities.get("social_campaign")
    out = await fn("ge", {})
    assert seen["brand"] == "ge" and isinstance(out, dict)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_social_capability.py -q`
Expected: FAIL — `"social_campaign"` not in registry.

- [ ] **Step 3: Write minimal implementation**

Add to `capabilities.py` (mirror the existing `_cap_routing_audit` shape) and register in `_REGISTRY`:

```python
async def _cap_social_campaign(brand_id: str, args: dict) -> dict:
    from glitch_signal.agent.social.campaign import run_campaign
    res = await run_campaign(brand_id)
    return {"ran": "social_campaign", "brand": brand_id,
            "posted": sum(1 for p in getattr(res, "posts", []) if p.status == "posted"),
            "skipped_reason": getattr(res, "skipped_reason", None)}
```

```python
_REGISTRY: dict[str, CapFn] = {
    # ...existing entries...
    "social_campaign": _cap_social_campaign,
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_social_capability.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/glitch_signal/agent/cron/capabilities.py tests/test_social_capability.py
git commit -m "feat(social): register social_campaign self-cron capability"
```

---

### Task 10: Full-suite gate + docs write-back + PR

**Files:**
- Modify: `docs/plans/2026-08-30-social-campaign.md` (Status → BUILT), `control-plane/ACTIVE_LANE_BOARD.md`, `control-plane/ENGINEERING_SUPERVISOR.md`

- [ ] **Step 1: Full suite + lint**

Run: `uv run pytest -q` — expect all prior tests + the ~7 new test files green.
Run: `uv run ruff check src/glitch_signal/agent/social/ tests/test_social_*.py` — 0 new debt (auto-fix `I001` import-sort only, like prior lanes).

- [ ] **Step 2: Boot check** (the app imports the new capability at startup)

Run: `uv run python -c "import glitch_signal.server"` — expect no import error.

- [ ] **Step 3: Docs write-back**

Update the spec Status to `BUILT`; add a `SOCIAL-CAMPAIGN` CLOSED entry to the board and an evidence entry to the supervisor (read / changed / verified / docs / remains). Note the enablement steps are separate and NOT done here: host GE's logo + platform screenshots in `ge-media/reference/`, set `GE_SOCIAL_REFERENCE_URLS`, flip `agent_social_enabled` + `agent_publish_enabled`, and seed the `social_campaign` cron job.

- [ ] **Step 4: Commit + PR**

```bash
git add docs/plans/2026-08-30-social-campaign.md control-plane/
git commit -m "docs(social): close SOCIAL-CAMPAIGN lane (built, ships inert)"
git push -u origin lane/social-campaign
gh pr create --base production --title "feat(social): autonomous conscience-gated social_campaign capability" --body "Implements docs/plans/2026-08-30-social-campaign.md. Ships INERT (agent_social_enabled=False). No prod flags flipped."
```

---

## Self-Review

**Spec coverage:** idea+dedup (T5) · Higgsfield image via media factory + HeyGen **Video Agent** client (T4) · captions+polish (T6) · conscience hard-gate (T8) · exactly-1/platform fan-out + mapping + idempotency (T7) · dedup + tables (T3) · flags/inert (T2) · self-cron capability (T9) · budget/fail-soft/cost (T7,T8) · reference assets via `SOCIAL_REFERENCE_URLS` (T4) · tests (every task) · docs (T10). All spec sections map to a task.

**Placeholder scan:** No TBD/TODO. The *verify-against-real-API* notes (T4 HeyGen Video Agent response nesting + `HEYGEN_API_KEY` access + the `storage` upload helper; T6 `polish_copy` import; T7 publisher kwargs) are deliberate — signatures came from the reference sheet / HeyGen docs, but exact response nesting, the key-access pattern, and publisher kwargs must be confirmed against source at build time; each says what to check and the fallback.

**Type consistency:** `Idea`/`PostDraft`/`PlatformResult`/`CampaignResult` fields consistent across T1→T8; `Publishers`/`RunDeps` dataclasses defined where introduced; `RunDeps` uses `generate_image`+`generate_video` (T8) matching the T8 defaults + tests; `store` function names match between T3, T7, T8; capability `CapFn = (brand_id, args)->dict` matches T9. No `VIDEO_RECIPE` remains (removed from T1, campaign import, and tests).

**Known real dependencies (not blockers to build, are blockers to enable live):** (1) `HEYGEN_API_KEY` (present in prod) drives the Video Agent; (2) the **reference assets** — GE's logo + the 4 platform screenshots — must be hosted in GE's Supabase bucket (e.g. `ge-media/reference/`) and their public URLs set in `GE_SOCIAL_REFERENCE_URLS` (comma-separated) before a live video run; (3) `agent_social_enabled` + `agent_publish_enabled` must be flipped and a cron job seeded — all separate, deliberate enablement steps, none done in this lane.
