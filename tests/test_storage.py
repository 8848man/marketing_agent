from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest

from marketing_agent.logging import EventLogger
from marketing_agent import storage
from marketing_agent.storage import SCHEMA_VERSION, ReservationBlocked, Store


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


def _unknown_attempt(store, video_id="vOut0000001"):
    attempt_id = store.reserve_reviewed_post(video_id=video_id, channel_id="ch", title="t", body_hash="b",
                                             approval_hash="a", profile="p", when=T)
    store.begin_dashboard_submit(attempt_id, T)
    store.finish_dashboard_post(attempt_id, "OUTCOME_UNKNOWN", reason_code="COMMENT_NOT_CONFIRMED")
    return attempt_id


def test_resolve_outcome_posted_and_dismissed(tmp_path):
    later = T + timedelta(minutes=5)
    with Store(tmp_path / "state.sqlite") as store:
        first = _unknown_attempt(store, "vOut0000001")
        second = _unknown_attempt(store, "vOut0000002")
        store.resolve_dashboard_outcome("vOut0000001", "POSTED", "검토자", later)
        store.resolve_dashboard_outcome("vOut0000002", "DISMISSED", "검토자", later)
        posted = store.dashboard_attempt("vOut0000001")
        assert posted["status"] == "POSTED" and posted["verified_at"]
        assert store.dashboard_attempt("vOut0000002")["status"] == "DISMISSED"
        rows = {r["attempt_id"]: r for r in store.db.execute("SELECT * FROM dashboard_outcome_resolutions")}
        assert rows[first]["outcome"] == "POSTED" and rows[second]["outcome"] == "DISMISSED"
        assert rows[first]["reviewer"] == "검토자" and rows[first]["resolved_at"]


def test_resolve_outcome_rejects_other_states(tmp_path):
    with Store(tmp_path / "state.sqlite") as store:
        store.reserve_reviewed_post(video_id="vOut0000003", channel_id="ch", title="t", body_hash="b",
                                    approval_hash="a", profile="p", when=T)
        _unknown_attempt(store, "vOut0000004")
        for video, outcome, reviewer, code in [
                ("vOut0000003", "POSTED", "x", "OUTCOME_NOT_UNKNOWN"),
                ("vNone000000", "POSTED", "x", "OUTCOME_NOT_UNKNOWN"),
                ("vOut0000004", "RESERVED", "x", "OUTCOME_INVALID"),
                ("vOut0000004", "POSTED", "", "REVIEWER_INVALID"),
                ("vOut0000004", "POSTED", "x" * 41, "REVIEWER_INVALID")]:
            with pytest.raises(ValueError, match=code):
                store.resolve_dashboard_outcome(video, outcome, reviewer, T)
        assert store.dashboard_attempt("vOut0000004")["status"] == "OUTCOME_UNKNOWN"
        store.resolve_dashboard_outcome("vOut0000004", "POSTED", "x", T)
        with pytest.raises(ValueError, match="OUTCOME_NOT_UNKNOWN"):
            store.resolve_dashboard_outcome("vOut0000004", "DISMISSED", "x", T)


def test_dismissed_still_blocks_repost(tmp_path):
    with Store(tmp_path / "state.sqlite") as store:
        _unknown_attempt(store, "vOut0000005")
        store.resolve_dashboard_outcome("vOut0000005", "DISMISSED", "x", T)
        with pytest.raises(ReservationBlocked, match="ALREADY_ATTEMPTED"):
            store.reserve_reviewed_post(video_id="vOut0000005", channel_id="ch", title="t", body_hash="b",
                                        approval_hash="a", profile="p", when=T)
        assert store.dashboard_posts_on("2026-10-15") == 1 or store.dashboard_posts_on("2026-10-16") == 1


def test_old_reservation_table_is_migrated_for_dismissed(tmp_path):
    import sqlite3
    path = tmp_path / "state.sqlite"
    with Store(path) as store:
        _unknown_attempt(store, "vOut0000006")
    db = sqlite3.connect(path)
    db.executescript("""
        ALTER TABLE dashboard_post_reservations RENAME TO _new;
        DROP INDEX dashboard_one_active_video; DROP INDEX dashboard_post_day;
        CREATE TABLE dashboard_post_reservations (
            attempt_id TEXT PRIMARY KEY, video_id TEXT NOT NULL, channel_id TEXT NOT NULL, title TEXT NOT NULL,
            body_hash TEXT NOT NULL, approval_hash TEXT NOT NULL, profile TEXT NOT NULL, attempt_date_kst TEXT NOT NULL,
            reserved_at TEXT NOT NULL, status TEXT NOT NULL
                CHECK(status IN ('RESERVED','SUBMITTING','PRECHECK_FAILED','OUTCOME_UNKNOWN','POSTED')),
            reason_code TEXT, screenshot_path TEXT, verified_at TEXT);
        INSERT INTO dashboard_post_reservations SELECT * FROM _new; DROP TABLE _new;
        CREATE UNIQUE INDEX dashboard_one_active_video ON dashboard_post_reservations(video_id) WHERE status != 'PRECHECK_FAILED';""")
    db.execute("PRAGMA user_version = 0")  # a real pre-versioning DB carries no version
    db.commit()
    db.close()
    with Store(path) as store:
        store.resolve_dashboard_outcome("vOut0000006", "DISMISSED", "x", T)
        assert store.dashboard_attempt("vOut0000006")["status"] == "DISMISSED"


# ---- R4-T3 / IMP-40: schema version and migrations ----

def _user_version(path):
    con = sqlite3.connect(path)
    try:
        return con.execute("PRAGMA user_version").fetchone()[0]
    finally:
        con.close()


# Round-2 era (commit 2fcbe07) reservation schema: status CHECK has no DISMISSED.
ROUND2_SCHEMA = """
    CREATE TABLE dashboard_post_reservations (
        attempt_id TEXT PRIMARY KEY, video_id TEXT NOT NULL,
        channel_id TEXT NOT NULL, title TEXT NOT NULL,
        body_hash TEXT NOT NULL, approval_hash TEXT NOT NULL,
        profile TEXT NOT NULL, attempt_date_kst TEXT NOT NULL,
        reserved_at TEXT NOT NULL, status TEXT NOT NULL
            CHECK(status IN ('RESERVED','SUBMITTING','PRECHECK_FAILED','OUTCOME_UNKNOWN','POSTED')),
        reason_code TEXT, screenshot_path TEXT, verified_at TEXT
    );
    CREATE UNIQUE INDEX dashboard_one_active_video
        ON dashboard_post_reservations(video_id)
        WHERE status != 'PRECHECK_FAILED';
    CREATE INDEX dashboard_post_day
        ON dashboard_post_reservations(attempt_date_kst, status);
    CREATE TABLE dashboard_post_bodies (
        attempt_id TEXT PRIMARY KEY, body TEXT NOT NULL
    );
"""


def test_new_db_gets_schema_version(tmp_path):
    path = tmp_path / "new.db"
    with Store(path):
        pass
    assert SCHEMA_VERSION >= 1
    assert _user_version(path) == SCHEMA_VERSION


def test_existing_unversioned_db_is_upgraded_without_data_loss(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(ROUND2_SCHEMA)
    con.execute("INSERT INTO dashboard_post_reservations VALUES"
                "('a1','v1','c1','t','bh','ah','p1','2026-10-01','2026-10-01T00:00:00+00:00',"
                "'OUTCOME_UNKNOWN','TIMEOUT',NULL,NULL)")
    con.execute("INSERT INTO dashboard_post_bodies VALUES('a1','hello body')")
    con.commit()
    assert con.execute("PRAGMA user_version").fetchone()[0] == 0
    con.close()

    with Store(path) as store:
        row = store.db.execute("SELECT * FROM dashboard_post_reservations").fetchall()
        assert [(r["attempt_id"], r["video_id"], r["status"], r["reason_code"]) for r in row] == [
            ("a1", "v1", "OUTCOME_UNKNOWN", "TIMEOUT")]
        assert store.db.execute("SELECT body FROM dashboard_post_bodies WHERE attempt_id='a1'").fetchone()["body"] == "hello body"
        indexes = {r["name"] for r in store.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='dashboard_post_reservations'")}
        assert {"dashboard_one_active_video", "dashboard_post_day"} <= indexes
        assert "DISMISSED" in store.db.execute(
            "SELECT sql FROM sqlite_master WHERE name='dashboard_post_reservations'").fetchone()["sql"]
        assert store.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        # the rebuilt table accepts the new status
        store.db.execute("UPDATE dashboard_post_reservations SET status='DISMISSED' WHERE attempt_id='a1'")


def test_newer_db_is_rejected(tmp_path):
    path = tmp_path / "newer.db"
    with Store(path):
        pass
    con = sqlite3.connect(path)
    con.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    con.close()
    with pytest.raises(ValueError, match="DB_SCHEMA_NEWER"):
        Store(path)
    assert _user_version(path) == SCHEMA_VERSION + 1


def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    with Store(path):
        pass

    def broken(db):
        db.execute("CREATE TABLE half_applied (x INTEGER)")
        raise RuntimeError("boom")

    monkeypatch.setattr(storage, "MIGRATIONS", [*storage.MIGRATIONS, broken])
    with pytest.raises(RuntimeError, match="boom"):
        Store(path)
    assert _user_version(path) == SCHEMA_VERSION
    con = sqlite3.connect(path)
    try:
        assert con.execute("SELECT name FROM sqlite_master WHERE name='half_applied'").fetchone() is None
    finally:
        con.close()
