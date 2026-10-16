from datetime import datetime, timedelta, timezone

from marketing_agent.config import AgentConfig
from marketing_agent.search_budget import SearchBudget
from marketing_agent.storage import Store
from marketing_agent.watcher import Watcher, cycle_times


T = datetime(2026, 10, 15, 3, tzinfo=timezone.utc)


class FakeAPI:
    def __init__(self):
        self.search_calls = []
        self.video_calls = []
        self.fail = False

    def search(self, **params):
        self.search_calls.append(params)
        if self.fail:
            raise RuntimeError("offline")
        return {"items": [{"id": {"videoId": "same"}, "snippet": {"channelId": "c"}},
                          {"id": {"videoId": "same"}, "snippet": {"channelId": "c"}}]}

    def videos(self, ids):
        self.video_calls.append(ids)
        return {"items": [{"id": video_id, "statistics": {"viewCount": "1200"}} for video_id in ids]}


def test_schedule_first_cycle_and_six_boundaries():
    assert cycle_times(T) == [T + timedelta(minutes=30 * n) for n in range(1, 7)]
    assert cycle_times(T, once=True) == [T]


def test_run_waits_then_continues_after_api_error():
    api = FakeAPI()
    now = T
    delays = []

    def sleep(seconds):
        nonlocal now
        delays.append(seconds)
        now += timedelta(seconds=seconds)

    watcher = Watcher(api, AgentConfig("dating", ("a", "b", "c", "d", "e")),
                      SearchBudget(), clock=lambda: now)
    api.fail = True
    outcomes = watcher.run(start=T, sleep=sleep)
    assert len(outcomes) == 6
    assert delays == [1800] * 6
    assert len(api.search_calls) == 6
    assert all(result.reasons == ["SEARCH_API_ERROR:RuntimeError"] for result in outcomes)


def test_query_dedup_and_api_recovery(tmp_path):
    api = FakeAPI()
    config = AgentConfig("dating", ("a", "b", "c", "d", "e"))
    budget = SearchBudget()
    with Store(tmp_path / "state.sqlite") as store:
        watcher = Watcher(api, config, budget, clock=lambda: T, store=store)
        result = watcher.search_cycle(T)
        assert result.candidates == ["same"]
        params = api.search_calls[0]
        assert (params["q"], params["order"], params["type"], params["regionCode"],
                params["relevanceLanguage"], params["maxResults"]) == ("a|b|c|d|e", "date", "video", "KR", "ko", 50)
        assert params["publishedAfter"] == (T - timedelta(hours=12)).isoformat().replace("+00:00", "Z")
        assert store.db.execute("SELECT COUNT(*) FROM processed_videos").fetchone()[0] == 1
        api.fail = True
        assert watcher.search_cycle(T + timedelta(minutes=30)).reasons == ["SEARCH_API_ERROR:RuntimeError"]
        api.fail = False
        assert watcher.search_cycle(T + timedelta(hours=1)).candidates == ["same"]
        assert store.db.execute("SELECT COUNT(*) FROM processed_videos").fetchone()[0] == 1


def test_full_page_cap_budget_stop_and_snapshots(tmp_path):
    api = FakeAPI()
    config = AgentConfig("dating", ("a", "b", "c", "d", "e"))
    with Store(tmp_path / "state.sqlite") as store:
        for n in range(51):
            store.save_video(f"v{n:02}", "c", T, state="waiting")
        store.save_video("expired", "c", T, state="expired")
        remaining = 99
        watcher = Watcher(api, config, SearchBudget(), clock=lambda: T,
                          remaining_units=lambda: remaining, store=store)
        assert watcher.search_cycle(T).reasons == ["SEARCH_BUDGET_STOP_UNITS"]
        assert api.search_calls == []
        remaining = 100
        for n in range(1, 3):
            watcher.track_views(T + timedelta(minutes=30 * n))
        assert len(store.views("v00")) == 3
        assert len(api.video_calls) == 6
        assert all("expired" not in batch and len(batch) <= 50 for batch in api.video_calls)
