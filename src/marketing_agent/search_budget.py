"""KST search call accounting and evidence based query strategy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
SEARCH_UNIT_COST_ASSUMPTION = 100  # Unverified until the project's M1 quota check.


class SearchBudgetStop(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ComparisonSample:
    or_ids: frozenset[str]
    individual_ids: frozenset[str]
    eligible_individual_ids: frozenset[str]
    complete: bool
    boundary: datetime
    discovery_rate: float | None
    missed_eligible_ids: frozenset[str]

    @classmethod
    def build(cls, or_ids, individual_ids, eligible_individual_ids, *, complete, boundary):
        individual = frozenset(individual_ids)
        or_set = frozenset(or_ids)
        missed = frozenset(eligible_individual_ids) & (individual - or_set)
        rate = len(or_set & individual) / len(individual) if individual else None
        return cls(or_set, individual, frozenset(eligible_individual_ids), complete,
                   boundary, rate, missed)


@dataclass
class SearchBudget:
    daily_limit: int = 100
    search_unit_cost: int = SEARCH_UNIT_COST_ASSUMPTION
    unit_cost_verified: bool = False
    actual_daily_calls: Callable[[datetime], int] | None = None
    calls: dict[date, dict[str, int]] = field(default_factory=dict)
    samples: list[ComparisonSample] = field(default_factory=list)
    rotation_from: date | None = None

    def __post_init__(self):
        if self.daily_limit <= 0 or self.search_unit_cost <= 0:
            raise ValueError("budget and unit cost must be positive")
        if self.daily_limit < 100:
            raise ValueError("planned 48+36+16 or 96+4 searches exceed daily limit")

    @property
    def unit_cost_label(self) -> str:
        return "verified" if self.unit_cost_verified else "unverified_assumption"

    def mode(self, when: datetime) -> str:
        day = self._day(when)
        return "rotation" if self.rotation_from and day >= self.rotation_from else "evaluation"

    @staticmethod
    def _day(when: datetime) -> date:
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("time must be timezone aware")
        return when.astimezone(KST).date()

    def counts(self, when: datetime) -> dict[str, int]:
        return dict(self.calls.get(self._day(when), {"base": 0, "evaluation": 0, "extra": 0}))

    def before_call(self, when: datetime, kind: str, remaining_units: int | None = None) -> None:
        """Inspect confirmed units immediately before each actual search call."""
        mode = self.mode(when)
        caps = {"base": 96, "evaluation": 0, "extra": 4} if mode == "rotation" else {
            "base": 48, "evaluation": 36, "extra": 16}
        if kind not in caps:
            raise ValueError("unknown search category")
        counts = self.counts(when)
        actual = self.actual_daily_calls(when) if self.actual_daily_calls else sum(counts.values())
        if counts[kind] >= caps[kind] or max(actual, sum(counts.values())) >= self.daily_limit:
            raise SearchBudgetStop("SEARCH_BUDGET_STOP")
        if remaining_units is not None and remaining_units < self.search_unit_cost:
            raise SearchBudgetStop("SEARCH_BUDGET_STOP_UNITS")
        self.calls.setdefault(self._day(when), {"base": 0, "evaluation": 0, "extra": 0})[kind] += 1

    def add_sample(self, sample: ComparisonSample) -> bool:
        """A complete, nonempty denominator may decide rotation on the next KST day."""
        if not sample.complete or sample.discovery_rate is None:
            return False
        if any(abs((sample.boundary - prior.boundary).total_seconds()) < 1800
               for prior in self.samples):
            return False
        self.samples.append(sample)
        if len(self.samples) < 3 or self.rotation_from is not None:
            return False
        if any(s.discovery_rate < .9 or s.missed_eligible_ids for s in self.samples):
            self.rotation_from = max(self._day(s.boundary) for s in self.samples) + timedelta(days=1)
            return True
        return False
