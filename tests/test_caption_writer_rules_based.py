"""Rules-based caption mode — prompt shape + catalog injection."""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("DISPATCH_MODE", "dry_run")
os.environ.setdefault("SIGNAL_DB_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("TELEGRAM_BOT_TOKEN_SIGNAL", "0:test")
os.environ.setdefault("TELEGRAM_ADMIN_IDS", "0")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_API_KEY", "test")
os.environ.setdefault("AUTH_ENCRYPTION_KEY", "l3mgT3MDKZ2g8oh2l8r4e1XaS0o7Q8mT9H5V1v3P2Hk=")


@pytest.fixture(autouse=True)
def _reset_caches():
    from glitch_signal import config as cfg
    cfg._reset_brand_registry_for_tests()
    cfg.settings.cache_clear()
    yield
    cfg._reset_brand_registry_for_tests()
    cfg.settings.cache_clear()


class _FakeSignal:
    def __init__(self, summary, signal_id="sig-1"):
        self.id = signal_id
        self.summary = summary


def _write_brand_with_catalog(tmp_path, brand_id, catalog_text):
    configs = tmp_path / "configs"
    configs.mkdir()
    catalog_path = tmp_path / f"{brand_id}_catalog.md"
    catalog_path.write_text(catalog_text)
    (configs / f"{brand_id}.json").write_text(json.dumps({
        "brand_id": brand_id,
        "display_name": f"{brand_id} Display",
        "timezone": "UTC",
        "platforms": {},
        "caption_writer": {
            "mode": "rules_based",
            "product_catalog_path": str(catalog_path),
        },
        "default_hashtags": ["tag1", "tag2"],
    }))
    return configs, catalog_path


class TestRulesBasedRouting:
    @pytest.mark.asyncio
    async def test_parsed_filename_and_catalog_reach_llm(self, tmp_path, monkeypatch):
        from glitch_signal import config as cfg
        from glitch_signal.agent.nodes import caption_writer as cw

        configs, catalog_path = _write_brand_with_catalog(
            tmp_path, "drive_test",
            "# Brand catalog\n- Liver Cleanse Tea\n- hard rule: never claim cure",
        )
        monkeypatch.setenv("BRAND_CONFIGS_DIR", str(configs))
        monkeypatch.setenv("DEFAULT_BRAND_ID", "drive_test")
        cfg.settings.cache_clear()
        cfg._reset_brand_registry_for_tests()

        captured = {}
        async def fake_rules_based(**kwargs):
            captured.update(kwargs)
            return {"title": "T", "caption": "Caption body #a #b", "hashtags": ["a", "b"]}
        async def no_filename(**kwargs):
            raise AssertionError("filename path should not run when rules_based succeeds")

        monkeypatch.setattr(cw, "_generate_via_rules_based", fake_rules_based)
        monkeypatch.setattr(cw, "_generate_via_filename", no_filename)

        title, caption, tags = await cw._generate_caption(
            _FakeSignal("Liver_ad15_UK_h1_9.4.26.mp4"),
            "drive_test", "tiktok", local_path=None,
        )
        assert title == "T"
        assert tags == ["a", "b"]
        # Filename + catalog path + system_prompt + user_context all reached the handler.
        assert captured["signal"].summary == "Liver_ad15_UK_h1_9.4.26.mp4"
        assert captured["catalog_path"] == str(catalog_path)
        assert "system_prompt" in captured
        assert "user_context" in captured


class TestRulesBasedPromptComposition:
    @pytest.mark.asyncio
    async def test_prompt_includes_parsed_fields_and_catalog(self, tmp_path, monkeypatch):
        """Exercises the real _generate_via_rules_based body with a
        mocked litellm response — verifies the prompt sent to the LLM
        carries product, ad_num, geo, variant_group, and catalog text."""
        from glitch_signal.agent.nodes import caption_writer as cw

        catalog = tmp_path / "cat.md"
        catalog.write_text("# catalog\n- Liver Cleanse Tea\n- never claim cure")

        captured = {}

        async def fake_caption(system_prompt, user_text, brand_id):
            captured["user"] = user_text
            return '{"title": "t", "caption": "c", "hashtags": ["x"]}'

        monkeypatch.setattr(
            "glitch_signal.agent.nodes.caption_writer._caption_llm", fake_caption)

        data = await cw._generate_via_rules_based(
            signal=_FakeSignal("Liver_ad15_UK_h1_9.4.26.mp4"),
            brand_id="drive_brand",
            system_prompt="SYSTEM",
            user_context="PLATFORM: tiktok",
            catalog_path=str(catalog),
        )
        assert data["title"] == "t"
        # The user text must carry parsed fields + catalog text.
        user_msg = captured["user"]
        assert "product: liver" in user_msg.lower()
        assert "ad_num:  15" in user_msg or "ad_num: 15" in user_msg
        assert "geo:     uk" in user_msg.lower() or "geo: uk" in user_msg.lower()
        assert "variant_group: liver_ad15_uk" in user_msg.lower()
        assert "Liver Cleanse Tea" in user_msg
        assert "never claim cure" in user_msg

    @pytest.mark.asyncio
    async def test_missing_catalog_logs_but_does_not_raise(self, tmp_path, monkeypatch):
        from glitch_signal.agent.nodes import caption_writer as cw

        async def fake_caption(system_prompt, user_text, brand_id):
            return '{"title":"t","caption":"c","hashtags":[]}'

        monkeypatch.setattr(
            "glitch_signal.agent.nodes.caption_writer._caption_llm", fake_caption)

        data = await cw._generate_via_rules_based(
            signal=_FakeSignal("x.mp4"),
            brand_id="drive_brand",
            system_prompt="S", user_context="U",
            catalog_path=str(tmp_path / "missing.md"),   # doesn't exist
        )
        assert data["title"] == "t"

    @pytest.mark.asyncio
    async def test_unparseable_filename_still_generates(self, tmp_path, monkeypatch):
        """Even when the filename produces no product, the prompt must
        still be generated (with 'unparsed' signalled to the model)."""
        from glitch_signal.agent.nodes import caption_writer as cw

        captured = {}

        async def fake_caption(system_prompt, user_text, brand_id):
            captured["user"] = user_text
            return '{"title":"t","caption":"c","hashtags":[]}'

        monkeypatch.setattr(
            "glitch_signal.agent.nodes.caption_writer._caption_llm", fake_caption)

        await cw._generate_via_rules_based(
            signal=_FakeSignal("random_clip_no_pattern.mp4"),
            brand_id="drive_brand",
            system_prompt="S", user_context="U",
            catalog_path=None,
        )
        user_msg = captured["user"]
        assert "unparsed" in user_msg.lower() or "generic" in user_msg.lower()
