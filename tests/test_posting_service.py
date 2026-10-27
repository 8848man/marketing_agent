from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import os
import sqlite3
import time
from unittest.mock import patch

import pytest

from marketing_agent.dashboard_contracts import VideoCard, VideoList
from marketing_agent.drafts import content_hash
from marketing_agent.posting_service import PostingService, recheck_test_video
from marketing_agent.storage import ReservationBlocked, Store


NOW = datetime(2026, 10, 15, 14, 59, tzinfo=timezone.utc)
CHANNEL = "UCxlc0Ky0aWoD8uI09ad44Tg"
BODY = "상대가 답장을 늦게 한 장면에서 마음이 불안해지는 게 공감돼요. 운명원 연애 사주로 관계 흐름을 살펴보면 어떨까 궁금하네요."
TEST_CHANNEL = "UCabcdefghijklmnopqrstuv"


def prepare_service(tmp_path, video_id="AbCdEfGhI12", *, poster=None, clock=lambda: NOW,
                    channel=CHANNEL, **service_kwargs):
    card = VideoCard(video_id, channel, "외롭여", "답장이 늦는 날", "2026-10-15", "")
    draft = dict(video_id=video_id, channel_id=channel, title=card.title,
                 worry_summary="답장을 기다리는 불안", comment=BODY,
                 cited_detail="답장을 늦게 한 장면", source_text="답장을 늦게 한 장면",
                 reviewer="human", reviewed_at="2026-10-15T10:00:00+09:00")
    draft["content_hash"] = draft["approval_hash"] = content_hash(draft)
    drafts = tmp_path / "drafts"
    drafts.mkdir(exist_ok=True)
    (drafts / f"{video_id}.json").write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    service = PostingService(tmp_path / "state.sqlite", drafts, poster=poster,
                             feed_loader=lambda: VideoList((card,)),
                             recheck=lambda vid, ch: card, clock=clock, **service_kwargs)
    service.list_videos()
    assert service.select_video(video_id).can_post
    return service, card, draft


def test_post_video_allows_configured_channel_outside_fixed_list(tmp_path):
    custom = "UCzzzzzzzzzzzzzzzzzzzzzz"
    opened = []
    service, card, _ = prepare_service(tmp_path, channel=custom, poster=lambda *args: opened.append(1),
                                       allowed_channels=lambda: {custom: "설정 채널"})
    result = service.post_video(card.video_id)
    assert result.reason_code != "CHANNEL_NOT_ALLOWED"
    assert opened


def test_pre_chrome_blocks_rss_and_changed_approval(tmp_path):
    opened = []
    service, card, draft = prepare_service(tmp_path, poster=lambda *args: opened.append(1))
    service.recheck = lambda *_: None
    assert service.post_video(card.video_id).reason_code == "RSS_MEMBERSHIP_UNVERIFIED"
    service.recheck = lambda *_: card
    draft["comment"] += " 수정"
    (service.drafts_dir / f"{card.video_id}.json").write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    assert service.post_video(card.video_id).state == "blocked"
    assert not opened
    with Store(service.db_path) as store:
        assert store.dashboard_attempt(card.video_id) is None


def test_preclick_failure_releases_and_after_click_is_held(tmp_path):
    def fail_before(*_):
        raise RuntimeError("login")
    service, card, _ = prepare_service(tmp_path, poster=fail_before)
    before = service.post_video(card.video_id)
    assert (before.state, before.message) == ("blocked", "PRECHECK_FAILED")
    with Store(service.db_path) as store:
        assert store.dashboard_attempt(card.video_id) is None
    def fail_after(card, body, mark):
        mark()
        raise RuntimeError("timeout")
    service.poster = fail_after
    after = service.post_video(card.video_id)
    assert (after.state, after.message) == ("uncertain", "OUTCOME_UNKNOWN")
    restarted, _, _ = prepare_service(tmp_path, poster=fail_after)
    assert restarted.post_video(card.video_id).reason_code == "ALREADY_ATTEMPTED"
    with Store(service.db_path) as store:
        assert store.dashboard_attempt(card.video_id)["status"] == "OUTCOME_UNKNOWN"


def test_concurrent_reservation_and_day_limit_survive_restart(tmp_path):
    path = tmp_path / "state.sqlite"
    def reserve(n):
        with Store(path) as store:
            try:
                return store.reserve_reviewed_post(video_id=f"video{n:06d}", channel_id=CHANNEL,
                    title="title", body_hash="body", approval_hash="approved", profile=f"profile{n%3}", when=NOW)
            except ReservationBlocked as exc:
                return exc.reason
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(reserve, range(20)))
    assert sum(result == "DAILY_LIMIT" for result in results) == 10
    accepted = [index for index, result in enumerate(results) if result != "DAILY_LIMIT"]
    assert len(accepted) == 10
    with Store(path) as store:
        assert store._dashboard_count("2026-10-15") == 10
        assert all(store.dashboard_attempt(f"video{index:06d}") is not None
                   for index in accepted)
    assert reserve(accepted[0]) == "ALREADY_ATTEMPTED"


def test_midnight_click_rechecks_new_day(tmp_path):
    path = tmp_path / "state.sqlite"
    with Store(path) as store:
        first = store.reserve_reviewed_post(video_id="first000001", channel_id=CHANNEL,
            title="title", body_hash="hash", approval_hash="approval", profile="p", when=NOW, daily_limit=1)
        second = store.reserve_reviewed_post(video_id="next0000001", channel_id=CHANNEL,
            title="title", body_hash="hash", approval_hash="approval", profile="p", when=NOW + timedelta(minutes=1), daily_limit=1)
        try:
            store.begin_dashboard_submit(first, NOW + timedelta(minutes=1), daily_limit=1)
            assert False
        except ReservationBlocked as exc:
            assert exc.reason == "DAILY_LIMIT"
        store.finish_dashboard_post(first, "PRECHECK_FAILED")
        assert store.dashboard_attempt("first000001") is None
        assert store.dashboard_attempt("next0000001")["attempt_id"] == second


def test_legacy_history_is_preserved_and_blocks_duplicate(tmp_path):
    path = tmp_path / "state.sqlite"
    with Store(path) as store:
        store.save_video("legacy00001", CHANNEL, NOW)
        comment = store.save_comment("legacy00001", BODY, NOW)
        legacy = store.reserve_post(video_id="legacy00001", comment_id=comment,
            run_id="old", input_source="legacy", body_hash="hash",
            author_channel_id="author", target_channel_id=CHANNEL, when=NOW)
        try:
            store.reserve_reviewed_post(video_id="legacy00001", channel_id=CHANNEL,
                title="title", body_hash="hash", approval_hash="approval",
                profile="유튜브1", when=NOW)
            assert False
        except ReservationBlocked as exc:
            assert exc.reason == "ALREADY_ATTEMPTED"
    with Store(path) as store:
        assert store.attempt("legacy00001")["attempt_id"] == legacy
        assert store._dashboard_count("2026-10-15") == 1


def test_owned_test_video_requires_exact_registration_and_prior_proof(tmp_path):
    opened = []
    video_id = "MyTestVid01"
    card = VideoCard(video_id, TEST_CHANNEL, "본인 테스트 영상", "내 테스트 영상", "", "")
    draft = dict(video_id=video_id, channel_id=TEST_CHANNEL, title=card.title,
                 worry_summary="답장을 기다리는 불안", comment=BODY,
                 cited_detail="답장을 늦게 한 장면", source_text="답장을 늦게 한 장면",
                 reviewer="human", reviewed_at="2026-10-15T10:00:00+09:00")
    draft["content_hash"] = draft["approval_hash"] = content_hash(draft)
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / f"{video_id}.json").write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    options = dict(poster=lambda *args: opened.append(1), feed_loader=lambda: VideoList(),
                   recheck=lambda *_: (_ for _ in ()).throw(AssertionError("test videos do not use RSS")),
                   test_recheck=lambda *_: card,
                   clock=lambda: NOW)
    unregistered = PostingService(tmp_path / "state.sqlite", drafts, **options)
    unregistered.list_videos()
    assert unregistered.select_video(video_id).reason_code == "VIDEO_NOT_FOUND"
    assert unregistered.post_video(video_id).reason_code == "VIDEO_NOT_SELECTED"

    registration = [dict(video_id=video_id, channel_id=TEST_CHANNEL, title=card.title)]
    service = PostingService(tmp_path / "state.sqlite", drafts, test_videos=registration, **options)
    assert service.list_videos().videos == (card,)
    assert service.select_video(video_id).reason_code == "OWNERSHIP_UNVERIFIED"
    (tmp_path / "local-review-record").write_text("Manual owner review", encoding="utf-8")
    with Store(service.db_path) as store:
        store.save_video(video_id, TEST_CHANNEL, NOW, title=card.title)
        store.register_owned_video(video_id, "UCxxxxxxxxxxxxxxxxxxxxxx", NOW, "local-review-record")
    assert service.select_video(video_id).reason_code == "OWNERSHIP_UNVERIFIED"
    with Store(service.db_path) as store:
        store.register_owned_video(video_id, TEST_CHANNEL, NOW, "local-review-record")
    assert service.select_video(video_id).can_post
    (tmp_path / "local-review-record").unlink()
    assert service.post_video(video_id).reason_code == "OWNERSHIP_UNVERIFIED"
    (tmp_path / "local-review-record").write_text("Manual owner review", encoding="utf-8")
    with Store(service.db_path) as store:
        store.register_owned_video(video_id, "UCxxxxxxxxxxxxxxxxxxxxxx", NOW, "local-review-record")
    assert service.post_video(video_id).reason_code == "OWNERSHIP_UNVERIFIED"
    assert opened == []
    with Store(service.db_path) as store:
        assert store.dashboard_attempt(video_id) is None
        store.register_owned_video(video_id, TEST_CHANNEL, NOW, "local-review-record")

    def confirmed(_card, _body, mark):
        opened.append(1)
        mark()
        return True
    service.poster = confirmed
    assert service.post_video(video_id).state == "posted"
    assert opened == [1]
    assert service.post_video(video_id).reason_code == "ALREADY_ATTEMPTED"


def test_test_video_feed_failure_blocks_before_reservation_or_chrome(tmp_path):
    video_id = "MyTestVid01"
    card = VideoCard(video_id, TEST_CHANNEL, "본인 테스트 영상", "내 테스트 영상", "", "")
    draft = dict(video_id=video_id, channel_id=TEST_CHANNEL, title=card.title,
                 worry_summary="답장을 기다리는 불안", comment=BODY,
                 cited_detail="답장을 늦게 한 장면", source_text="답장을 늦게 한 장면",
                 reviewer="human", reviewed_at="2026-10-15T10:00:00+09:00")
    draft["content_hash"] = draft["approval_hash"] = content_hash(draft)
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / f"{video_id}.json").write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "proof").write_text("Manual owner review", encoding="utf-8")
    with Store(tmp_path / "state.sqlite") as store:
        store.save_video(video_id, TEST_CHANNEL, NOW, title=card.title)
        store.register_owned_video(video_id, TEST_CHANNEL, NOW, "proof")
    opened = []
    service = PostingService(tmp_path / "state.sqlite", drafts,
                             poster=lambda *args: opened.append(1),
                             feed_loader=lambda: VideoList(),
                             test_videos=[dict(video_id=video_id, channel_id=TEST_CHANNEL, title=card.title)],
                             test_recheck=lambda *_: card)
    service.list_videos()
    assert service.select_video(video_id).can_post
    for lookup, reason in (
            (lambda *_: (_ for _ in ()).throw(OSError("offline")), "TEST_FEED_UNAVAILABLE"),
            (lambda *_: None, "TEST_VIDEO_NOT_IN_FEED"),
            (lambda *_: VideoCard(video_id, TEST_CHANNEL, card.channel, "changed", "", ""),
             "TEST_VIDEO_CHANGED")):
        service.test_recheck = lambda *_: card
        assert service.select_video(video_id).can_post
        service.test_recheck = lookup
        assert service.post_video(video_id).reason_code == reason
        assert service.select_video(video_id).reason_code == reason
    assert opened == []
    with Store(service.db_path) as store:
        assert store.dashboard_attempt(video_id) is None


def test_test_video_feed_recheck_requires_matching_channel_and_entry():
    video_id = "MyTestVid01"
    def feed(owner, entry_owner=TEST_CHANNEL, entry_id=video_id):
        return (f'<feed xmlns="http://www.w3.org/2005/Atom" '
                f'xmlns:yt="http://www.youtube.com/xml/schemas/2015">'
                f'<yt:channelId>{owner}</yt:channelId><entry>'
                f'<yt:videoId>{entry_id}</yt:videoId>'
                f'<yt:channelId>{entry_owner}</yt:channelId>'
                f'<title>내 테스트 영상</title></entry></feed>').encode()
    class Opener:
        def __init__(self, data):
            self.data = data
        def open(self, request, timeout):
            assert request.full_url == f"https://www.youtube.com/feeds/videos.xml?channel_id={TEST_CHANNEL}"
            assert timeout == 10
            return BytesIO(self.data)
    with patch("marketing_agent.posting_service.build_opener", return_value=Opener(feed(TEST_CHANNEL))):
        assert recheck_test_video(video_id, TEST_CHANNEL).title == "내 테스트 영상"
    with patch("marketing_agent.posting_service.build_opener", return_value=Opener(feed(TEST_CHANNEL, entry_id="OtherVideo1"))):
        assert recheck_test_video(video_id, TEST_CHANNEL) is None
    with patch("marketing_agent.posting_service.build_opener", return_value=Opener(feed(CHANNEL))):
        try:
            recheck_test_video(video_id, TEST_CHANNEL)
            assert False
        except ValueError as exc:
            assert str(exc) == "TEST_FEED_CHANNEL_MISMATCH"


def test_test_registration_rejects_invalid_or_fixed_channel(tmp_path):
    for registration in ([dict(video_id="bad", channel_id=TEST_CHANNEL, title="x")],
                         [dict(video_id="MyTestVid01", channel_id=CHANNEL, title="x")],
                         [dict(video_id="MyTestVid01", channel_id=TEST_CHANNEL, title="")]):
        try:
            PostingService(tmp_path / "state.sqlite", tmp_path, test_videos=registration)
            assert False
        except ValueError:
            pass


def test_post_video_blocks_when_channel_config_fails(tmp_path):
    opened = []

    def broken():
        raise RuntimeError("config unreadable")

    service, card, _ = prepare_service(tmp_path, poster=lambda *args: opened.append(1),
                                       allowed_channels=broken)
    result = service.post_video(card.video_id)
    assert (result.state, result.reason_code) == ("blocked", "CHANNEL_CONFIG_UNAVAILABLE")
    assert not opened
    with Store(service.db_path) as store:
        assert store.dashboard_attempt(card.video_id) is None


def test_post_video_blocks_when_channel_config_empty(tmp_path):
    opened = []
    service, card, _ = prepare_service(tmp_path, poster=lambda *args: opened.append(1),
                                       allowed_channels=lambda: {})
    result = service.post_video(card.video_id)
    assert result.reason_code == "CHANNEL_NOT_ALLOWED"
    assert not opened


def test_post_video_channel_cooldown_blocks_before_poster(tmp_path):
    calls = []
    def poster(card, body, mark):
        calls.append(card.video_id)
        mark()
        return True
    first, card1, _ = prepare_service(tmp_path, "AbCdEfGhI12", poster=poster, channel_cooldown_minutes=60)
    assert first.post_video(card1.video_id).state == "posted"
    second, card2, _ = prepare_service(tmp_path, "ZyXwVuTsR98", poster=poster, channel_cooldown_minutes=60)
    result = second.post_video(card2.video_id)
    assert (result.state, result.reason_code) == ("blocked", "CHANNEL_COOLDOWN")
    assert calls == ["AbCdEfGhI12"]


def test_cooldown_and_daily_limit_have_korean_message(tmp_path):
    def poster(card, body, mark):
        mark()
        return True
    first, card1, _ = prepare_service(tmp_path, "AbCdEfGhI12", poster=poster, channel_cooldown_minutes=60)
    assert first.post_video(card1.video_id).state == "posted"
    second, card2, _ = prepare_service(tmp_path, "ZyXwVuTsR98", poster=poster, channel_cooldown_minutes=60)
    cooldown = second.post_video(card2.video_id)
    assert cooldown.reason_code == "CHANNEL_COOLDOWN"
    assert "60분 간격" in cooldown.message and "다른 채널" in cooldown.message
    (tmp_path / "limit").mkdir()
    one, card3, _ = prepare_service(tmp_path / "limit", "QwErTyUiO12", poster=poster, daily_limit=1)
    assert one.post_video(card3.video_id).state == "posted"
    limited, card4, _ = prepare_service(tmp_path / "limit", "PoIuYtReW34", poster=poster, daily_limit=1)
    daily = limited.post_video(card4.video_id)
    assert daily.reason_code == "DAILY_LIMIT"
    assert "오늘 게시 한도(" in daily.message and "내일 다시" in daily.message


def test_daily_limit_day_is_kst_regardless_of_machine_tz(tmp_path, monkeypatch):
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset unavailable")
    original = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    try:
        late = datetime(2026, 10, 15, 15, 30, tzinfo=timezone.utc)  # KST 2026-10-16 00:30
        service, card, _ = prepare_service(tmp_path, clock=lambda: late, poster=lambda *args: None)
        assert late.astimezone(service.local_tz).utcoffset() == timedelta(hours=9)
        with Store(service.db_path) as store:
            attempt_id = store.reserve_reviewed_post(
                video_id=card.video_id, channel_id=card.channel_id, title=card.title,
                body_hash="b", approval_hash="a", profile="p", when=late, local_tz=service.local_tz)
        db = sqlite3.connect(service.db_path)
        try:
            row = db.execute("SELECT attempt_date_kst FROM dashboard_post_reservations WHERE attempt_id=?",
                             (attempt_id,)).fetchone()
        finally:
            db.close()
        assert row[0] == "2026-10-16"
    finally:
        monkeypatch.undo()
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        time.tzset()
