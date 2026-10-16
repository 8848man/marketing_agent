"""Validated, reloadable agent configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
import warnings

import yaml


class ConfigError(ValueError):
    """Configuration cannot be used safely."""


@dataclass(frozen=True)
class TriggerConfig:
    min_views: int = 1000
    max_views: int = 5000
    max_age_hours: float = 12
    min_views_per_hour: float = 150


@dataclass(frozen=True)
class CommentConfig:
    min_chars: int = 40
    max_chars: int = 120


@dataclass(frozen=True)
class LimitsConfig:
    daily_max_comments: int = 10
    channel_cooldown_hours: float = 24


@dataclass(frozen=True)
class AgentConfig:
    topic: str
    keywords: tuple[str, ...]
    poll_interval_min: int = 30
    trigger: TriggerConfig = TriggerConfig()
    comment: CommentConfig = CommentConfig()
    limits: LimitsConfig = LimitsConfig()
    chrome_debug_url: str = "http://localhost:9222"
    allowed_videos: tuple[str, ...] = ()
    daily_search_budget: int = 100


def _mapping(value: object, name: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a mapping")
    return value


def _number(value: object, name: str, *, integer: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int if integer else (int, float)):
        raise ConfigError(f"{name} must be a number")
    if value <= 0:
        raise ConfigError(f"{name} must be positive")
    return value


def _unknown(data: dict, allowed: set[str], scope: str) -> None:
    for key in data.keys() - allowed:
        warnings.warn(f"Unknown configuration key: {scope}{key}", stacklevel=3)


def load_config(path: str | Path) -> AgentConfig:
    """Read on each call, so changes take effect on the next cycle."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Cannot read configuration: {exc}") from exc
    data = _mapping(raw, "config")
    _unknown(data, {"topic", "keywords", "poll_interval_min", "trigger", "comment", "limits", "chrome_debug_url", "allowed_videos", "daily_search_budget"}, "")
    topic = data.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        raise ConfigError("topic must be nonempty")
    keywords = data.get("keywords")
    if not isinstance(keywords, list) or not keywords or any(not isinstance(k, str) or not k.strip() for k in keywords):
        raise ConfigError("keywords must be a nonempty list of strings")
    trigger = _mapping(data.get("trigger", {}), "trigger")
    comment = _mapping(data.get("comment", {}), "comment")
    limits = _mapping(data.get("limits", {}), "limits")
    _unknown(trigger, set(TriggerConfig.__dataclass_fields__), "trigger.")
    _unknown(comment, set(CommentConfig.__dataclass_fields__), "comment.")
    _unknown(limits, set(LimitsConfig.__dataclass_fields__), "limits.")
    t = TriggerConfig(
        min_views=_number(trigger.get("min_views", 1000), "trigger.min_views", integer=True),
        max_views=_number(trigger.get("max_views", 5000), "trigger.max_views", integer=True),
        max_age_hours=_number(trigger.get("max_age_hours", 12), "trigger.max_age_hours"),
        min_views_per_hour=_number(trigger.get("min_views_per_hour", 150), "trigger.min_views_per_hour"),
    )
    c = CommentConfig(
        min_chars=_number(comment.get("min_chars", 40), "comment.min_chars", integer=True),
        max_chars=_number(comment.get("max_chars", 120), "comment.max_chars", integer=True),
    )
    l = LimitsConfig(
        daily_max_comments=_number(limits.get("daily_max_comments", 10), "limits.daily_max_comments", integer=True),
        channel_cooldown_hours=_number(limits.get("channel_cooldown_hours", 24), "limits.channel_cooldown_hours"),
    )
    if t.min_views > t.max_views or c.min_chars > c.max_chars:
        raise ConfigError("minimum cannot exceed maximum")
    url = data.get("chrome_debug_url", "http://localhost:9222")
    if not isinstance(url, str):
        raise ConfigError("chrome_debug_url must be a URL")
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigError("chrome_debug_url must have a valid port") from exc
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"} or not port or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ConfigError("chrome_debug_url must be a local HTTP CDP endpoint")
    allowed = data.get("allowed_videos", [])
    if not isinstance(allowed, list) or any(not isinstance(v, str) or not v.strip() for v in allowed):
        raise ConfigError("allowed_videos must be a list of strings")
    return AgentConfig(
        topic=topic.strip(), keywords=tuple(k.strip() for k in keywords),
        poll_interval_min=_number(data.get("poll_interval_min", 30), "poll_interval_min", integer=True),
        trigger=t, comment=c, limits=l, chrome_debug_url=url,
        allowed_videos=tuple(allowed),
        daily_search_budget=_number(data.get("daily_search_budget", 100), "daily_search_budget", integer=True),
    )
