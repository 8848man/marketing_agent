"""Focused feed and human-approved draft safety checks."""

from __future__ import annotations

import json

from marketing_agent.dashboard_contracts import VideoCard
from marketing_agent.captions import CaptionResult, VideoEvidence
from marketing_agent.dashboard_ui import FeedDraftService, page
from marketing_agent.dashboard_contracts import VideoList
from marketing_agent.drafts import approve, content_hash, preview, quality_failure, save_generated
from marketing_agent.rss_feed import CHANNELS, FeedError, list_videos, parse_channel, recheck_video


VIDEO_ID = "AbCdEfGhI12"
CHANNEL_ID = next(iter(CHANNELS))
TITLE = "새 영상 제목"


def feed(channel_id=CHANNEL_ID, *, feed_channel=None, entry_channel=None, video_id=VIDEO_ID):
    feed_channel = channel_id if feed_channel is None else feed_channel
    entry_channel = channel_id if entry_channel is None else entry_channel
    return f'''<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"
          xmlns:media="http://search.yahoo.com/mrss/">
      <yt:channelId>{feed_channel}</yt:channelId>
      <entry><yt:videoId>{video_id}</yt:videoId><yt:channelId>{entry_channel}</yt:channelId>
      <title>{TITLE}</title><published>2026-10-15T00:00:00+00:00</published>
      <media:group><media:thumbnail url="https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" /></media:group>
      </entry></feed>'''.encode()


def video():
    return VideoCard(VIDEO_ID, CHANNEL_ID, CHANNELS[CHANNEL_ID], TITLE,
                     "2026-10-15T00:00:00+00:00", f"https://i.ytimg.com/vi/{VIDEO_ID}/hqdefault.jpg")


def approved():
    draft = {
        "video_id": VIDEO_ID, "channel_id": CHANNEL_ID, "title": TITLE,
        "worry_summary": "연애에서 상대 마음이 불확실한 고민",
        "cited_detail": "답장이 늦어지는 장면",
        "source_text": "영상에서는 답장이 늦어지는 장면을 말합니다.",
        "comment": "답장이 늦어지는 장면이 특히 마음에 남네요. 기다리는 동안 내 마음도 살피고, 운명원 연애 사주로 두 사람의 흐름을 살펴보고 싶어져요.",
        "reviewer": "human reviewer", "reviewed_at": "2026-10-15T09:00:00+09:00",
    }
    draft["content_hash"] = content_hash(draft)
    draft["approval_hash"] = draft["content_hash"]
    return draft


def save(tmp_path, draft):
    (tmp_path / "latest.json").write_text(json.dumps({"drafts": [draft]}, ensure_ascii=False), encoding="utf-8")


def test_five_fixed_keyless_feeds_and_partial_failure():
    requested = []

    def fetch(channel_id):
        requested.append(channel_id)
        if channel_id == "UC-ee_ziASM251TMXe3P3VZA":
            raise OSError("offline")
        return feed(channel_id)

    result = list_videos(fetch=fetch)
    assert requested == list(CHANNELS)
    assert len(result.videos) == 4
    assert len(result.errors) == 1
    assert {item.channel_id for item in result.videos} == set(CHANNELS) - {"UC-ee_ziASM251TMXe3P3VZA"}
    assert all(item.video_id == VIDEO_ID and item.thumbnail_url.startswith("https://i.ytimg.com/")
               and item.title == TITLE and item.published_at for item in result.videos)


def test_feed_owner_mismatch_and_recheck_failure_close():
    # Live YouTube RSS omits "UC" only in the top-level channel ID.
    assert parse_channel(feed(feed_channel=CHANNEL_ID[2:]), CHANNEL_ID) == (video(),)
    for invalid in ("UCwrong", ""):
        try:
            parse_channel(feed(feed_channel=invalid), CHANNEL_ID)
        except FeedError as exc:
            assert str(exc) == "RSS_CHANNEL_MISMATCH"
        else:
            assert False, "unexpected feed channel must fail"
    try:
        parse_channel(feed(entry_channel="UCwrong"), CHANNEL_ID)
    except FeedError as exc:
        assert str(exc) == "RSS_CHANNEL_MISMATCH"
    else:
        assert False, "mismatched entry must fail"
    assert recheck_video(VIDEO_ID, CHANNEL_ID, fetch=lambda _: feed()) == video()
    assert recheck_video(VIDEO_ID, CHANNEL_ID, fetch=lambda _: (_ for _ in ()).throw(OSError())) is None
    assert recheck_video(VIDEO_ID, CHANNEL_ID, fetch=lambda _: feed(video_id="XyZaBcDeF34")) is None


def test_approved_draft_and_mismatch_reasons(tmp_path):
    draft = approved()
    save(tmp_path, draft)
    assert preview(video(), tmp_path).can_post
    for field, value, reason in [
        ("channel_id", "UCwrong", "DRAFT_CHANNEL_MISMATCH"),
        ("title", "changed", "DRAFT_TITLE_MISMATCH"),
        ("approval_hash", "0" * 64, "APPROVAL_HASH_MISMATCH"),
        ("comment", "tampered", "COMMENT_LENGTH"),
    ]:
        changed = dict(draft, **{field: value})
        save(tmp_path, changed)
        result = preview(video(), tmp_path)
        assert not result.can_post and result.reason_code == reason
    (tmp_path / "latest.json").unlink()
    assert preview(video(), tmp_path).reason_code == "DRAFT_MISSING"


def test_individual_approved_draft_is_used_when_latest_omits_video(tmp_path):
    draft = approved()
    (tmp_path / "latest.json").write_text(json.dumps({"drafts": []}), encoding="utf-8")
    (tmp_path / f"{VIDEO_ID}.json").write_text(json.dumps(draft), encoding="utf-8")
    assert preview(video(), tmp_path).can_post


def test_hash_and_human_review_required(tmp_path):
    draft = approved()
    draft["comment"] += " 기다려 볼게요."
    save(tmp_path, draft)
    assert preview(video(), tmp_path).reason_code == "DRAFT_CONTENT_HASH_MISMATCH"
    draft = approved()
    draft["source_text"] = "다른 영상의 내용"
    save(tmp_path, draft)
    assert preview(video(), tmp_path).reason_code == "UNSUPPORTED_DETAIL"
    draft = approved()
    draft["reviewer"] = ""
    save(tmp_path, draft)
    assert preview(video(), tmp_path).reason_code == "HUMAN_REVIEW_MISSING"


def test_generated_draft_needs_human_approval_before_posting(tmp_path):
    card = video()
    generated = save_generated(card, {
        "worry_summary": "답장이 늦어져 불안한 마음",
        "cited_detail": TITLE,
        "comment": f"{TITLE} 장면이 특히 마음에 남네요. 기다리는 마음이 불안할 때 운명원 연애 사주로 관계의 흐름을 살펴보고 싶어져요.",
    }, tmp_path)
    assert preview(card, tmp_path).reason_code == "APPROVAL_MISSING"
    approved_draft = approve(card, {**{key: generated[key] for key in
        ("worry_summary", "cited_detail", "comment")}, "reviewer": "human reviewer"}, tmp_path)
    assert approved_draft["approval_hash"] == approved_draft["content_hash"]
    assert preview(card, tmp_path).can_post
    assert preview(card, tmp_path).source_text == card.title


def test_evidence_uses_captions_then_title_description_and_optional_comments():
    class Captions:
        def fetch(self, _video_id):
            return CaptionResult("영상 속 구체 장면 자막")

    class Comments:
        def fetch(self, _video_id):
            return ("인기 댓글 한 개",)

    card = VideoCard(VIDEO_ID, CHANNEL_ID, "채널", TITLE, "날짜", "", "영상 설명")
    result = VideoEvidence(Captions(), Comments()).collect(card)
    assert result.sources == ("자막", "인기 댓글")
    assert "구체 장면 자막" in result.text and "인기 댓글 한 개" in result.text

    class MissingCaptions:
        def fetch(self, _video_id):
            return CaptionResult(failure_reason="not available")

    class MissingComments:
        def fetch(self, _video_id):
            raise ValueError("COMMENTS_KEY_MISSING")

    fallback = VideoEvidence(MissingCaptions(), MissingComments()).collect(card)
    assert fallback.sources == ("제목", "설명")
    assert TITLE in fallback.text and "영상 설명" in fallback.text
    assert "YouTube Data API 키" in fallback.notice


def test_generated_draft_rejects_missing_blank_or_extra_schema_fields(tmp_path):
    for result in (
        {"worry_summary": "고민", "cited_detail": TITLE},
        {"worry_summary": "고민", "cited_detail": TITLE, "comment": "  "},
        {"worry_summary": "고민", "cited_detail": TITLE, "comment": "본문", "extra": "x"},
    ):
        try:
            save_generated(video(), result, tmp_path)
            assert False
        except ValueError as exc:
            assert str(exc) == "AI_RESPONSE_SCHEMA_INVALID"
    assert not (tmp_path / f"{VIDEO_ID}.json").exists()


def test_comment_length_link_and_hashtag_rules():
    draft = approved()
    assert quality_failure(draft) == ""
    assert quality_failure(dict(draft, comment="짧음")) == "COMMENT_LENGTH"
    assert quality_failure(dict(draft, comment=draft["comment"] + " https://example.com")) == "COMMENT_LINK"
    assert quality_failure(dict(draft, comment=draft["comment"] + " #연애")) == "COMMENT_HASHTAG"
    assert quality_failure(dict(draft, comment=draft["comment"].replace("운명원", "다른 곳"))) == "BRAND_CONTEXT_MISSING"


def test_brand_used_as_common_noun_or_past_visit_is_rejected():
    """Regression for 2026-10-16 drafts that treated 운명원 as 'destined partner'."""
    draft = approved()
    base = "답장이 늦어지는 장면 너무 공감돼요. 나도 인연이 언제 오는지 궁금하다. "
    misused = ("혹시 여기서 저의 운명원을 만날 수 있을까요? 진짜 궁금해요",
               "올해는 운명원을 만날 좋은 기회라고 하던데 용기를 내봐야겠어요",
               "제 운명원은 어디에 있을지 궁금해지는 밤이네요 정말로요")
    for tail in misused:
        assert quality_failure(dict(draft, comment=base + tail)) == "BRAND_MISUSED", tail
    visited = base + "운명원에서 사주 봤더니 올해 인연 들어온다고 했어요"
    assert quality_failure(dict(draft, comment=visited)) == "FABRICATED_TESTIMONIAL"
    ongoing = base + "요즘 운명원은 물론 사주까지 보면서 짝을 찾는 중이에요"
    assert quality_failure(dict(draft, comment=ongoing)) == "FABRICATED_TESTIMONIAL"
    result = base + "운명원이나 사주에서 제 연애운이 안 좋았던 이유가 있었네요"
    assert quality_failure(dict(draft, comment=result)) == "FABRICATED_TESTIMONIAL"
    intent = base + "언젠가 운명원에서 제 연애운도 한번 봐보고 싶어요"
    assert quality_failure(dict(draft, comment=intent)) == ""
    negative = base + "사주나 운명원에 의지하기 전에 내 행동부터 바꿔야겠어요"
    assert quality_failure(dict(draft, comment=negative)) == "BRAND_NEGATIVE_FRAMING"
    curious = base + "운명원 연애사주가 그렇게 잘 본다던데 한번 보고 싶다"
    assert quality_failure(dict(draft, comment=curious)) == ""


def test_ui_selection_has_no_post_or_chrome_action():
    html = page("token").decode("utf-8")
    assert all(label in html for label in ("① 영상 불러오기", "② 영상 선택", "③ 댓글 달기"))
    selection = html.split("async function selectVideo", 1)[1].split("async function postComment", 1)[0]
    assert "/api/post" not in selection


def test_feed_failure_never_leaves_stale_postable_selection(tmp_path):
    save(tmp_path, approved())
    responses = iter((VideoList((video(),), {}), VideoList((), {CHANNELS[CHANNEL_ID]: "TimeoutError"})))
    service = FeedDraftService(tmp_path, feed_loader=lambda: next(responses))
    service.list_videos()
    assert service.select_video(VIDEO_ID).can_post
    service.list_videos()
    assert service.select_video(VIDEO_ID).reason_code == "VIDEO_NOT_FOUND"
    assert service.post_video(VIDEO_ID).state == "blocked"


def test_rss_outage_without_cache_shows_only_approved_draft_videos(tmp_path):
    """IMP-20: display-only fallback; unapproved, failing or other-channel drafts never appear."""
    from marketing_agent.drafts import approved_draft_cards
    good = approved()
    (tmp_path / f"{VIDEO_ID}.json").write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")
    unapproved = {**good, "video_id": "Unapproved1"}
    unapproved.pop("approval_hash")
    (tmp_path / "Unapproved1.json").write_text(json.dumps(unapproved, ensure_ascii=False), encoding="utf-8")
    other = {**approved(), "video_id": "OtherChan01", "channel_id": "UC" + "x" * 22}
    other["content_hash"] = other["approval_hash"] = content_hash(other)
    (tmp_path / "OtherChan01.json").write_text(json.dumps(other, ensure_ascii=False), encoding="utf-8")
    cards = approved_draft_cards(tmp_path, CHANNEL_ID, "외롭여")
    assert [card.video_id for card in cards] == [VIDEO_ID]
    assert cards[0].title == TITLE and cards[0].thumbnail_url.startswith("https://i.ytimg.com/vi/")
    assert preview(cards[0], tmp_path).can_post      # same title/channel as the approved draft

    def down(channel_id, **_):
        raise FeedError("RSS_HTTP_500")
    result = list_videos(fetch=down, channels={CHANNEL_ID: "외롭여"}, cache_dir=tmp_path / "cache",
                         fallback=lambda cid: approved_draft_cards(tmp_path, cid, "외롭여"))
    assert [card.video_id for card in result.videos] == [VIDEO_ID]
    assert result.errors == {"외롭여": "RSS_HTTP_500 · 승인 초안 영상 1개만 표시"}
    # posting time recheck has no fallback: it fails closed
    assert recheck_video(VIDEO_ID, CHANNEL_ID, fetch=down, channels={CHANNEL_ID: "외롭여"}) is None
    # a cached feed still wins over the fallback
    result = list_videos(fetch=lambda cid: feed(), channels={CHANNEL_ID: "외롭여"}, cache_dir=tmp_path / "cache")
    result = list_videos(fetch=down, channels={CHANNEL_ID: "외롭여"}, cache_dir=tmp_path / "cache",
                         fallback=lambda cid: (_ for _ in ()).throw(AssertionError("fallback used")))
    assert "받은 목록 표시" in result.errors["외롭여"]


def test_rss_errors_are_explained_in_plain_korean():
    from marketing_agent.dashboard_page import render_page
    html = render_page("t").decode("utf-8")
    assert "function rssText" in html and "YouTube RSS 서버 오류" in html
    assert "rssText(error)" in html and "rssText(error.message)" in html
