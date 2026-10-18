"""Durable video and posting state. A reservation commits before UI submission."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
STATUSES = {"POST_PENDING", "POST_FAILED", "POST_OUTCOME_UNKNOWN", "POSTED"}
TRANSITIONS = {
    "POST_PENDING": {"POST_FAILED", "POST_OUTCOME_UNKNOWN", "POSTED"},
    "POST_OUTCOME_UNKNOWN": {"POSTED"},
    "POST_FAILED": set(),
    "POSTED": set(),
}


class ReservationBlocked(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _aware(when: datetime) -> datetime:
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return when.astimezone(timezone.utc)


def _stamp(when: datetime) -> str:
    return _aware(when).isoformat(timespec="microseconds")


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA busy_timeout = 30000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS processed_videos (
                video_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL,
                published_at TEXT, title TEXT, state TEXT NOT NULL,
                classified_reason TEXT, used_captions INTEGER,
                last_seen_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS view_history (
                video_id TEXT NOT NULL REFERENCES processed_videos(video_id),
                observed_at TEXT NOT NULL, view_count INTEGER NOT NULL CHECK(view_count >= 0),
                PRIMARY KEY(video_id, observed_at)
            );
            CREATE TABLE IF NOT EXISTS comments (
                comment_id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL UNIQUE REFERENCES processed_videos(video_id),
                worry_summary TEXT, cited_detail TEXT, body TEXT NOT NULL,
                source TEXT, fit_result TEXT,
                state TEXT NOT NULL CHECK(state IN ('COMMENT_WRITTEN','DRY_RUN_SAVED')),
                dry_run_path TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS owned_test_videos (
                video_id TEXT PRIMARY KEY REFERENCES processed_videos(video_id),
                owner_channel_id TEXT NOT NULL, verified_at TEXT NOT NULL,
                evidence_path TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS post_results (
                attempt_id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL UNIQUE REFERENCES processed_videos(video_id),
                comment_id TEXT NOT NULL REFERENCES comments(comment_id),
                run_id TEXT NOT NULL, input_source TEXT NOT NULL,
                attempted_at_kst TEXT NOT NULL, attempt_date_kst TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('POST_PENDING','POST_FAILED','POST_OUTCOME_UNKNOWN','POSTED')),
                body_hash TEXT NOT NULL, author_channel_id TEXT NOT NULL,
                target_channel_id TEXT NOT NULL, reason_code TEXT,
                screenshot_path TEXT, verified_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_post_date ON post_results(attempt_date_kst);
            CREATE INDEX IF NOT EXISTS idx_post_target ON post_results(target_channel_id, attempted_at_kst);
            CREATE TABLE IF NOT EXISTS channel_cooldowns (
                target_channel_id TEXT PRIMARY KEY, last_attempted_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS post_precheck_failures (
                precheck_event_id TEXT PRIMARY KEY, video_id TEXT NOT NULL,
                run_id TEXT NOT NULL, failed_at_kst TEXT NOT NULL,
                reason_code TEXT NOT NULL, screenshot_path TEXT
            );
        """)
        # Kept separate from the legacy CLI table so its history and constraints
        # remain intact. A partial unique index permits only pre-click failures
        # to be retried, while retaining every failed decision for audit.
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS dashboard_post_reservations (
                attempt_id TEXT PRIMARY KEY, video_id TEXT NOT NULL,
                channel_id TEXT NOT NULL, title TEXT NOT NULL,
                body_hash TEXT NOT NULL, approval_hash TEXT NOT NULL,
                profile TEXT NOT NULL, attempt_date_kst TEXT NOT NULL,
                reserved_at TEXT NOT NULL, status TEXT NOT NULL
                    CHECK(status IN ('RESERVED','SUBMITTING','PRECHECK_FAILED','OUTCOME_UNKNOWN','POSTED')),
                reason_code TEXT, screenshot_path TEXT, verified_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS dashboard_one_active_video
                ON dashboard_post_reservations(video_id)
                WHERE status != 'PRECHECK_FAILED';
            CREATE INDEX IF NOT EXISTS dashboard_post_day
                ON dashboard_post_reservations(attempt_date_kst, status);
            CREATE TABLE IF NOT EXISTS dashboard_video_assignments (
                video_id TEXT PRIMARY KEY, profile TEXT,
                assigned_at TEXT NOT NULL, source TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dashboard_assignment_cursor (
                id INTEGER PRIMARY KEY CHECK(id=1), profile TEXT NOT NULL
            );
            -- IMP-19: last confirmed sign-in per app profile (no account data),
            -- and the candidate list the current assignments were balanced for.
            CREATE TABLE IF NOT EXISTS dashboard_profile_status (
                label TEXT PRIMARY KEY, active INTEGER NOT NULL CHECK(active IN (0,1)),
                confirmed_at TEXT, changed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dashboard_assignment_meta (
                id INTEGER PRIMARY KEY CHECK(id=1), candidates TEXT NOT NULL
            );
            -- Comment text shown in the history panel (R-LOG-01). Kept beside the
            -- reservation table so older databases need no column migration.
            CREATE TABLE IF NOT EXISTS dashboard_post_bodies (
                attempt_id TEXT PRIMARY KEY, body TEXT NOT NULL
            );
        """)

    def assign_dashboard_videos(self, cards, candidates: list[str], when: datetime) -> None:
        """Assign only new videos in stable order, with one durable round-robin cursor."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.db.execute(
                "SELECT profile FROM dashboard_assignment_cursor WHERE id=1").fetchone()
            previous = cursor["profile"] if cursor else ""
            for card in sorted(cards, key=lambda item: (item.published_at, item.video_id)):
                existing = self.db.execute(
                    "SELECT profile,source FROM dashboard_video_assignments WHERE video_id=?",
                    (card.video_id,)).fetchone()
                if existing and not (existing["source"] == "no_candidate" and candidates):
                    continue
                old = self.db.execute(
                    "SELECT profile FROM dashboard_post_reservations WHERE video_id=? "
                    "ORDER BY reserved_at LIMIT 1", (card.video_id,)).fetchone()
                legacy = self.db.execute("SELECT 1 FROM post_results WHERE video_id=?",
                                         (card.video_id,)).fetchone()
                if old:
                    profile, source = old["profile"], "existing_post"
                elif legacy:
                    profile, source = None, "legacy_post_unknown"
                elif candidates:
                    after = [label for label in candidates if label > previous]
                    profile, source = (after or candidates)[0], "auto"
                    previous = profile
                else:
                    profile, source = None, "no_candidate"
                if existing:
                    self.db.execute("UPDATE dashboard_video_assignments SET profile=?, assigned_at=?, source=? "
                                    "WHERE video_id=?", (profile, _stamp(when), source, card.video_id))
                else:
                    self.db.execute("INSERT INTO dashboard_video_assignments VALUES(?,?,?,?)",
                                    (card.video_id, profile, _stamp(when), source))
            if previous:
                self.db.execute("INSERT INTO dashboard_assignment_cursor VALUES(1,?) "
                                "ON CONFLICT(id) DO UPDATE SET profile=excluded.profile", (previous,))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def profile_status(self) -> dict[str, dict]:
        rows = self.db.execute("SELECT label,active,confirmed_at FROM dashboard_profile_status").fetchall()
        return {row["label"]: {"active": bool(row["active"]), "confirmed_at": row["confirmed_at"] or ""}
                for row in rows}

    def set_profile_active(self, label: str, active: bool, when: datetime) -> None:
        stamp = _stamp(when)
        with self.db:
            if active:
                self.db.execute(
                    "INSERT INTO dashboard_profile_status VALUES(?,1,?,?) ON CONFLICT(label) DO UPDATE "
                    "SET active=1, confirmed_at=excluded.confirmed_at, changed_at=excluded.changed_at",
                    (label, stamp, stamp))
            else:
                self.db.execute(
                    "INSERT INTO dashboard_profile_status VALUES(?,0,NULL,?) ON CONFLICT(label) DO UPDATE "
                    "SET active=0, changed_at=excluded.changed_at", (label, stamp))

    def assignment_candidates_key(self) -> str | None:
        row = self.db.execute("SELECT candidates FROM dashboard_assignment_meta WHERE id=1").fetchone()
        return row["candidates"] if row else None

    def rebalance_dashboard_assignments(self, cards, candidates: list[str], when: datetime) -> int:
        """Re-spread videos without any post attempt over ``candidates`` (IMP-19).

        Videos are taken oldest first and dealt in candidate order. Videos with a
        reservation, a legacy post, or an earlier post-based assignment keep
        their profile. Returns how many assignments changed.
        """
        key = json.dumps(candidates, ensure_ascii=False)
        changed = 0
        self.db.execute("BEGIN IMMEDIATE")
        try:
            index = 0
            last = ""
            for card in sorted(cards, key=lambda item: (item.published_at, item.video_id)):
                row = self.db.execute(
                    "SELECT profile,source FROM dashboard_video_assignments WHERE video_id=?",
                    (card.video_id,)).fetchone()
                if row is None or row["source"] in ("existing_post", "legacy_post_unknown"):
                    continue
                if self.db.execute("SELECT 1 FROM dashboard_post_reservations WHERE video_id=?",
                                   (card.video_id,)).fetchone():
                    continue
                if self.db.execute("SELECT 1 FROM post_results WHERE video_id=?",
                                   (card.video_id,)).fetchone():
                    continue
                if candidates:
                    target, source = candidates[index % len(candidates)], "rebalance"
                    index += 1
                    last = target
                else:
                    target, source = None, "no_candidate"
                if row["profile"] != target:
                    changed += 1
                    self.db.execute("UPDATE dashboard_video_assignments SET profile=?, assigned_at=?, source=? "
                                    "WHERE video_id=?", (target, _stamp(when), source, card.video_id))
            if last:
                self.db.execute("INSERT INTO dashboard_assignment_cursor VALUES(1,?) "
                                "ON CONFLICT(id) DO UPDATE SET profile=excluded.profile", (last,))
            self.db.execute("INSERT INTO dashboard_assignment_meta VALUES(1,?) "
                            "ON CONFLICT(id) DO UPDATE SET candidates=excluded.candidates", (key,))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return changed

    def dashboard_assignment(self, video_id: str):
        return self.db.execute("SELECT * FROM dashboard_video_assignments WHERE video_id=?",
                               (video_id,)).fetchone()

    def dashboard_post_status(self, video_id: str) -> str:
        row = self.db.execute("SELECT status FROM dashboard_post_reservations WHERE video_id=? "
                              "AND status!='PRECHECK_FAILED' ORDER BY reserved_at DESC LIMIT 1",
                              (video_id,)).fetchone()
        if row:
            return row["status"]
        row = self.db.execute("SELECT status FROM post_results WHERE video_id=?", (video_id,)).fetchone()
        return row["status"] if row else ""

    def latest_posted_video_for_channels(self, channel_ids: set[str]):
        """Return a previously confirmed watch target without changing posting state."""
        if not channel_ids:
            return None
        placeholders = ",".join("?" for _ in channel_ids)
        return self.db.execute(
            "SELECT video_id, channel_id, title FROM dashboard_post_reservations "
            f"WHERE status='POSTED' AND channel_id IN ({placeholders}) "
            "ORDER BY verified_at DESC LIMIT 1", tuple(sorted(channel_ids))).fetchone()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def video(self, video_id: str):
        return self.db.execute("SELECT * FROM processed_videos WHERE video_id=?", (video_id,)).fetchone()

    def save_video(self, video_id: str, channel_id: str, seen_at: datetime, *, published_at: datetime | None = None, title: str = "", state: str = "detected", classified_reason: str | None = None, used_captions: bool | None = None) -> None:
        self.db.execute("""INSERT INTO processed_videos VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(video_id) DO UPDATE SET last_seen_at=excluded.last_seen_at,
            state=excluded.state, classified_reason=excluded.classified_reason,
            used_captions=excluded.used_captions""",
            (video_id, channel_id, _stamp(published_at) if published_at else None, title, state, classified_reason, used_captions, _stamp(seen_at)))

    def add_view(self, video_id: str, observed_at: datetime, view_count: int) -> None:
        if isinstance(view_count, bool) or not isinstance(view_count, int) or view_count < 0:
            raise ValueError("view_count must be nonnegative")
        self.db.execute("INSERT INTO view_history VALUES(?,?,?)", (video_id, _stamp(observed_at), view_count))

    def views(self, video_id: str):
        return self.db.execute("SELECT * FROM view_history WHERE video_id=? ORDER BY observed_at", (video_id,)).fetchall()

    def save_comment(self, video_id: str, body: str, created_at: datetime, *, comment_id: str | None = None, state: str = "COMMENT_WRITTEN", worry_summary: str | None = None, cited_detail: str | None = None, source: str | None = None, fit_result: str | None = None, dry_run_path: str | None = None) -> str:
        if state not in {"COMMENT_WRITTEN", "DRY_RUN_SAVED"} or not body:
            raise ValueError("invalid comment")
        comment_id = comment_id or uuid4().hex
        self.db.execute("INSERT INTO comments VALUES(?,?,?,?,?,?,?,?,?,?)", (comment_id, video_id, worry_summary, cited_detail, body, source, fit_result, state, dry_run_path, _stamp(created_at)))
        return comment_id

    def comment(self, video_id: str):
        return self.db.execute("SELECT * FROM comments WHERE video_id=?", (video_id,)).fetchone()

    def register_owned_video(self, video_id: str, owner_channel_id: str, verified_at: datetime, evidence_path: str) -> None:
        if not owner_channel_id or not evidence_path:
            raise ValueError("ownership requires channel and evidence")
        self.db.execute("""INSERT INTO owned_test_videos VALUES(?,?,?,?)
            ON CONFLICT(video_id) DO UPDATE SET owner_channel_id=excluded.owner_channel_id,
            verified_at=excluded.verified_at, evidence_path=excluded.evidence_path""",
            (video_id, owner_channel_id, _stamp(verified_at), evidence_path))

    def ownership(self, video_id: str):
        return self.db.execute("SELECT * FROM owned_test_videos WHERE video_id=?", (video_id,)).fetchone()

    def record_precheck_failure(self, video_id: str, run_id: str, reason_code: str, when: datetime, *, screenshot_path: str | None = None) -> str:
        event_id = uuid4().hex
        self.db.execute("INSERT INTO post_precheck_failures VALUES(?,?,?,?,?,?)", (event_id, video_id, run_id, _aware(when).astimezone(KST).isoformat(), reason_code, screenshot_path))
        return event_id

    def attempt(self, video_id: str):
        return self.db.execute("SELECT * FROM post_results WHERE video_id=?", (video_id,)).fetchone()

    def daily_attempts(self, when: datetime) -> int:
        day = _aware(when).astimezone(KST).date().isoformat()
        return self.db.execute("SELECT COUNT(DISTINCT attempt_id) FROM post_results WHERE attempt_date_kst=?", (day,)).fetchone()[0]

    def dashboard_attempt(self, video_id: str):
        return self.db.execute("SELECT * FROM dashboard_post_reservations WHERE video_id=? AND status!='PRECHECK_FAILED'", (video_id,)).fetchone()

    def _dashboard_count(self, day: str) -> int:
        current = self.db.execute("SELECT COUNT(*) FROM dashboard_post_reservations WHERE attempt_date_kst=? AND status!='PRECHECK_FAILED'", (day,)).fetchone()[0]
        legacy = self.db.execute("SELECT COUNT(*) FROM post_results WHERE attempt_date_kst=? AND status IN ('POST_PENDING','POST_OUTCOME_UNKNOWN','POSTED')", (day,)).fetchone()[0]
        return current + legacy

    def reserve_reviewed_post(self, *, video_id: str, channel_id: str, title: str,
                              body_hash: str, approval_hash: str, profile: str,
                              when: datetime, daily_limit: int = 10, local_tz=KST,
                              body: str = "") -> str:
        """Reserve across processes before any Chrome work; include legacy posts."""
        utc = _aware(when)
        if not all(isinstance(x, str) and x for x in (video_id, channel_id, title, body_hash, approval_hash, profile)):
            raise ValueError("reservation fields cannot be empty")
        if isinstance(daily_limit, bool) or not isinstance(daily_limit, int) or daily_limit <= 0:
            raise ValueError("daily_limit must be positive")
        day = utc.astimezone(local_tz).date().isoformat()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.attempt(video_id) or self.dashboard_attempt(video_id):
                raise ReservationBlocked("ALREADY_ATTEMPTED")
            if self._dashboard_count(day) >= daily_limit:
                raise ReservationBlocked("DAILY_LIMIT")
            attempt_id = uuid4().hex
            self.db.execute("""INSERT INTO dashboard_post_reservations
                (attempt_id,video_id,channel_id,title,body_hash,approval_hash,profile,attempt_date_kst,reserved_at,status)
                VALUES(?,?,?,?,?,?,?,?,?,'RESERVED')""",
                (attempt_id, video_id, channel_id, title, body_hash, approval_hash, profile, day, _stamp(utc)))
            if body:
                self.db.execute("INSERT INTO dashboard_post_bodies VALUES(?,?)", (attempt_id, body))
            self.db.execute("COMMIT")
            return attempt_id
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def begin_dashboard_submit(self, attempt_id: str, when: datetime, *, daily_limit: int = 10, local_tz=KST) -> None:
        """Move a reservation to the click date, then mark outcome uncertain."""
        day = _aware(when).astimezone(local_tz).date().isoformat()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT status,attempt_date_kst FROM dashboard_post_reservations WHERE attempt_id=?", (attempt_id,)).fetchone()
            if row is None or row["status"] != "RESERVED":
                raise ReservationBlocked("RESERVATION_NOT_PENDING")
            if row["attempt_date_kst"] != day and self._dashboard_count(day) >= daily_limit:
                raise ReservationBlocked("DAILY_LIMIT")
            self.db.execute("UPDATE dashboard_post_reservations SET status='SUBMITTING', attempt_date_kst=? WHERE attempt_id=?", (day, attempt_id))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def dashboard_history(self, limit: int = 50) -> list[dict]:
        """Newest-first posting attempts for the dashboard history panel."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be 1..500")
        rows = self.db.execute(
            "SELECT r.*, b.body FROM dashboard_post_reservations r "
            "LEFT JOIN dashboard_post_bodies b ON b.attempt_id = r.attempt_id "
            "ORDER BY r.reserved_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def dashboard_posts_on(self, day: str) -> int:
        return self._dashboard_count(day)

    def finish_dashboard_post(self, attempt_id: str, status: str, *, reason_code: str | None = None,
                              screenshot_path: str | None = None, verified_at: datetime | None = None) -> None:
        if status not in {"PRECHECK_FAILED", "OUTCOME_UNKNOWN", "POSTED"}:
            raise ValueError("invalid dashboard status")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT status FROM dashboard_post_reservations WHERE attempt_id=?", (attempt_id,)).fetchone()
            old = row["status"] if row else None
            if not ((old == "RESERVED" and status == "PRECHECK_FAILED") or
                    (old == "SUBMITTING" and status in {"OUTCOME_UNKNOWN", "POSTED"}) or
                    (old == "OUTCOME_UNKNOWN" and status == "POSTED")):
                raise ValueError("invalid dashboard transition")
            if status == "POSTED" and verified_at is None:
                raise ValueError("POSTED needs verification time")
            self.db.execute("""UPDATE dashboard_post_reservations SET status=?,reason_code=?,
                screenshot_path=?,verified_at=? WHERE attempt_id=?""",
                (status, reason_code, screenshot_path, _stamp(verified_at) if verified_at else None, attempt_id))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def reserve_post(self, *, video_id: str, comment_id: str, run_id: str, input_source: str, body_hash: str, author_channel_id: str, target_channel_id: str, when: datetime, daily_limit: int = 10, cooldown_hours: float = 24) -> str:
        """Atomically reserve and commit. Caller may click only after this returns."""
        utc = _aware(when)
        if daily_limit <= 0 or cooldown_hours <= 0:
            raise ValueError("limits must be positive")
        if not all((video_id, comment_id, run_id, input_source, body_hash, author_channel_id, target_channel_id)):
            raise ValueError("reservation fields cannot be empty")
        kst = utc.astimezone(KST)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.attempt(video_id) or self.dashboard_attempt(video_id):
                raise ReservationBlocked("ALREADY_ATTEMPTED")
            comment = self.comment(video_id)
            if comment is None or comment["comment_id"] != comment_id:
                raise ReservationBlocked("COMMENT_MISSING")
            if self.daily_attempts(utc) + self.db.execute("SELECT COUNT(*) FROM dashboard_post_reservations WHERE attempt_date_kst=? AND status!='PRECHECK_FAILED'", (kst.date().isoformat(),)).fetchone()[0] >= daily_limit:
                raise ReservationBlocked("DAILY_LIMIT")
            last = self.db.execute("SELECT MAX(attempted_at_kst) FROM post_results WHERE target_channel_id=?", (target_channel_id,)).fetchone()[0]
            if last and utc - datetime.fromisoformat(last).astimezone(timezone.utc) < timedelta(hours=cooldown_hours):
                raise ReservationBlocked("CHANNEL_COOLDOWN")
            attempt_id = uuid4().hex
            self.db.execute("INSERT INTO post_results(attempt_id,video_id,comment_id,run_id,input_source,attempted_at_kst,attempt_date_kst,status,body_hash,author_channel_id,target_channel_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (attempt_id, video_id, comment_id, run_id, input_source, kst.isoformat(), kst.date().isoformat(), "POST_PENDING", body_hash, author_channel_id, target_channel_id))
            self.db.execute("INSERT INTO channel_cooldowns VALUES(?,?) ON CONFLICT(target_channel_id) DO UPDATE SET last_attempted_at=excluded.last_attempted_at", (target_channel_id, kst.isoformat()))
            self.db.execute("COMMIT")
            return attempt_id
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def set_post_status(self, attempt_id: str, status: str, *, reason_code: str | None = None, screenshot_path: str | None = None, verified_at: datetime | None = None) -> None:
        if status not in STATUSES:
            raise ValueError("invalid post status")
        row = self.db.execute("SELECT status FROM post_results WHERE attempt_id=?", (attempt_id,)).fetchone()
        if row is None or status not in TRANSITIONS[row["status"]]:
            raise ValueError("invalid post transition")
        if status == "POSTED" and verified_at is None:
            raise ValueError("POSTED needs verification time")
        self.db.execute("UPDATE post_results SET status=?, reason_code=?, screenshot_path=?, verified_at=? WHERE attempt_id=?",
                        (status, reason_code, screenshot_path, _stamp(verified_at) if verified_at else None, attempt_id))
