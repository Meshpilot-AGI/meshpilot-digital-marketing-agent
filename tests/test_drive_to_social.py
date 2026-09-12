"""DRIVE-TO-SOCIAL — post what already exists, once, oldest first."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from glitch_signal.agent.social import drive_to_social as d2s
from glitch_signal.config import brand_config as _real_brand_config
from glitch_signal.config import brand_env as _real_brand_env


@dataclass
class F:
    id: str
    name: str
    mime_type: str = "video/mp4"
    size: int = 1000
    md5: str | None = None
    modified_time: str | None = None


# ── choosing the next file ──
def test_oldest_by_name_first_and_never_a_posted_one():
    files = [F("c", "2026-09-03_c.mp4"), F("a", "2026-09-01_a.mp4"), F("b", "2026-09-02_b.mp4")]
    posted = {"a": {"ig_media_id": "x", "tiktok_post_id": "y"}}
    f, need = d2s.pick_next(files, posted)
    assert f.id == "b" and need == {"instagram": True, "tiktok": True}


def test_a_file_that_landed_on_one_platform_is_retried_only_on_the_other():
    """Per-platform outcomes are independent: a TikTok outage must not repeat the IG post."""
    files = [F("a", "a.mp4"), F("b", "b.mp4")]
    posted = {"a": {"ig_media_id": "ig-1", "tiktok_post_id": None}}
    f, need = d2s.pick_next(files, posted)
    assert f.id == "a" and need == {"instagram": False, "tiktok": True}


def test_everything_posted_means_nothing_to_do():
    f, _ = d2s.pick_next([F("a", "a.mp4")], {"a": {"ig_media_id": "1", "tiktok_post_id": "2"}})
    assert f is None


# ── captions ──
def test_a_hard_stop_phrase_cuts_the_caption_at_that_sentence():
    """The phrases the ORM lane refuses to say in a reply, the caption must not say in a post."""
    out = d2s.scrub("Turmeric chews for happy dogs. Cures joint pain fast! Order today.", ["cures"])
    assert out == "Turmeric chews for happy dogs."


def test_a_caption_that_is_all_hard_stops_falls_back_to_the_filename():
    assert d2s.scrub("Cures everything.", ["cures"]) == ""
    assert d2s.caption_from_name("2026-09-01_turmeric-chew-closeup.mp4") == "Turmeric chew closeup"


async def test_caption_generation_failure_does_not_fail_the_post(monkeypatch):
    monkeypatch.setattr(d2s, "_hard_stops", lambda b: ["cures"])
    monkeypatch.setattr("glitch_signal.config.brand_config",
                        lambda b: {"display_name": "AyurPet", "brand": {"voice": "warm"},
                                   "default_hashtags": ["ayurpet", "dogwellness"]})

    async def boom(prompt):
        raise RuntimeError("model down")

    cap = await d2s.write_caption("ayurpet", "yak-chew-unboxing.mp4", complete=boom)
    assert cap.startswith("Yak chew unboxing")
    assert "#ayurpet" in cap and "#dogwellness" in cap


async def test_generated_captions_are_scrubbed_and_hashtagged(monkeypatch):
    monkeypatch.setattr(d2s, "_hard_stops", lambda b: ["vet recommended"])
    monkeypatch.setattr("glitch_signal.config.brand_config",
                        lambda b: {"display_name": "AyurPet", "brand": {"voice": "warm"},
                                   "default_hashtags": ["ayurpet"]})

    async def ok(prompt):
        return "Morning chew time. Vet recommended for every dog."

    cap = await d2s.write_caption("ayurpet", "x.mp4", complete=ok)
    assert cap.splitlines()[0] == "Morning chew time."
    assert "#ayurpet" in cap


# ── the run ──
class _Eng:
    def __init__(self, rows=None):
        self.rows, self.writes = rows or [], []

    def connect(self):
        return _Conn(self)

    def begin(self):
        return _Conn(self)


class _Conn:
    def __init__(self, eng):
        self.eng = eng

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt, params=None):
        if "INSERT" in str(stmt):
            self.eng.writes.append(params)
        return _Res(self.eng.rows)


class _Res:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


def _deps(ig_fail=False, tt_fail=False):
    calls = {"ig": [], "tt": [], "up": []}

    async def list_files(folder, brand_id=None):
        return [F("f1", "2026-09-01_first.mp4")]

    async def download(fid, dest, brand_id=None):
        dest.write_bytes(b"video")
        return 5

    async def upload(data, brand_id, **kw):
        calls["up"].append(kw)
        return "https://cdn.example/drive/f1.mp4"

    async def publish_instagram(**kw):
        calls["ig"].append(kw)
        if ig_fail:
            raise RuntimeError("ig down")
        return "ig-123", "https://instagram.com/p/abc"

    async def create_post(brand_id, service, **kw):
        calls["tt"].append((service, kw))
        if tt_fail:
            raise RuntimeError("buffer down")
        return "bf-9", "sending"

    async def complete(prompt):
        return "First one from the new batch."

    return calls, {"list_files": list_files, "download": download, "upload": upload,
                   "publish_instagram": publish_instagram, "create_post": create_post,
                   "complete": complete}




@pytest.fixture(autouse=True)
def _brand(monkeypatch):
    monkeypatch.setattr(d2s, "_on", lambda: True)
    monkeypatch.setattr(d2s, "_hard_stops", lambda b: [])
    monkeypatch.setattr("glitch_signal.config.brand_config",
                        lambda b: {"display_name": "AyurPet", "brand": {"voice": "warm"},
                                   "default_hashtags": ["ayurpet"]})
    monkeypatch.setattr("glitch_signal.config.brand_env", lambda k, b=None, d="": "folder-1" if k == "DRIVE_FOLDER_ID" else d)


async def test_a_full_post_hits_both_platforms_and_records_both_ids():
    calls, deps = _deps()
    eng = _Eng()
    out = await d2s.run("ayurpet", {}, engine=eng, deps=deps)
    assert out["instagram"] == "https://instagram.com/p/abc" and out["tiktok"].startswith("bf-9")
    assert calls["ig"][0]["video_url"] == "https://cdn.example/drive/f1.mp4"
    assert calls["tt"][0][0] == "tiktok" and calls["tt"][0][1]["media_url"] == "https://cdn.example/drive/f1.mp4"
    w = eng.writes[0]
    assert w["ig"] == "ig-123" and w["tt"] == "bf-9" and w["ige"] is None and w["tte"] is None


async def test_one_platform_failing_still_posts_the_other_and_records_the_error():
    calls, deps = _deps(tt_fail=True)
    eng = _Eng()
    out = await d2s.run("ayurpet", {}, engine=eng, deps=deps)
    assert out["instagram"] and "buffer down" in out["tiktok_error"]
    w = eng.writes[0]
    assert w["ig"] == "ig-123" and w["tt"] is None and "buffer down" in w["tte"]


async def test_a_retry_reuses_the_uploaded_copy_and_skips_the_platform_that_succeeded():
    """Second run after a TikTok failure: no re-download, no re-upload, no second IG post."""
    calls, deps = _deps()
    eng = _Eng(rows=[{"file_id": "f1", "ig_media_id": "ig-123", "tiktok_post_id": None,
                      "media_url": "https://cdn.example/drive/f1.mp4", "caption": "kept"}])
    await d2s.run("ayurpet", {}, engine=eng, deps=deps)
    assert calls["up"] == [] and calls["ig"] == [] and len(calls["tt"]) == 1
    assert calls["tt"][0][1]["text"] == "kept"


async def test_dry_run_posts_nothing_and_shows_what_it_would_do():
    calls, deps = _deps()
    out = await d2s.run("ayurpet", {"dry_run": True}, engine=_Eng(), deps=deps)
    assert out["dry_run"] and out["would_post"] == "2026-09-01_first.mp4"
    assert calls["ig"] == [] and calls["tt"] == [] and calls["up"] == []


async def test_the_kill_switches_gate_it_like_every_other_publisher(monkeypatch):
    monkeypatch.setattr(d2s, "_on", lambda: False)
    _, deps = _deps()
    assert (await d2s.run("ayurpet", {}, engine=_Eng(), deps=deps))["skipped"] == "social_or_publish_disabled"


async def test_no_folder_is_a_named_refusal(monkeypatch):
    monkeypatch.setattr("glitch_signal.config.brand_env", lambda k, b=None, d="": d)
    _, deps = _deps()
    assert (await d2s.run("ayurpet", {}, engine=_Eng(), deps=deps))["skipped"] == "no_folder"


def test_drive_client_resolves_sa_per_brand(monkeypatch):
    """AyurPet must fall to the unprefixed MeshPilot SA while GE keeps its own GE_ one."""
    from glitch_signal.integrations import google_drive as gd

    # The module-wide fixture stubs brand_config/brand_env; this test needs the real registry.
    monkeypatch.setattr("glitch_signal.config.brand_config", _real_brand_config)
    monkeypatch.setattr("glitch_signal.config.brand_env", _real_brand_env)
    monkeypatch.setattr(gd, "GoogleDriveClient", lambda sa: sa)
    monkeypatch.setenv("GE_GOOGLE_DRIVE_SA_JSON", "ge-sa")
    monkeypatch.setenv("GOOGLE_DRIVE_SA_JSON", "meshpilot-sa")
    gd._client.cache_clear()
    assert gd._client("ayurpet") == "meshpilot-sa"
    assert gd._client("glitch_executor") == "ge-sa"
    gd._client.cache_clear()
