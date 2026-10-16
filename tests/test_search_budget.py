from datetime import datetime, timedelta, timezone

import pytest

from marketing_agent.search_budget import ComparisonSample, SearchBudget, SearchBudgetStop


T = datetime(2026, 10, 15, 14, 59, tzinfo=timezone.utc)


def test_budget_reservations_units_and_kst_reset():
    budget = SearchBudget()
    assert budget.unit_cost_label == "unverified_assumption"
    with pytest.raises(SearchBudgetStop, match="UNITS"):
        budget.before_call(T, "base", 99)
    assert sum(budget.counts(T).values()) == 0
    for kind, cap in (("base", 48), ("evaluation", 36), ("extra", 16)):
        for _ in range(cap):
            budget.before_call(T, kind, 100)
        with pytest.raises(SearchBudgetStop):
            budget.before_call(T, kind, 100)
    assert sum(budget.counts(T).values()) == 100
    budget.before_call(T + timedelta(minutes=1), "base", 100)
    assert budget.counts(T + timedelta(minutes=1))["base"] == 1


def test_complete_samples_only_and_next_day_rotation():
    budget = SearchBudget()
    incomplete = ComparisonSample.build({"a"}, {"a", "b"}, {"b"}, complete=False, boundary=T)
    empty = ComparisonSample.build(set(), set(), set(), complete=True, boundary=T)
    assert not budget.add_sample(incomplete)
    assert not budget.add_sample(empty)
    for n in range(3):
        sample = ComparisonSample.build({"a"}, {"a", "b"}, {"b"}, complete=True,
                                        boundary=T - timedelta(minutes=30 * (2 - n)))
        switched = budget.add_sample(sample)
        assert switched == (n == 2)
    assert budget.mode(T) == "evaluation"
    tomorrow = T + timedelta(minutes=1)
    assert budget.mode(tomorrow) == "rotation"
    for kind, cap in (("base", 96), ("extra", 4)):
        for _ in range(cap):
            budget.before_call(tomorrow, kind)
    with pytest.raises(SearchBudgetStop):
        budget.before_call(tomorrow, "evaluation")
    assert sum(budget.counts(tomorrow).values()) == 100


def test_reject_unfunded_plan():
    with pytest.raises(ValueError, match="planned"):
        SearchBudget(daily_limit=99)


def test_confirmed_actual_count_is_checked_before_call():
    budget = SearchBudget(actual_daily_calls=lambda when: 100)
    with pytest.raises(SearchBudgetStop):
        budget.before_call(T, "base", 1000)
    assert budget.counts(T)["base"] == 0
