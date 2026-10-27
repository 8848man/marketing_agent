"""Explicit-click posting decision for fixed-channel RSS videos."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re
from typing import Callable
from urllib.request import Request, build_opener
import xml.etree.ElementTree as ET

from .dashboard_contracts import DraftPreview, PostStatus, VideoCard, VideoList
from .drafts import _load_record, content_hash, preview
from .guard import check_rss_membership, normalize_video_id
from .rss_feed import CHANNELS, VIDEO_ID, _NoRedirect, list_videos, recheck_video
from .storage import ReservationBlocked, Store


@dataclass(frozen=True)
class _Selection:
    card: VideoCard
    approval_hash: str
    body: str


CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
ATOM = "{http://www.w3.org/2005/Atom}"
YT = "{http://www.youtube.com/xml/schemas/2015}"
MAX_FEED_BYTES = 2_000_000


def recheck_test_video(video_id: str, channel_id: str) -> VideoCard | None:
    """Verify an explicitly registered test video through its channel RSS.

    A missing feed entry is inconclusive, never permission to open the video.
    """
    if not VIDEO_ID.fullmatch(video_id) or not CHANNEL_ID.fullmatch(channel_id) or channel_id in CHANNELS:
        raise ValueError("TEST_VIDEO_INVALID")
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    request = Request(url, headers={"User-Agent": "marketing-agent-rss/1.0", "Accept": "application/atom+xml"})
    with build_opener(_NoRedirect()).open(request, timeout=10) as response:
        data = response.read(MAX_FEED_BYTES + 1)
    if len(data) > MAX_FEED_BYTES:
        raise ValueError("TEST_FEED_TOO_LARGE")
    root = ET.fromstring(data)
    if root.tag != f"{ATOM}feed" or root.findtext(f"{YT}channelId") != channel_id:
        raise ValueError("TEST_FEED_CHANNEL_MISMATCH")
    for entry in root.findall(f"{ATOM}entry"):
        if entry.findtext(f"{YT}videoId") != video_id:
            continue
        if entry.findtext(f"{YT}channelId") != channel_id:
            raise ValueError("TEST_VIDEO_CHANNEL_MISMATCH")
        title = entry.findtext(f"{ATOM}title", "").strip()
        if not title:
            raise ValueError("TEST_VIDEO_TITLE_MISSING")
        return VideoCard(video_id, channel_id, "본인 테스트 영상", title, "", "")
    return None


def _test_cards(entries: object) -> dict[str, VideoCard]:
    """Parse explicit registrations without visiting a video page."""
    if not isinstance(entries, (list, tuple)):
        raise ValueError("test_videos must be a list")
    cards = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("invalid test video registration")
        video_id, channel_id, title = (entry.get(key) for key in ("video_id", "channel_id", "title"))
        if (not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id)
                or not isinstance(channel_id, str) or not CHANNEL_ID.fullmatch(channel_id)
                or channel_id in CHANNELS or not isinstance(title, str) or not title.strip()
                or video_id in cards):
            raise ValueError("invalid test video registration")
        cards[video_id] = VideoCard(video_id, channel_id, "본인 테스트 영상", title, "", "")
    return cards


class PostingService:
    """Dashboard adapter. ``poster`` receives card, body, and a click marker.

    It must call the marker immediately before the actual submit click. A
    failure after that marker remains uncertain even if Chrome raises.
    """

    def __init__(self, db_path: str | Path, drafts_dir: str | Path, *,
                 poster: Callable | None = None, profile: str = "유튜브1",
                 daily_limit: int = 10, feed_loader=list_videos,
                 recheck=recheck_video, clock=None, test_videos=(),
                 test_recheck=recheck_test_video, allowed_channels=None):
        self.db_path = Path(db_path)
        self.drafts_dir = Path(drafts_dir)
        self.poster = poster
        self.profile = profile
        self.daily_limit = daily_limit
        self.feed_loader = feed_loader
        self.recheck = recheck
        self.test_recheck = test_recheck
        self.allowed_channels = allowed_channels
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.test_videos = _test_cards(test_videos)
        self.local_tz = datetime.now().astimezone().tzinfo
        self._videos: dict[str, VideoCard] = {}
        self._selected: dict[str, _Selection] = {}

    def list_videos(self) -> VideoList:
        result = self.feed_loader()
        self._videos = {card.video_id: card for card in result.videos}
        self._videos.update({key: card for key, card in self.test_videos.items()
                             if key not in self._videos})
        self._selected.clear()
        return VideoList(tuple(self._videos.values()), result.errors)

    def _test_ownership(self, card: VideoCard) -> bool:
        if self.test_videos.get(card.video_id) != card:
            return False
        with Store(self.db_path) as store:
            proof = store.ownership(card.video_id)
            video = store.video(card.video_id)
        if not (proof and video and proof["video_id"] == card.video_id
                and proof["owner_channel_id"] == card.channel_id
                and video["channel_id"] == card.channel_id
                and video["title"] == card.title and proof["verified_at"]):
            return False
        evidence_name = proof["evidence_path"]
        if not evidence_name:
            return False
        evidence_root = self.db_path.parent.resolve()
        evidence = (evidence_root / evidence_name).resolve()
        return evidence.is_relative_to(evidence_root) and evidence.is_file()

    def select_video(self, video_id: str) -> DraftPreview:
        self._selected.pop(video_id, None)
        card = self._videos.get(video_id)
        if card is None:
            return DraftPreview(video_id, reason_code="VIDEO_NOT_FOUND")
        if video_id in self.test_videos and not self._test_ownership(card):
            return DraftPreview(video_id, reason_code="OWNERSHIP_UNVERIFIED")
        if video_id in self.test_videos:
            reason = self._test_feed_reason(card)
            if reason:
                return DraftPreview(video_id, reason_code=reason)
        result = preview(card, self.drafts_dir)
        if result.can_post:
            try:
                record = _load_record(self.drafts_dir, video_id)
                if record is None or record.get("approval_hash") != content_hash(record):
                    raise ValueError
                self._selected[video_id] = _Selection(card, record["approval_hash"], record["comment"])
            except (OSError, ValueError, TypeError, KeyError):
                return DraftPreview(video_id, reason_code="DRAFT_UNREADABLE")
        return result

    def _test_feed_reason(self, card: VideoCard) -> str:
        try:
            fresh = self.test_recheck(card.video_id, card.channel_id)
        except Exception:
            return "TEST_FEED_UNAVAILABLE"
        if fresh is None:
            return "TEST_VIDEO_NOT_IN_FEED"
        if (fresh.video_id != card.video_id or fresh.channel_id != card.channel_id
                or fresh.title != card.title):
            return "TEST_VIDEO_CHANGED"
        return ""

    def dev_guard_enabled(self) -> bool:
        """Developer-only switch (IMP-10): a marker file in the ignored work folder."""
        return (Path(self.db_path).parent / "DEV_BLOCK_OUR_CHANNELS").is_file()

    def history(self, limit: int = 50) -> dict[str, object]:
        """Chronological posting record for the dashboard (R-LOG-01)."""
        now = self.clock()
        day = now.astimezone(self.local_tz).date().isoformat()
        with Store(self.db_path) as store:
            rows = store.dashboard_history(limit)
            posted_today = store.dashboard_posts_on(day)
        items = []
        for row in rows:
            body = row.get("body") or ""
            if not body:
                try:
                    record = _load_record(self.drafts_dir, row["video_id"]) or {}
                except (OSError, ValueError, TypeError):
                    record = {}
                if record.get("approval_hash") == row["approval_hash"]:
                    body = str(record.get("comment", ""))
            items.append({
                "reserved_at": row["reserved_at"], "video_id": row["video_id"],
                "title": row["title"], "channel_id": row["channel_id"],
                "profile": row["profile"], "comment": body, "status": row["status"],
                "reason_code": row["reason_code"] or "", "verified_at": row["verified_at"] or "",
                "screenshot_path": row["screenshot_path"] or "",
            })
        return {"items": items, "posted_today": posted_today, "daily_limit": self.daily_limit}

    def post_video(self, video: str) -> PostStatus:
        try:
            video_id = normalize_video_id(video)
        except ValueError:
            return PostStatus("blocked", "INVALID_VIDEO_ID")
        # A URL alone never creates a selection or authorizes a new page.
        selection = self._selected.get(video_id)
        if selection is None or video != video_id:
            return PostStatus("blocked", "VIDEO_NOT_SELECTED")
        card = selection.card
        if video_id not in self.test_videos and self.dev_guard_enabled():
            return PostStatus("blocked", "DEV_OUR_CHANNEL_BLOCKED",
                              "개발용 차단 파일이 있어 우리 채널 영상에는 게시하지 않습니다. "
                              "본인 테스트 영상만 게시할 수 있습니다.")
        if video_id in self.test_videos:
            if not self._test_ownership(card):
                return PostStatus("blocked", "OWNERSHIP_UNVERIFIED")
            reason = self._test_feed_reason(card)
            if reason:
                return PostStatus("blocked", reason)
            fresh = card
        else:
            try:
                fresh = self.recheck(video_id, card.channel_id)
            except Exception:
                fresh = None
            decision = check_rss_membership(
                video_id, card.channel_id, recheck=lambda *_: fresh,
                allowed_channels=self.allowed_channels() if self.allowed_channels else None)
            if not decision.allowed:
                return PostStatus("blocked", decision.reason)
            if fresh is None or fresh.video_id != card.video_id or fresh.channel_id != card.channel_id or fresh.title != card.title:
                return PostStatus("blocked", "RSS_VIDEO_CHANGED")
        checked = preview(fresh, self.drafts_dir)
        if not checked.can_post:
            return PostStatus("blocked", checked.reason_code)
        try:
            record = _load_record(self.drafts_dir, video_id)
        except (OSError, ValueError, TypeError):
            return PostStatus("blocked", "DRAFT_UNREADABLE")
        if (record is None or record.get("approval_hash") != selection.approval_hash
                or record.get("comment") != selection.body):
            return PostStatus("blocked", "APPROVAL_CHANGED")
        if self.poster is None:
            return PostStatus("blocked", "POSTER_UNAVAILABLE")

        with Store(self.db_path) as store:
            try:
                attempt_id = store.reserve_reviewed_post(
                    video_id=video_id, channel_id=card.channel_id, title=card.title,
                    body_hash=sha256(selection.body.encode("utf-8")).hexdigest(),
                    approval_hash=selection.approval_hash,
                    profile=self.profile, when=self.clock(), daily_limit=self.daily_limit,
                    local_tz=self.local_tz, body=selection.body)
            except ReservationBlocked as exc:
                return PostStatus("blocked", exc.reason)
            clicked = False

            def before_click() -> None:
                nonlocal clicked
                # A durable SUBMITTING state is written before invoking Chrome's
                # click. A crash after this point must never free the video.
                store.begin_dashboard_submit(attempt_id, self.clock(), daily_limit=self.daily_limit,
                                             local_tz=self.local_tz)
                clicked = True

            try:
                confirmed = self.poster(fresh, selection.body, before_click)
                if not clicked:
                    raise RuntimeError("SUBMIT_NOT_STARTED")
                if confirmed is not True:
                    raise RuntimeError("COMMENT_NOT_CONFIRMED")
                store.finish_dashboard_post(attempt_id, "POSTED", verified_at=self.clock())
                return PostStatus("posted", "CONFIRMED")
            except Exception as exc:
                reason = exc.reason if isinstance(exc, ReservationBlocked) else getattr(exc, "code", type(exc).__name__)
                status = "OUTCOME_UNKNOWN" if clicked else "PRECHECK_FAILED"
                screenshot = getattr(self.poster, "last_screenshot_path", "")
                store.finish_dashboard_post(attempt_id, status, reason_code=reason,
                                            screenshot_path=screenshot or None)
                return PostStatus("uncertain" if clicked else "blocked", reason,
                                  message=status, screenshot_url=screenshot)
