# SOCIAL-CAMPAIGN Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, conscience-gated `social_campaign` capability that finds one content idea for a brand, generates a Higgsfield image + a HeyGen video, and publishes one post to each of X, LinkedIn, TikTok (Buffer) + Facebook, Instagram (Meta) — no YouTube, no human in the loop — running on the existing self-cron.

**Architecture:** A Python orchestrator (`agent/social/`) calls the LLM only for the idea and captions; everything exact/safe (media mapping, the conscience hold, per-platform fan-out, dedup, cost, idempotency) is deterministic code. Ships inert behind `agent_social_enabled`.

**Tech Stack:** Python 3.11 / `uv`, FastAPI, SQLModel + Supabase-native SQL migrations, pytest (asyncio auto mode). Reuses the media factory (Higgsfield/HeyGen engines), `agent/loop/conscience.py`, `agent/memory/store.py`, `platforms/{buffer,facebook,instagram}.py`, `analytics/cost/budget.py`, `agent/loop/llm.py`, `agent/cron/capabilities.py`.

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
- Produces: `Idea(angle: str, hook: str, key_points: list[str], dedup_key: str)`; `PostDraft(platform: str, media_kind: str, media_url: str, caption: str)`; `PlatformResult(platform: str, status: str, verdict: str | None = None, platform_post_id: str | None = None, post_url: str | None = None, error: str | None = None)`; `CampaignResult(idea: Idea | None, image_url: str | None, video_url: str | None, posts: list[PlatformResult], cost_usd: float = 0.0, skipped_reason: str | None = None)`. Constants: `IMAGE_PLATFORMS = ("x", "linkedin", "facebook")`, `VIDEO_PLATFORMS = ("tiktok", "instagram")`, `IMAGE_RECIPE = "higgsfield-soul-image"`, `VIDEO_RECIPE = "heygen-avatar-video"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_social_spec.py
from glitch_signal.agent.social.spec import (
    Idea, PostDraft, PlatformResult, CampaignResult,
    IMAGE_PLATFORMS, VIDEO_PLATFORMS, IMAGE_RECIPE, VIDEO_RECIPE,
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
    assert VIDEO_RECIPE == "heygen-avatar-video" and IMAGE_RECIPE == "higgsfield-soul-image"
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
IMAGE_RECIPE = "higgsfield-soul-image"     # existing Higgsfield recipe
VIDEO_RECIPE = "heygen-avatar-video"       # authored in Task 4 (HeyGen engine)


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

### Task 4: HeyGen video recipe

**Files:**
- Create: `src/glitch_signal/media/generation/recipe_library/heygen-avatar-video/recipe.json`
- Create: `src/glitch_signal/media/generation/recipe_library/heygen-avatar-video/SKILL.md`
- Test: `tests/test_social_recipe.py`

**Interfaces:**
- Produces: a loadable recipe slug `heygen-avatar-video` whose engine is `heygen`, taking inputs `{script, avatar_id, voice_id}`. GE's `avatar_id`/`voice_id` are supplied at enablement via `brand_env` (owner data) — the recipe references them as `{{avatar_id}}`/`{{voice_id}}` placeholders filled by the caller's `Brief.inputs`.

> **NOTE:** Read an existing `recipe.json` (e.g. `recipe_library/higgsfield-soul-image/recipe.json`) FIRST and mirror its exact structure/keys — the loader (`media/generation/registry.py`) defines the schema. The JSON below shows intent; conform its keys to the real loader. Confirm the HeyGen submit body fields (`agent/media/generation/engines/heygen.py::_submit`) so `recipe.json` inputs map to what the engine sends (`v3/videos`: script/text, avatar, voice).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_social_recipe.py
from glitch_signal.media.generation import registry


def test_heygen_recipe_loads_and_uses_heygen_engine():
    rec = registry.load("heygen-avatar-video")   # conform to the real loader API
    assert rec.engine == "heygen"
    # inputs the caller must supply
    assert {"script", "avatar_id", "voice_id"} <= set(rec.declared_inputs())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_social_recipe.py -q`
Expected: FAIL — recipe slug not found.

- [ ] **Step 3: Write the recipe** (conform keys to the real loader)

```json
// recipe_library/heygen-avatar-video/recipe.json
{
  "slug": "heygen-avatar-video",
  "engine": "heygen",
  "kind": "video",
  "inputs": {
    "script": {"type": "string", "required": true},
    "avatar_id": {"type": "string", "required": true},
    "voice_id": {"type": "string", "required": true}
  },
  "phases": [
    {"op": "generate", "model": "heygen",
     "params": {"script": "{{script}}", "avatar_id": "{{avatar_id}}", "voice_id": "{{voice_id}}"}}
  ]
}
```

```markdown
<!-- recipe_library/heygen-avatar-video/SKILL.md -->
# heygen-avatar-video
A short brand avatar video (HeyGen). Inputs: script (spoken copy), avatar_id, voice_id
(brand-specific, supplied via brand_env at call time). Engine: heygen (submit→poll).
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_social_recipe.py -q`
Expected: PASS. If the loader's API differs, adjust the test + JSON keys to the real schema (read `registry.py`).

- [ ] **Step 5: Commit**

```bash
git add "src/glitch_signal/media/generation/recipe_library/heygen-avatar-video/" tests/test_social_recipe.py
git commit -m "feat(social): heygen-avatar-video recipe (HeyGen engine, brand avatar/voice)"
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
    async def gen(brand_id, recipe, inputs): return f"https://cdn/{recipe}.out"
    async def review(goal, output, *, facts="", **k): return {"verdict": "pass", "notes": ""}
    async def brand_facts(brand_id, **k): return ""
    async def budget_check(brand_id, **k): return (True, "")
    async def fan_out(brand_id, cid, drafts, verdicts, **k):
        return [PlatformResult(platform=d.platform, status="posted") for d in drafts]
    class _Store:
        async def recent_dedup_keys(self, b, **k): return set()
        async def create_campaign(self, b, idea, **k): return "camp-1"
        async def finalize_campaign(self, cid, status, cost, **k): self.final = (status, cost)
    d = campaign.RunDeps(ideate=ideate, captions=captions, generate_media=gen, review=review,
                         brand_facts=brand_facts, budget_check=budget_check, fan_out=fan_out,
                         store_mod=_Store(), remember=lambda *a, **k: None)
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
    async def gen(brand_id, recipe, inputs): raise RuntimeError("engine down")
    res = await campaign.run_campaign("ge", deps=_deps(generate_media=gen))
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
    CampaignResult, IMAGE_PLATFORMS, IMAGE_RECIPE, PostDraft, VIDEO_PLATFORMS, VIDEO_RECIPE,
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
    generate_media: Callable[..., Any]     # (brand_id, recipe, inputs) -> url
    review: Callable[..., Any]
    brand_facts: Callable[..., Any]
    budget_check: Callable[..., Any]
    fan_out: Callable[..., Any]
    store_mod: Any
    remember: Callable[..., Any]


def _default_deps() -> RunDeps:
    from glitch_signal.agent.loop import conscience
    from glitch_signal.agent.loop.llm import complete           # noqa: F401 (used by ideate/captions defaults)
    from glitch_signal.agent.memory.store import remember
    from glitch_signal.agent.social import captions, ideate, publish, store
    from glitch_signal.analytics.cost import budget
    from glitch_signal.media.generation import generate as _generate
    from glitch_signal.media.generation.spec import Brief
    from glitch_signal.media.generation.storage import persist

    async def generate_media(brand_id: str, recipe: str, inputs: dict) -> str:
        asset = await _generate(Brief(brand_id=brand_id, recipe=recipe, inputs=inputs))
        asset = await persist(asset, brand_id)
        return asset.url

    async def _remember(brand_id, content):
        await remember(brand_id, "episode", content, source="social_campaign")

    return RunDeps(ideate=ideate.propose_idea, captions=captions.write_captions,
                   generate_media=generate_media, review=conscience.review,
                   brand_facts=conscience.brand_facts, budget_check=budget.check,
                   fan_out=publish.fan_out, store_mod=store, remember=_remember)


def _brief_inputs(brand_id: str, recipe: str, idea) -> dict:
    """Recipe inputs. HeyGen avatar/voice come from brand_env (owner data)."""
    from glitch_signal.config import brand_env
    script = f"{idea.hook}. " + " ".join(idea.key_points)
    if recipe == VIDEO_RECIPE:
        return {"script": script, "avatar_id": brand_env("HEYGEN_AVATAR_ID", brand_id),
                "voice_id": brand_env("HEYGEN_VOICE_ID", brand_id)}
    return {"prompt": f"{idea.angle}: {idea.hook}"}     # image recipe


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

    # media — per-medium fail-soft
    image_url = video_url = None
    try:
        image_url = await d.generate_media(brand_id, IMAGE_RECIPE, _brief_inputs(brand_id, IMAGE_RECIPE, idea))
    except Exception as exc:  # noqa: BLE001
        log.warning("social.image_failed", error=str(exc)[:200])
    try:
        video_url = await d.generate_media(brand_id, VIDEO_RECIPE, _brief_inputs(brand_id, VIDEO_RECIPE, idea))
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

Update the spec Status to `BUILT`; add a `SOCIAL-CAMPAIGN` CLOSED entry to the board and an evidence entry to the supervisor (read / changed / verified / docs / remains — note enablement is a separate step, and GE's `HEYGEN_AVATAR_ID`/`HEYGEN_VOICE_ID` must be set before a live run).

- [ ] **Step 4: Commit + PR**

```bash
git add docs/plans/2026-08-30-social-campaign.md control-plane/
git commit -m "docs(social): close SOCIAL-CAMPAIGN lane (built, ships inert)"
git push -u origin lane/social-campaign
gh pr create --base production --title "feat(social): autonomous conscience-gated social_campaign capability" --body "Implements docs/plans/2026-08-30-social-campaign.md. Ships INERT (agent_social_enabled=False). No prod flags flipped."
```

---

## Self-Review

**Spec coverage:** idea+dedup (T5) · Higgsfield image + HeyGen video, incl. the missing recipe (T4, media factory) · captions+polish (T6) · conscience hard-gate (T8) · exactly-1/platform fan-out + mapping + idempotency (T7) · dedup + tables (T3) · flags/inert (T2) · self-cron capability (T9) · budget/fail-soft/cost (T7,T8) · tests (every task) · docs (T10). All spec sections map to a task.

**Placeholder scan:** No TBD/TODO. Two flagged *verify-against-real-API* notes (T4 recipe loader schema; T6 `polish_copy` import; T7 publisher kwargs) are deliberate — the reference sheet gave signatures but the recipe-loader schema and exact publisher kwargs must be confirmed against source at build time; each says exactly what to check and the fallback.

**Type consistency:** `Idea`/`PostDraft`/`PlatformResult`/`CampaignResult` fields consistent across T1→T8; `Publishers`/`RunDeps` dataclasses defined where introduced; `store` function names match between T3, T7, T8; capability `CapFn = (brand_id, args)->dict` matches T9.

**Known real dependency (not a blocker to build, is a blocker to enable live):** no HeyGen recipe existed (T4 authors one); GE's `HEYGEN_AVATAR_ID` / `HEYGEN_VOICE_ID` are owner-supplied and required before a live video run.
