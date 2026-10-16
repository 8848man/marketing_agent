import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from marketing_agent.config import AgentConfig
from marketing_agent.fixtures import OFFLINE_VIDEO, OfflineAI, OfflineCaptions
from marketing_agent.logging import EventLogger
from marketing_agent.pipeline import run_cycle
from marketing_agent.storage import Store


NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
CONFIG = AgentConfig(topic="relationships", keywords=("relationships",))


def test_offline_cycle_saves_one_comment_without_post_or_browser(tmp_path):
    output = tmp_path / "comments.jsonl"
    log = tmp_path / "run.log"

    def forbidden(**kwargs):
        raise AssertionError("poster was called")

    with Store(tmp_path / "state.db") as store:
        result = run_cycle(config=CONFIG, store=store, logger=EventLogger(log),
                           dry_run_path=output, screenshot_dir=tmp_path, offline=True,
                           now=NOW, post=forbidden)
        assert store.comment(OFFLINE_VIDEO.video_id)["state"] == "DRY_RUN_SAVED"
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    events = [json.loads(line)["event"] for line in log.read_text(encoding="utf-8").splitlines()]
    assert result["comments"] == 1 and result["post_calls"] == 0
    assert len(records) == 1 and records[0]["input_source"] == "offline_fixture"
    assert {"DETECTED", "CLASSIFIED", "VIEW_SNAPSHOT", "TRIGGER_EVALUATED",
            "COMMENT_WRITTEN", "DRY_RUN_SAVED"} <= set(events)


def test_stage_error_is_logged_and_next_video_is_processed(tmp_path):
    ids = ["abcDEF123_-", "xyzDEF123_-"]

    class API:
        def search(self, **params):
            return {"items": [{"id": {"videoId": video_id}, "snippet": {
                "channelId": "channel", "publishedAt": (NOW - timedelta(hours=2)).isoformat(),
                "title": OFFLINE_VIDEO.title, "description": OFFLINE_VIDEO.description}}
                for video_id in ids]}

        def videos(self, video_ids):
            return {"items": [{"id": video_ids[0], "statistics": {"viewCount": "1500"}}]}

        def comments(self, video_id):
            return []

    class FailingFirstAI:
        def __init__(self):
            self.calls = 0
            self.fallback = OfflineAI()

        def complete_json(self, system, prompt):
            if '"on_topic"' in system:
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("model unavailable")
            return self.fallback.complete_json(system, prompt)

    output = tmp_path / "comments.jsonl"
    log = tmp_path / "run.log"
    with Store(tmp_path / "state.db") as store:
        result = run_cycle(config=CONFIG, store=store, logger=EventLogger(log),
                           dry_run_path=output, screenshot_dir=tmp_path, dry_run=True,
                           api=API(), ai=FailingFirstAI(), captions=OfflineCaptions(), now=NOW)
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert result["errors"] == 1 and result["comments"] == 1 and result["post_calls"] == 0
    assert any(row["video_id"] == ids[0] and row["event"] == "STAGE_ERROR" and
               row["reason"].startswith("classify:") for row in records)
    assert any(row["video_id"] == ids[1] and row["event"] == "DRY_RUN_SAVED" for row in records)
    assert len(output.read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.parametrize("flag", ["--once", "--dry-run", "--offline-fixtures"])
def test_each_safe_flag_is_immediate_and_disables_posting(tmp_path, flag):
    from marketing_agent import __main__

    calls = []

    def fake_cycle(**kwargs):
        calls.append(kwargs)
        return {"run_id": "test", "candidates": 0, "comments": 0, "post_calls": 0, "errors": 0}

    with patch.object(__main__, "load_config", return_value=CONFIG), \
         patch.object(__main__, "run_cycle", side_effect=fake_cycle), \
         patch.object(__main__, "sleep", side_effect=AssertionError("unexpected wait")):
        assert __main__.main([flag, "--db", str(tmp_path / "state.db"),
                              "--output", str(tmp_path / "comments.jsonl"),
                              "--log", str(tmp_path / "events.log")]) == 0
    assert len(calls) == 1 and calls[0]["dry_run"] is True
