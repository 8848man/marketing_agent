from datetime import datetime, timedelta, timezone

import pytest

from marketing_agent.config import TriggerConfig
from marketing_agent.trigger import evaluate


NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)


@pytest.mark.parametrize("views,age,expected", [
    (999, 4, "waiting"), (1000, 4, "eligible"),
    (5000, 4, "eligible"), (5001, 4, "expired"),
    (1800, 12, "eligible"), (1800, 12 + 1 / 3600, "expired"),
    (1499, 10, "waiting"), (1500, 10, "eligible"),
])
def test_boundaries(views, age, expected):
    assert evaluate(views, NOW - timedelta(hours=age), NOW).state == expected


def test_rate_recent_snapshot_and_config_reload():
    settings = TriggerConfig()
    current = lambda: settings
    result = evaluate(1200, NOW - timedelta(hours=4), NOW, current,
                      (NOW - timedelta(minutes=30), 1000))
    assert (result.state, result.views_per_hour, result.recent_views_per_hour) == ("eligible", 300, 400)
    settings = TriggerConfig(min_views=2000)
    assert evaluate(1500, NOW - timedelta(hours=4), NOW, current).state == "waiting"
    assert evaluate(1300, NOW - timedelta(hours=4), NOW).state == "eligible"
