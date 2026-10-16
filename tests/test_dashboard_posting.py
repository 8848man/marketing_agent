"""The dashboard service is the only caller that may authorize Chrome work."""

from datetime import datetime, timezone
import json

from marketing_agent.dashboard_contracts import VideoCard, VideoList
from marketing_agent.drafts import content_hash
from marketing_agent.posting_service import PostingService
from marketing_agent.storage import Store


VIDEO = VideoCard("AbCdEfGhI12", "UCxlc0Ky0aWoD8uI09ad44Tg", "외롭여",
                  "답장이 늦는 날", "2026-10-15", "")
BODY = "답장을 기다리던 장면에서 불안한 마음이 전해졌어요. 운명원 연애 사주로 두 사람의 흐름을 살펴보면 어떨지 궁금하네요."
NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)


def _service(tmp_path, poster):
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    record = dict(video_id=VIDEO.video_id, channel_id=VIDEO.channel_id,
                  title=VIDEO.title, worry_summary="답장을 기다리는 불안", comment=BODY,
                  cited_detail="답장을 기다리던 장면", source_text="답장을 기다리던 장면",
                  reviewer="human", reviewed_at="2026-10-15T10:00:00+09:00")
    record["content_hash"] = record["approval_hash"] = content_hash(record)
    (drafts / f"{VIDEO.video_id}.json").write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8")
    service = PostingService(tmp_path / "state.sqlite", drafts, poster=poster,
                             feed_loader=lambda: VideoList((VIDEO,)),
                             recheck=lambda *_: VIDEO, clock=lambda: NOW)
    service.list_videos()
    return service


def test_selection_does_not_launch_and_click_requires_fresh_rss(tmp_path):
    calls = []
    service = _service(tmp_path, lambda *_: calls.append("launch"))
    assert service.select_video(VIDEO.video_id).can_post
    assert calls == []
    service.recheck = lambda *_: None
    assert service.post_video(VIDEO.video_id).state == "blocked"
    with Store(service.db_path) as store:
        assert store.dashboard_attempt(VIDEO.video_id) is None
    assert calls == []


def test_click_marker_keeps_uncertain_result_reserved(tmp_path):
    calls = []

    def poster(card, body, before_click):
        assert card == VIDEO and body == BODY
        calls.append("open")
        before_click()
        calls.append("click")
        raise TimeoutError("ambiguous click")

    service = _service(tmp_path, poster)
    assert service.select_video(VIDEO.video_id).can_post
    assert service.post_video(VIDEO.video_id).state == "uncertain"
    assert service.post_video(VIDEO.video_id).reason_code == "ALREADY_ATTEMPTED"
    assert calls == ["open", "click"]
    with Store(service.db_path) as store:
        assert store.dashboard_attempt(VIDEO.video_id)["status"] == "OUTCOME_UNKNOWN"
