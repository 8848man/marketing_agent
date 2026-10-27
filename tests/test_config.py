from pathlib import Path

import pytest

from marketing_agent.config import ConfigError, load_config


def write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_defaults_and_reload(tmp_path):
    path = write(tmp_path, "topic: 연애\nkeywords: [연애, 썸]\n")
    cfg = load_config(path)
    assert (cfg.poll_interval_min, cfg.trigger.min_views, cfg.trigger.max_views,
            cfg.trigger.max_age_hours, cfg.trigger.min_views_per_hour,
            cfg.comment.min_chars, cfg.comment.max_chars,
            cfg.limits.daily_max_comments, cfg.limits.channel_cooldown_hours) == (30, 1000, 5000, 12, 150, 40, 120, 10, 24)
    write(tmp_path, "topic: 연애\nkeywords: [연애]\ntrigger:\n  min_views: 2000\n")
    assert load_config(path).trigger.min_views == 2000


@pytest.mark.parametrize("content", [
    "keywords: [연애]",
    "topic: 연애\nkeywords: []",
    "topic: 연애\nkeywords: [연애]\ntrigger: {min_views: 6000}",
    "topic: 연애\nkeywords: [연애]\nlimits: {daily_max_comments: -1}",
    "topic: 연애\nkeywords: [연애]\nchrome_debug_url: http://example.com:9222",
    "topic: 연애\nkeywords: [연애]\nchrome_debug_url: http://localhost:9222@evil.test",
])
def test_invalid_config(tmp_path, content):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, content))


def test_unknown_allowlist_toggle_cannot_disable_policy(tmp_path):
    path = write(tmp_path, "topic: 연애\nkeywords: [연애]\nallowlist_enabled: false\n")
    with pytest.warns(UserWarning, match="allowlist_enabled"):
        assert load_config(path).allowed_videos == ()


def test_task_constraints_single_source():
    import marketing_agent
    from marketing_agent import task_constraints
    assert (task_constraints.BRAND_NAME, task_constraints.DAILY_MAX_COMMENTS) == ("운명원", 10)
    source = (Path(marketing_agent.__file__).parent / "dashboard_settings.py").read_text(encoding="utf-8")
    assert '"운명원"' not in source
    assert "daily_max_comments\": 10" not in source and "!= 10" not in source


def test_claude_client_default_matches_registry():
    from marketing_agent.ai_client import PROVIDERS, ClaudeClient
    assert ClaudeClient(api_key="x").model == PROVIDERS["claude"][0]


def test_app_root_validation(tmp_path):
    from marketing_agent.__main__ import _resolve_app_root
    fake = tmp_path / "site"
    fake.mkdir()
    with pytest.raises(SystemExit) as info:
        _resolve_app_root(fake, {})
    assert "pip install -e ." in str(info.value)
    other = tmp_path / "other"
    other.mkdir()
    (other / "pyproject.toml").write_text('[project]\nname = "other"\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        _resolve_app_root(fake, {"MARKETING_AGENT_HOME": str(other)})
    real = tmp_path / "app"
    real.mkdir()
    (real / "pyproject.toml").write_text('[project]\nname = "marketing-agent"\n', encoding="utf-8")
    assert _resolve_app_root(real, {}) == real.resolve()
    assert _resolve_app_root(fake, {"MARKETING_AGENT_HOME": str(real)}) == real.resolve()
