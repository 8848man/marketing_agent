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


# --- IMP-14 RSS retry/cache, IMP-15 second-pass filter -------------------------
from urllib.error import HTTPError
import pytest
from marketing_agent import rss_feed
from marketing_agent.captions import EvidenceResult
from marketing_agent.draft_review import review_problems
from marketing_agent.dashboard_contracts import VideoList as _VL

FEED = ("<feed xmlns='http://www.w3.org/2005/Atom' xmlns:yt='http://www.youtube.com/xml/schemas/2015'>"
        "<yt:channelId>xlc0Ky0aWoD8uI09ad44Tg</yt:channelId><title>외롭여</title>"
        "<entry><yt:videoId>Video000001</yt:videoId><yt:channelId>UCxlc0Ky0aWoD8uI09ad44Tg</yt:channelId>"
        "<title>제목</title><published>2026-10-17T00:00:00+00:00</published></entry></feed>").encode()


class _Opener:
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    def open(self, request, timeout):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        body = MagicMock()
        body.__enter__.return_value.read.return_value = outcome
        return body


def _http(code):
    return HTTPError("https://www.youtube.com/feeds/videos.xml", code, "x", {}, None)


def test_rss_retries_transient_errors_but_not_forbidden():
    opener = _Opener([_http(404), _http(500), FEED])
    assert rss_feed.fetch_channel(CHANNEL, opener=opener, sleep=lambda _s: None) == FEED
    assert opener.calls == 3
    forbidden = _Opener([_http(403)])
    with pytest.raises(rss_feed.FeedError, match="RSS_HTTP_403"):
        rss_feed.fetch_channel(CHANNEL, opener=forbidden, sleep=lambda _s: None)
    assert forbidden.calls == 1


def test_list_uses_recent_cache_only_for_display(tmp_path):
    channels = {CHANNEL: "외롭여"}
    rss_feed.list_videos(fetch=lambda _c: FEED, channels=channels, cache_dir=tmp_path)
    def broken(_c):
        raise rss_feed.FeedError("RSS_HTTP_404")
    result = rss_feed.list_videos(fetch=broken, channels=channels, cache_dir=tmp_path)
    assert [v.video_id for v in result.videos] == ["Video000001"]
    assert "RSS_HTTP_404" in result.errors["외롭여"] and "목록 표시" in result.errors["외롭여"]
    assert rss_feed.recheck_video("Video000001", CHANNEL, fetch=broken, channels=channels) is None


def test_review_flags_length_long_quote_praise_and_repeated_closing():
    base = {"worry_summary": "고민", "cited_detail": "짧은 장면", "source_text": "짧은 장면 설명",
            "brand_name": "운명원", "min_chars": 40, "max_chars": 120}
    good = dict(base, comment="짧은 장면 보고 웃었어요. 저도 비슷한 일이 있었거든요. 친구가 운명원 궁합이 잘 맞는다고 하던데 한번 보고 싶네요.")
    assert review_problems(good, ["전혀 다른 문장입니다. 운명원에서 재회운 보고 싶어요."]) == []
    long = dict(base, comment=good["comment"] + " 영상 잘 봤어요." * 6)
    codes = " ".join(review_problems(long, []))
    assert "LENGTH" in codes and "GENERIC" in codes
    repeated = review_problems(good, ["다른 영상. 친구가 운명원 궁합이 잘 맞는다고 하던데 한번 보고 싶네요."])
    assert any(p.startswith("REPEATED_CLOSING") for p in repeated)


def _service_with(tmp_path, responses):
    settings = _settings(tmp_path)
    settings.save_ai("openai", "gpt-5.4-mini", "PRIVATE_AI_TEST_KEY")
    card = VideoCard("Video000001", CHANNEL, "외롭여", "답장이 늦어질 때", "2026-10-15", "")
    evidence = type("E", (), {"collect": lambda self, _c: EvidenceResult("답장이 늦어질 때 자막", ("자막",))})()
    prompts = []
    class Gen:
        def generate(self, provider, model, key, prompt):
            prompts.append(prompt)
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts", settings=settings,
                                       evidence_provider=evidence, draft_generator=Gen(),
                                       feed_loader=lambda: _VL((card,)))
    service._videos[card.video_id] = card
    service._assigned_profile = lambda _v: "유튜브1"
    return service, prompts


GOOD = {"worry_summary": "답장을 기다리는 마음", "cited_detail": "답장이 늦어질 때",
        "comment": "답장이 늦어질 때 혼자 폰만 보던 제 모습이 떠올랐어요ㅠ 친구가 운명원에서 둘 궁합 한번 보라던데 저도 궁금해지네요."}


def test_second_pass_rewrites_until_review_passes_and_keeps_audit(tmp_path):
    too_long = dict(GOOD, comment=GOOD["comment"] + " 정말 공감되는 이야기였고 오래 기억에 남을 것 같아요." * 2)
    service, prompts = _service_with(tmp_path, [too_long, GOOD])
    result = service.generate_draft("Video000001")
    assert result["comment"] == GOOD["comment"] and len(prompts) == 2
    revision = json.loads(prompts[1].user)
    assert revision["previous_draft"]["comment"] == too_long["comment"]
    assert any(item.startswith("LENGTH") for item in revision["fix"])
    saved = json.loads((tmp_path / "drafts" / "Video000001.json").read_text(encoding="utf-8"))
    assert saved["prompt_version"].startswith("draft-v7") and len(saved["review_rounds"]) == 2
    assert saved["review_rounds"][-1]["problems"] == [] and "approval_hash" not in saved


def test_second_pass_failure_keeps_first_draft(tmp_path):
    too_long = dict(GOOD, comment=GOOD["comment"] + " 정말 공감되는 이야기였고 오래 기억에 남을 것 같아요." * 2)
    service, prompts = _service_with(tmp_path, [too_long, ValueError("AI_RESPONSE_INVALID")])
    assert service.generate_draft("Video000001")["comment"] == too_long["comment"]
    assert len(prompts) == 2


# --- IMP-16 filter switch and re-run from the dashboard ------------------------
def test_filter_switch_off_skips_second_pass(tmp_path):
    too_long = dict(GOOD, comment=GOOD["comment"] + " 정말 공감되는 이야기였고 오래 기억에 남을 것 같아요." * 2)
    service, prompts = _service_with(tmp_path, [too_long, GOOD])
    service.settings.save_comment_generation("운명원", "연애 사주 업체", "", 40, 120, False)
    result = service.generate_draft("Video000001")
    assert len(prompts) == 1 and result["review_filter"] is False
    assert any(p.startswith("LENGTH") for p in result["problems"])


def test_refine_reviews_without_ai_then_rewrites_on_request(tmp_path):
    too_long = dict(GOOD, comment=GOOD["comment"] + " 정말 공감되는 이야기였고 오래 기억에 남을 것 같아요." * 2)
    service, prompts = _service_with(tmp_path, [too_long, GOOD])
    service.settings.save_comment_generation("운명원", "연애 사주 업체", "", 40, 120, False)
    service.generate_draft("Video000001")
    prompts.clear()
    view = service.refine_draft("Video000001", rewrite=False)
    assert prompts == [] and view["changed"] is False and view["problems"]
    view = service.refine_draft("Video000001", rewrite=True)
    assert len(prompts) == 1 and view["changed"] is True and view["problems"] == []
    assert view["comment"] == GOOD["comment"] and view["approved"] is False
    assert json.loads(prompts[0].user)["previous_draft"]["comment"] == too_long["comment"]
    again = service.refine_draft("Video000001", rewrite=True)
    assert len(prompts) == 1 and again["changed"] is False  # nothing left to fix: no AI call


def test_refine_http_requires_token_and_exact_body(tmp_path):
    service, _ = _service_with(tmp_path, [GOOD])
    service.generate_draft("Video000001")
    with running_server(service) as port:
        page = request(port, "GET", "/")[1]
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        origin = f"http://127.0.0.1:{port}"
        body = json.dumps({"video_id": "Video000001", "rewrite": False})
        assert request(port, "POST", "/api/drafts/refine", origin=origin, body=body)[0] == 403
        bad = json.dumps({"video_id": "Video000001", "rewrite": "yes"})
        assert request(port, "POST", "/api/drafts/refine", origin=origin, token=token, body=bad)[0] == 400
        status, text = request(port, "POST", "/api/drafts/refine", origin=origin, token=token, body=body)
    assert status == 200 and json.loads(text)["comment"] == GOOD["comment"]


def test_same_quote_across_videos_is_flagged():
    base = {"worry_summary": "고민", "cited_detail": "싱글들을 위한 줌 미팅방", "source_text": "싱글들을 위한 줌 미팅방 안내",
            "brand_name": "운명원", "min_chars": 40, "max_chars": 120,
            "comment": "싱글들을 위한 줌 미팅방 소식 반가워요. 혼자 지낸 지 오래됐거든요. 친구가 운명원에서 인연 시기 보라던데 궁금해요."}
    other = "싱글들을 위한 줌 미팅방이라니 좋네요. 외로운데 운명원 결혼운도 궁금하네요."
    assert any(p.startswith("SAME_QUOTE") for p in review_problems(base, [other]))
