"""Timing and view based eligibility using the current configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .config import TriggerConfig


@dataclass(frozen=True)
class TriggerResult:
    state: str
    reason: str
    view_count: int
    age_hours: float
    views_per_hour: float
    recent_views_per_hour: float | None = None


def evaluate(view_count: int, published_at: datetime, observed_at: datetime,
             config: TriggerConfig | Callable[[], TriggerConfig] = TriggerConfig(),
             previous: tuple[datetime, int] | None = None) -> TriggerResult:
    if published_at.tzinfo is None or observed_at.tzinfo is None:
        raise ValueError("timestamps must be timezone aware")
    if view_count < 0:
        raise ValueError("negative view count")
    limits = config() if callable(config) else config
    age = (observed_at - published_at).total_seconds() / 3600
    if age < 0:
        return TriggerResult("waiting", "FUTURE_PUBLICATION", view_count, age, 0)
    rate = view_count / age if age > 0 else 0.0
    recent = None
    if previous is not None:
        prior_at, prior_count = previous
        elapsed = (observed_at - prior_at).total_seconds() / 3600
        if elapsed > 0:
            recent = (view_count - prior_count) / elapsed
    if age > limits.max_age_hours:
        state, reason = "expired", "AGE_EXCEEDED"
    elif view_count > limits.max_views:
        state, reason = "expired", "VIEWS_EXCEEDED"
    elif view_count < limits.min_views:
        state, reason = "waiting", "VIEWS_BELOW_MINIMUM"
    elif rate < limits.min_views_per_hour:
        state, reason = "waiting", "RATE_BELOW_MINIMUM"
    else:
        state, reason = "eligible", "THRESHOLDS_MET"
    return TriggerResult(state, reason, view_count, age, rate, recent)
