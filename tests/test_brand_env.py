"""Per-brand env resolver: every credential resolves as <ENV_PREFIX>_<KEY>.

The keystone of the multi-project model — a project brings its own `<TAG>_*`
keys, and there are no global credentials. Pure logic, no external calls.
"""
import json

from glitch_signal import config as cfg


def _setup(monkeypatch, tmp_path, brand_id, extra=None):
    configs = tmp_path / "configs"
    configs.mkdir()
    doc = {"brand_id": brand_id, "display_name": brand_id, "timezone": "UTC"}
    if extra:
        doc.update(extra)
    (configs / f"{brand_id}.json").write_text(json.dumps(doc))
    monkeypatch.setenv("BRAND_CONFIGS_DIR", str(configs))
    monkeypatch.setenv("DEFAULT_BRAND_ID", brand_id)
    cfg.settings.cache_clear()
    cfg._reset_brand_registry_for_tests()


def test_reads_prefixed_key(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, "glitch_executor", {"env_prefix": "GE"})
    monkeypatch.setenv("GE_META_APP_ID", "app-123")
    assert cfg.brand_env("META_APP_ID") == "app-123"
    assert cfg.brand_env_prefix() == "GE"


def test_default_when_unset(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, "glitch_executor", {"env_prefix": "GE"})
    monkeypatch.delenv("GE_META_APP_ID", raising=False)
    assert cfg.brand_env("META_APP_ID", default="none") == "none"


def test_no_global_fallback(monkeypatch, tmp_path):
    # A brand with no env_prefix must NEVER read an unprefixed global var.
    _setup(monkeypatch, tmp_path, "glitch_executor", {})
    monkeypatch.setenv("META_APP_ID", "GLOBAL-LEAK")
    assert cfg.brand_env("META_APP_ID", default="none") == "none"
    assert cfg.brand_env_prefix() is None


def test_per_project_prefix_isolates(monkeypatch, tmp_path):
    # A second project uses its own prefix — same code, different tenant.
    _setup(monkeypatch, tmp_path, "acme_corp", {"env_prefix": "ACME"})
    monkeypatch.setenv("ACME_BUFFER_API_KEY", "buf-xyz")
    monkeypatch.setenv("GE_BUFFER_API_KEY", "ge-should-not-win")
    assert cfg.brand_env("BUFFER_API_KEY", "acme_corp") == "buf-xyz"
