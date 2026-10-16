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
