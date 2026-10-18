"""R-SUBMIT-2026-10-18: history panel, dev guard, signed-in assignment, drafts CLI."""
from datetime import datetime, timezone
import json
import re
from unittest.mock import MagicMock, patch

import yaml

from marketing_agent import __main__
from marketing_agent.dashboard import ConfiguredPostingService, DashboardSettings
from marketing_agent.dashboard_contracts import VideoCard, VideoList
from marketing_agent.dashboard_ui import _page
from marketing_agent.posting_service import PostingService, _Selection
from marketing_agent.storage import Store
from test_dashboard import running_server, request

CHANNEL = "UCxlc0Ky0aWoD8uI09ad44Tg"
NOW = datetime(2026, 10, 18, 1, 0, tzinfo=timezone.utc)


def _settings(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    return DashboardSettings(tmp_path / "config.yaml")


def _reserve(store, video_id, *, body="", approval="a" * 64, when=NOW):
    return store.reserve_reviewed_post(
        video_id=video_id, channel_id=CHANNEL, title="제목 " + video_id, body_hash="h" * 64,
        approval_hash=approval, profile="유튜브1", when=when, body=body)


def test_history_lists_newest_first_with_body_status_and_daily_count(tmp_path):
    db = tmp_path / "posts.db"
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "OldVideo001.json").write_text(json.dumps(
        {"video_id": "OldVideo001", "comment": "예전 승인 댓글", "approval_hash": "b" * 64},
        ensure_ascii=False), encoding="utf-8")
    with Store(db) as store:
        old = _reserve(store, "OldVideo001", approval="b" * 64,
                       when=datetime(2026, 10, 17, 0, 0, tzinfo=timezone.utc))
        store.finish_dashboard_post(old, "PRECHECK_FAILED", reason_code="LOGIN_REQUIRED")
        # simulate a pre-IMP-07 row: no stored body
        store.db.execute("DELETE FROM dashboard_post_bodies WHERE attempt_id=?", (old,))
        new = _reserve(store, "NewVideo001", body="새 댓글 본문")
        store.begin_dashboard_submit(new, NOW)
        store.finish_dashboard_post(new, "POSTED", verified_at=NOW)
    service = PostingService(db, drafts, clock=lambda: NOW)
    service.local_tz = timezone.utc
    result = service.history()
    assert [item["video_id"] for item in result["items"]] == ["NewVideo001", "OldVideo001"]
    assert result["items"][0]["comment"] == "새 댓글 본문"
    assert result["items"][0]["status"] == "POSTED"
    assert result["items"][1]["comment"] == "예전 승인 댓글"
    assert result["items"][1]["reason_code"] == "LOGIN_REQUIRED"
    assert result["posted_today"] == 1 and result["daily_limit"] == 10
    assert not any("key" in name or "email" in name for name in result["items"][0])


def test_history_http_requires_token_and_page_has_panel(tmp_path):
    service = PostingService(tmp_path / "posts.db", tmp_path / "drafts", clock=lambda: NOW)
    with running_server(service) as port:
        page = request(port, "GET", "/")[1]
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        assert request(port, "GET", "/api/history")[0] == 403
        status, body = request(port, "GET", "/api/history", token=token)
    assert status == 200 and json.loads(body)["items"] == []
    html = _page("t").decode("utf-8")
    assert "④ 실행 기록" in html and "/api/history" in html


def test_dev_guard_blocks_our_channel_before_reservation_or_chrome(tmp_path):
    poster = MagicMock()
    service = PostingService(tmp_path / "posts.db", tmp_path / "drafts", poster=poster)
    card = VideoCard("NewVideo001", CHANNEL, "외롭여", "제목", "", "")
    service._selected["NewVideo001"] = _Selection(card, "a" * 64, "본문")
    (tmp_path / "DEV_BLOCK_OUR_CHANNELS").write_text("", encoding="utf-8")
    result = service.post_video("NewVideo001")
    assert result.reason_code == "DEV_OUR_CHANNEL_BLOCKED"
    poster.assert_not_called()
    assert not (tmp_path / "posts.db").exists()


def test_assignment_uses_signed_in_profiles_else_first_profile(tmp_path):
    settings = _settings(tmp_path)
    for label in ("유튜브1", "유튜브2", "유튜브3"):
        (settings.app_profile_root(label) / "Default").mkdir(parents=True)
        settings.connect_profile(label)
    cards = tuple(VideoCard(f"Video00000{i}", CHANNEL, "외롭여", f"t{i}", f"2026-10-1{i}", "")
                  for i in range(1, 5))
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts", settings=settings,
                                       poster=MagicMock(), feed_loader=lambda: VideoList(cards[:2]))
    assert service._assignment_candidates() == ["유튜브1"]
    service.list_videos()
    service._account_states.update({"유튜브2": "SIGNED_IN", "유튜브3": "SIGNED_IN"})
    assert service._assignment_candidates() == ["유튜브2", "유튜브3"]
    service.feed_loader = lambda: VideoList(cards)
    service.list_videos()
    states = service.video_states()
    assert {states[c.video_id]["profile"] for c in cards[:2]} == {"유튜브1"}
    assert {states[c.video_id]["profile"] for c in cards[2:]} == {"유튜브2", "유튜브3"}


def test_drafts_cli_generates_unapproved_only_and_never_posts(tmp_path, capsys):
    cards = [VideoCard(f"Video00000{i}", CHANNEL, "외롭여", f"t{i}", f"2026-10-1{i}", "")
             for i in range(1, 5)]
    service = MagicMock()
    service.list_videos.return_value = VideoList(tuple(cards))
    service.generate_draft.side_effect = lambda vid: {"video_id": vid, "comment": "x"}
    with patch("marketing_agent.__main__._draft_service", return_value=service), \
         patch("marketing_agent.__main__._approved", side_effect=lambda card, _d: card.video_id == "Video000004"):
        assert __main__.main(["drafts", "--latest", "3"]) == 0
    generated = [call.args[0] for call in service.generate_draft.call_args_list]
    assert generated == ["Video000003", "Video000002"]  # newest 3, already-approved skipped
    service.post_video.assert_not_called()
    out = capsys.readouterr().out
    assert "Video000004 SKIP_APPROVED" in out and "GENERATED" in out
    service.generate_draft.reset_mock()
    with patch("marketing_agent.__main__._draft_service", return_value=service), \
         patch("marketing_agent.__main__._approved", return_value=True):
        assert __main__.main(["drafts", "--latest", "1", "--include-approved"]) == 0
    assert [c.args[0] for c in service.generate_draft.call_args_list] == ["Video000004"]


def test_previous_draft_is_kept_before_regeneration(tmp_path):
    drafts, work = tmp_path / "drafts", tmp_path / "work"
    drafts.mkdir()
    (drafts / "Video000001.json").write_text('{"comment": "v5"}', encoding="utf-8")
    __main__._keep_previous_draft(drafts, work, "Video000001")
    kept = list((work / "draft_history").glob("Video000001.*.json"))
    assert len(kept) == 1 and kept[0].read_text(encoding="utf-8") == '{"comment": "v5"}'
