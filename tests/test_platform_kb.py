"""Per-platform audience and register.

Until this, one caption was written per MEDIUM and reused across every platform of that medium — the
identical text went to X, LinkedIn and Facebook. Different rooms, different lengths and registers; a
caption tuned for none of them is tuned for all of them badly. On a brand whose positioning is
"sounds like someone who has been there", generic copy is the specific thing that breaks it.
"""
import pathlib

from glitch_signal.agent.social import captions, platforms_kb as kb
from glitch_signal.agent.social.spec import Idea
from tests.test_agent_memory import FakeEngine, _Result, _Row

_MIGRATIONS = pathlib.Path(__file__).resolve().parents[1] / "supabase" / "migrations"


# ── the migration must not ship an empty table (finding: "Platform profiles ship empty") ──────────
def test_platform_profile_defaults_are_seeded_for_every_advertised_platform():
    """The table-creating migration inserted no rows, so a fresh install had no profiles at all and
    every caption silently fell back to generic per-medium copy. A later migration must seed a
    generic default for every platform this feature advertises."""
    seed_files = [p for p in _MIGRATIONS.glob("*.sql") if "platform_profile" in p.name]
    assert seed_files, "no platform_profile migration found"
    combined = "\n".join(p.read_text() for p in seed_files)
    for platform in ("x", "linkedin", "facebook", "instagram", "tiktok"):
        assert f"'{platform}'" in combined, f"no seeded default profile for {platform!r}"


def _prof(platform="x"):
    return {"platform": platform, "audience": "traders", "register": "one idea, stated flat",
            "max_chars": 280, "hashtags": "None.", "avoid": "emoji"}


# ── the profile section ─────────────────────────────────────────────────────────────────────────
def test_section_is_empty_without_a_profile():
    """An empty labelled block invites the model to fill it from its priors — same rule as every
    other grounding section in this pipeline."""
    assert kb.section({}) == ""


def test_section_carries_audience_register_and_limits():
    s = kb.section(_prof())
    assert "traders" in s and "one idea, stated flat" in s
    assert "280" in s and "emoji" in s


def test_section_subordinates_the_platform_to_the_positioning():
    """The platform shapes HOW to say it. It must never be read as licence to relax a prohibition —
    otherwise 'that works on TikTok' becomes a route around the brand's claim limits."""
    s = kb.section(_prof())
    assert "must never be relaxed" in s


async def test_profile_degrades_to_empty_on_db_failure():
    class _Boom:
        def connect(self):
            raise RuntimeError("db down")
    assert await kb.profile("ge", "x", engine=_Boom()) == {}


async def test_profile_is_scoped_to_brand_and_platform():
    eng = FakeEngine()
    eng.queue(_Result(rows=[]))
    await kb.profile("ge", "X", engine=eng)
    _sql, params = eng.calls[0]
    assert params["b"] == "ge" and params["p"] == "x"      # platform normalised


async def test_profile_falls_back_to_the_reserved_default_brand():
    """A brand that never set its own profile must not be left with an empty one: the migration
    seeds five generic profiles under the reserved '_default' brand_id, and the query has to
    consider that id — not just the caller's own — so a fresh brand still gets platform context."""
    eng = FakeEngine()
    eng.queue(_Result(rows=[]))
    await kb.profile("brand-new-and-unconfigured", "x", engine=eng)
    sql, params = eng.calls[0]
    assert params["default_brand"] == "_default"
    assert "_default" not in params["p"]                    # never confused for a platform
    assert " in (" in sql.lower() or " IN (" in sql
    # the brand's own row must win when both exist
    assert "order by" in sql.lower() and "desc" in sql.lower()


# ── tagging: verified handles only ──────────────────────────────────────────────────────────────
def test_no_handles_means_no_tagging_instruction():
    """A wrong handle tags a real stranger's account in public — worse than not tagging. Absence
    must mean 'name them in plain text', never 'guess'."""
    assert kb.mention_line([], "x") == ""
    assert kb.mention_line([None, ""], "x") == ""


def test_mention_line_forbids_inventing_other_handles():
    line = kb.mention_line(["@FTMO"], "x")
    assert "@FTMO" in line
    assert "Do not invent any other handle" in line
    assert "companies the post does not discuss" in line


async def test_handles_lookup_returns_nothing_when_unverified(monkeypatch):
    """The library ships with no handles; until they are verified, tagging stays off."""
    async def _resolve(brand, names, *, kind="logo", engine=None):
        return [{"slug": "ftmo", "name": "FTMO", "handles": {}}]
    monkeypatch.setattr("glitch_signal.agent.assets.resolve_named", _resolve)
    assert await kb.handles_for("ge", ["FTMO"], "x") == []


async def test_handles_lookup_returns_a_verified_handle(monkeypatch):
    async def _resolve(brand, names, *, kind="logo", engine=None):
        return [{"slug": "ftmo", "name": "FTMO", "handles": {"x": "@FTMO"}}]
    monkeypatch.setattr("glitch_signal.agent.assets.resolve_named", _resolve)
    assert await kb.handles_for("ge", ["FTMO"], "x") == ["@FTMO"]


async def test_handles_are_per_platform(monkeypatch):
    """A company's X handle is not its LinkedIn one; using the wrong one tags nobody, or worse."""
    async def _resolve(brand, names, *, kind="logo", engine=None):
        return [{"slug": "ftmo", "name": "FTMO", "handles": {"x": "@FTMO"}}]
    monkeypatch.setattr("glitch_signal.agent.assets.resolve_named", _resolve)
    assert await kb.handles_for("ge", ["FTMO"], "linkedin") == []


# ── captions are now per platform ───────────────────────────────────────────────────────────────
async def test_one_caption_is_written_per_platform(monkeypatch):
    seen: list[str] = []

    async def complete(prompt, *, system=None, **k):
        seen.append(prompt)
        return f"caption {len(seen)}"

    async def prof(brand, platform, *, engine=None):
        return _prof(platform)

    monkeypatch.setattr(kb, "profile", prof)
    monkeypatch.setattr(kb, "handles_for", lambda *a, **k: _empty())
    out = await captions.write_captions(
        "ge", Idea("a", "h", ["p"], "k"), platforms={"x": "image", "linkedin": "image"},
        complete=complete, positioning=lambda *a, **k: _blank())
    assert out["x"] != out["linkedin"]                    # genuinely distinct copy
    assert len(seen) == 2
    assert "WRITING FOR X" in seen[0] and "WRITING FOR LINKEDIN" in seen[1]


async def test_medium_keys_stay_populated_for_older_callers(monkeypatch):
    async def complete(prompt, *, system=None, **k):
        return "c"

    async def prof(brand, platform, *, engine=None):
        return {}

    monkeypatch.setattr(kb, "profile", prof)
    monkeypatch.setattr(kb, "handles_for", lambda *a, **k: _empty())
    out = await captions.write_captions(
        "ge", Idea("a", "h", ["p"], "k"), platforms={"x": "image"},
        complete=complete, positioning=lambda *a, **k: _blank())
    assert out["image"] == out["x"]


async def test_caption_is_truncated_to_the_platforms_hard_limit(monkeypatch):
    """max_chars is described as a hard platform limit but was only ever placed in the prompt — a
    model response (or the polishing pass after it) could still overrun it and be sent unchanged to
    the publisher. The 2,200 global cap is not narrow enough to catch X's 280."""
    async def complete(prompt, *, system=None, **k):
        return "x" * 500                        # well over X's 280, under the global 2200 cap

    async def prof(brand, platform, *, engine=None):
        return _prof(platform)                  # max_chars=280

    monkeypatch.setattr(kb, "profile", prof)
    monkeypatch.setattr(kb, "handles_for", lambda *a, **k: _empty())
    out = await captions.write_captions(
        "ge", Idea("a", "h", ["p"], "k"), platforms={"x": "image"},
        complete=complete, positioning=lambda *a, **k: _blank())
    assert len(out["x"]) <= 280


async def test_caption_without_a_platform_limit_keeps_the_global_cap(monkeypatch):
    async def complete(prompt, *, system=None, **k):
        return "x" * 3000

    async def prof(brand, platform, *, engine=None):
        return {**_prof(platform), "max_chars": None}

    monkeypatch.setattr(kb, "profile", prof)
    monkeypatch.setattr(kb, "handles_for", lambda *a, **k: _empty())
    out = await captions.write_captions(
        "ge", Idea("a", "h", ["p"], "k"), platforms={"x": "image"},
        complete=complete, positioning=lambda *a, **k: _blank())
    assert len(out["x"]) == 2200


async def test_without_platforms_it_falls_back_to_per_medium():
    """An unprofiled brand must still post."""
    async def complete(prompt, *, system=None, **k):
        return "c"
    out = await captions.write_captions("ge", Idea("a", "h", ["p"], "k"), complete=complete,
                                        positioning=lambda *a, **k: _blank())
    assert set(out) == {"image", "video"}


async def _empty():
    return []


async def _blank():
    return ""


# ── handle storage + lookup (real data, real footguns) ──────────────────────────────────────────
async def test_find_selects_the_handles_column():
    """Guards the bug this shipped with: the column was added and populated, but `assets.find`'s
    explicit SELECT list was never updated, so every lookup silently returned no handles."""
    from glitch_signal.agent import assets
    eng = FakeEngine()
    eng.queue(_Result(rows=[]))
    await assets.find("ge", kind="logo", engine=eng)
    sql, _ = eng.calls[0]
    assert "handles" in sql.lower()


async def test_reserved_provenance_key_is_never_returned_as_a_handle(monkeypatch):
    """`_source` records where a handle came from and lives in the same JSON. It must never be
    mistaken for a platform and emitted as something to tag."""
    async def _resolve(brand, names, *, kind="logo", engine=None):
        return [{"slug": "ftmo", "name": "FTMO",
                 "handles": {"x": "@FTMO_com", "_source": "ftmo.com footer"}}]
    monkeypatch.setattr("glitch_signal.agent.assets.resolve_named", _resolve)
    assert await kb.handles_for("ge", ["FTMO"], "_source") == []
    assert await kb.handles_for("ge", ["FTMO"], "x") == ["@FTMO_com"]


async def test_handles_survive_jsonb_returned_as_text():
    """asyncpg sometimes hands jsonb back as a string; a raw str would make `.get` fail silently and
    the post would simply never tag anyone. A local fake is used because the shared FakeEngine has
    no `.mappings()`, which `assets.find` relies on."""
    from glitch_signal.agent import assets

    row = {"slug": "ftmo", "name": "FTMO", "kind": "logo", "url": "u", "width": 1, "height": 1,
           "accent": None, "usage_note": None, "handles": '{"x": "@FTMO_com"}'}

    class _R:
        def mappings(self):
            return self

        def all(self):
            return [row]

    class _Conn:
        async def execute(self, *a, **k):
            return _R()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Eng:
        def connect(self):
            return _Conn()

    got = await assets.find("ge", kind="logo", engine=_Eng())
    assert got[0]["handles"] == {"x": "@FTMO_com"}


async def test_a_company_with_no_verified_handle_is_never_tagged(monkeypatch):
    """Apex publishes no social links on its own site, so we hold none. It must be named in plain
    text rather than tagged at a guessed account — this category has lookalikes."""
    async def _resolve(brand, names, *, kind="logo", engine=None):
        return [{"slug": "apex", "name": "Apex Trader Funding", "handles": {}}]
    monkeypatch.setattr("glitch_signal.agent.assets.resolve_named", _resolve)
    assert await kb.handles_for("ge", ["Apex"], "x") == []
