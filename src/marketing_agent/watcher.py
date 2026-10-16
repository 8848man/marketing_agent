"""Injectable YouTube search, candidate discovery, and view snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

from .config import AgentConfig
from .search_budget import ComparisonSample, SearchBudget, SearchBudgetStop


class YouTubeAPI(Protocol):
    def search(self, **parameters) -> dict: ...
    def videos(self, ids: list[str]) -> dict: ...


def cycle_times(start: datetime, *, interval_minutes: int = 30, duration_hours: float = 3,
                once: bool = False) -> list[datetime]:
    if start.tzinfo is None or interval_minutes <= 0 or duration_hours < 0:
        raise ValueError("invalid schedule")
    if once:
        return [start]
    count = int(duration_hours * 60 // interval_minutes)
    return [start + timedelta(minutes=interval_minutes * n) for n in range(1, count + 1)]


@dataclass
class CycleResult:
    candidates: list[str] = field(default_factory=list)
    snapshots: list[tuple[str, datetime, int]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    partial: bool = False


class Watcher:
    def __init__(self, api: YouTubeAPI, config: AgentConfig, budget: SearchBudget, *,
                 clock: Callable[[], datetime], remaining_units: Callable[[], int | None] = lambda: None,
                 store=None, logger=None, run_id: str = "watcher"):
        self.api, self.config, self.budget = api, config, budget
        self.clock, self.remaining_units = clock, remaining_units
        self.store, self.logger, self.run_id = store, logger, run_id
        self.candidates: dict[str, dict] = {}
        self.history: dict[str, list[tuple[datetime, int]]] = {}

    def _emit(self, event: str, video_id: str, reason: str, when: datetime):
        if self.logger:
            self.logger.emit(event=event, run_id=self.run_id, video_id=video_id or "-",
                             input_source="live_search", reason=reason, timestamp=when)

    def _parameters(self, query: str, boundary: datetime) -> dict:
        if boundary.tzinfo is None:
            raise ValueError("boundary must be timezone aware")
        after = (boundary - timedelta(hours=self.config.trigger.max_age_hours)).astimezone(timezone.utc)
        return {"part": "snippet", "q": query, "order": "date", "type": "video",
                "regionCode": "KR", "relevanceLanguage": "ko", "publishedAfter": after.isoformat().replace("+00:00", "Z"),
                "maxResults": 50}

    @staticmethod
    def _items(response: dict) -> list[dict]:
        return response.get("items", [])

    @staticmethod
    def _id(item: dict) -> str | None:
        raw = item.get("id")
        return raw.get("videoId") if isinstance(raw, dict) else raw

    def _pages(self, query: str, boundary: datetime, *, first_kind: str,
               extra_kind: str, result: CycleResult) -> tuple[dict[str, dict], bool]:
        params = self._parameters(query, boundary)
        found: dict[str, dict] = {}
        complete = True
        for page in range(2):
            kind = first_kind if page == 0 else extra_kind
            try:
                self.budget.before_call(self.clock(), kind, self.remaining_units())
                response = self.api.search(**params)
            except SearchBudgetStop as exc:
                result.reasons.append(exc.reason)
                self._emit("SEARCH_BUDGET_STOP", "-", exc.reason, self.clock())
                result.partial = complete = False
                break
            except Exception as exc:
                reason = f"SEARCH_API_ERROR:{type(exc).__name__}"
                result.reasons.append(reason)
                self._emit("SEARCH_API_ERROR", "-", reason, self.clock())
                result.partial = complete = False
                break
            items = self._items(response)
            for item in items:
                video_id = self._id(item)
                if video_id:
                    found.setdefault(video_id, item)
            token = response.get("nextPageToken")
            if not token or len(items) < 50:
                break
            if page == 1:
                result.partial = complete = False  # More pages exist than this capped sample can read.
                break
            params = {**params, "pageToken": token}
        return found, complete

    def search_cycle(self, boundary: datetime, *, compare: bool = False,
                     eligible_ids: set[str] | None = None) -> CycleResult:
        result = CycleResult()
        keywords = self.config.keywords
        mode = self.budget.mode(boundary)
        if mode == "rotation":
            # Two keywords per cycle; the fifth appears again every third cycle.
            slot = self.budget.counts(boundary)["base"] // 2
            queries = [keywords[(slot * 2 + offset) % len(keywords)] for offset in range(2)]
        else:
            queries = ["|".join(keywords)]
        or_found: dict[str, dict] = {}
        base_complete = True
        for query in queries:
            found, done = self._pages(query, boundary, first_kind="base", extra_kind="extra", result=result)
            base_complete &= done
            or_found.update(found)
        for video_id, item in or_found.items():
            if video_id not in self.candidates:
                self._emit("DETECTED", video_id, "NEW_CANDIDATE", boundary)
            self.candidates[video_id] = item
            result.candidates.append(video_id)
            if self.store:
                snippet = item.get("snippet", {})
                published = snippet.get("publishedAt")
                published_at = datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None
                prior = self.store.video(video_id)
                if prior is None:
                    self.store.save_video(video_id, snippet.get("channelId", "unknown"), boundary,
                                          published_at=published_at, title=snippet.get("title", ""), state="detected")
                else:
                    # Preserve classification and tracking state on rediscovery.
                    self.store.db.execute("UPDATE processed_videos SET last_seen_at=? WHERE video_id=?",
                                          (boundary.astimezone(timezone.utc).isoformat(timespec="microseconds"), video_id))
        if compare and mode == "evaluation" and len(keywords) == 5 and base_complete:
            individual: set[str] = set()
            complete = True
            for keyword in keywords:
                found, done = self._pages(keyword, boundary, first_kind="evaluation",
                                          extra_kind="evaluation", result=result)
                individual.update(found)
                complete &= done
            sample = ComparisonSample.build(or_found, individual, eligible_ids or set(),
                                            complete=complete and not result.partial, boundary=boundary)
            self.budget.add_sample(sample)
        self.track_views(boundary, result)
        return result

    def run(self, *, start: datetime, duration_hours: float = 3, once: bool = False,
            sleep: Callable[[float], None], compare: bool = False) -> list[CycleResult]:
        """Run scheduled boundaries; a failed cycle leaves later boundaries intact."""
        outcomes = []
        for boundary in cycle_times(start, interval_minutes=self.config.poll_interval_min,
                                    duration_hours=duration_hours, once=once):
            delay = (boundary - self.clock()).total_seconds()
            if delay > 0:
                sleep(delay)
            try:
                outcomes.append(self.search_cycle(boundary, compare=compare))
            except Exception as exc:
                reason = f"CYCLE_ERROR:{type(exc).__name__}"
                self._emit("CYCLE_ERROR", "-", reason, boundary)
                outcomes.append(CycleResult(reasons=[reason], partial=True))
        return outcomes

    def track_views(self, boundary: datetime, result: CycleResult | None = None) -> CycleResult:
        result = result or CycleResult()
        if not self.store:
            return result
        rows = self.store.db.execute("SELECT video_id FROM processed_videos WHERE state='waiting' ORDER BY video_id").fetchall()
        ids = [row["video_id"] for row in rows]
        for offset in range(0, len(ids), 50):
            batch = ids[offset:offset + 50]
            try:
                response = self.api.videos(batch)
            except Exception as exc:
                reason = f"VIDEOS_API_ERROR:{type(exc).__name__}"
                result.reasons.append(reason)
                self._emit("VIDEOS_API_ERROR", "-", reason, boundary)
                continue
            for item in response.get("items", []):
                video_id = item.get("id")
                if video_id not in batch:
                    continue
                try:
                    count = int(item["statistics"]["viewCount"])
                    self.store.add_view(video_id, boundary, count)
                except (KeyError, ValueError, TypeError) as exc:
                    result.reasons.append(f"VIEW_SNAPSHOT_ERROR:{type(exc).__name__}")
                    continue
                result.snapshots.append((video_id, boundary, count))
                self._emit("VIEW_SNAPSHOT", video_id, f"VIEW_COUNT_{count}", boundary)
        return result
