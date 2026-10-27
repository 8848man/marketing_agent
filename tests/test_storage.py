from datetime import datetime, timedelta, timezone
import json

import pytest

from marketing_agent.logging import EventLogger
from marketing_agent.storage import ReservationBlocked, Store


T = datetime(2026, 10, 15, 14, 59, tzinfo=timezone.utc)  # KST 23:59


def prepare(store, video_id, when=T, channel="target"):
    store.save_video(video_id, channel, when)
    store.add_view(video_id, when, 1200)
    comment_id = store.save_comment(video_id, "A useful comment", when)
    store.register_owned_video(video_id, "owner", when, "evidence/local.png")
    return comment_id


def reserve(store, video_id, comment_id, when=T, channel="target", **kwargs):
    return store.reserve_post(video_id=video_id, comment_id=comment_id, run_id="run-1", input_source="fixture", body_hash="digest", author_channel_id="owner", target_channel_id=channel, when=when, **kwargs)


def test_restart_and_transition(tmp_path):
    path = tmp_path / "state.sqlite"
    with Store(path) as store:
        cid = prepare(store, "v1")
        attempt_id = reserve(store, "v1", cid)
        assert store.attempt("v1")["status"] == "POST_PENDING"
        store.set_post_status(attempt_id, "POST_OUTCOME_UNKNOWN", reason_code="TIMEOUT")
    with Store(path) as store:
        assert store.views("v1")[0]["view_count"] == 1200
        assert store.comment("v1")["body"] == "A useful comment"
        assert store.ownership("v1")["owner_channel_id"] == "owner"
        assert store.attempt("v1")["attempt_id"] == attempt_id
        assert store.daily_attempts(T) == 1
        with pytest.raises(ReservationBlocked, match="ALREADY_ATTEMPTED"):
            reserve(store, "v1", cid, T + timedelta(days=2))
        store.set_post_status(attempt_id, "POSTED", verified_at=T + timedelta(minutes=5))
        with pytest.raises(ValueError):
            store.set_post_status(attempt_id, "POST_FAILED")


def test_daily_limit_kst_boundary_and_cooldown(tmp_path):
    with Store(tmp_path / "state.sqlite") as store:
        for n in range(10):
            vid = f"v{n}"
            aid = reserve(store, vid, prepare(store, vid), channel=f"c{n}")
            store.set_post_status(aid, "POST_FAILED", reason_code="UI_ERROR")
        cid = prepare(store, "v10")
        with pytest.raises(ReservationBlocked, match="DAILY_LIMIT"):
            reserve(store, "v10", cid, channel="c10")
        next_day = T + timedelta(minutes=1)
        assert store.daily_attempts(next_day) == 0
        with pytest.raises(ReservationBlocked, match="CHANNEL_COOLDOWN"):
            reserve(store, "v10", cid, next_day, channel="c0")
        aid = reserve(store, "v10", cid, T + timedelta(hours=24), channel="c0")
        assert store.attempt("v10")["attempt_id"] == aid
        assert store.daily_attempts(T + timedelta(hours=24)) == 1


def test_precheck_and_failed_reservation_do_not_consume_quota(tmp_path):
    with Store(tmp_path / "state.sqlite") as store:
        event_id = store.record_precheck_failure("v1", "r", "OWNERSHIP_BLOCKED", T)
        assert event_id
        assert store.daily_attempts(T) == 0
        cid = prepare(store, "v1")
        with pytest.raises(ReservationBlocked, match="COMMENT_MISSING"):
            reserve(store, "v1", "wrong")
        assert store.attempt("v1") is None
        assert reserve(store, "v1", cid)


def test_structured_log_redacts_secrets(tmp_path):
    path = tmp_path / "events.jsonl"
    writer = EventLogger(path)
    with pytest.raises(ValueError):
        writer.emit(event="POST_PENDING", run_id="r", video_id="v", input_source="fixture", reason="OK")
    writer.emit(event="POST_PENDING", run_id="r", video_id="v", input_source="fixture", reason="token=abc cookie: xyz", attempt_id="a")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert (record["run_id"], record["video_id"], record["event"], record["attempt_id"]) == ("r", "v", "POST_PENDING", "a")
    assert "abc" not in str(record) and "xyz" not in str(record)


def _reviewed(store, video_id, channel, when, **kwargs):
    return store.reserve_reviewed_post(video_id=video_id, channel_id=channel, title="title",
                                       body_hash="body", approval_hash="approved", profile="p1",
                                       when=when, **kwargs)


def test_reviewed_post_channel_cooldown_blocks_within_window(tmp_path):
    with Store(tmp_path / "state.sqlite") as store:
        _reviewed(store, "video000001", "chan-a", T, cooldown_minutes=60)
        with pytest.raises(ReservationBlocked, match="CHANNEL_COOLDOWN"):
            _reviewed(store, "video000002", "chan-a", T + timedelta(minutes=59), cooldown_minutes=60)
        assert store.dashboard_attempt("video000002") is None
        assert _reviewed(store, "video000002", "chan-a", T + timedelta(minutes=61), cooldown_minutes=60)


def test_reviewed_post_cooldown_ignores_precheck_failed_and_other_channels(tmp_path):
    with Store(tmp_path / "state.sqlite") as store:
        first = _reviewed(store, "video000001", "chan-a", T, cooldown_minutes=60)
        store.finish_dashboard_post(first, "PRECHECK_FAILED", reason_code="LOGIN_REQUIRED")
        assert _reviewed(store, "video000002", "chan-a", T + timedelta(minutes=1), cooldown_minutes=60)
        assert _reviewed(store, "video000003", "chan-b", T + timedelta(minutes=2), cooldown_minutes=60)


def test_reviewed_post_cooldown_rejects_invalid_value(tmp_path):
    with Store(tmp_path / "state.sqlite") as store:
        for bad in (-1, True, 1.5, "60"):
            with pytest.raises(ValueError):
                _reviewed(store, "video000001", "chan-a", T, cooldown_minutes=bad)
