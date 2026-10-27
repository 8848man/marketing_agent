import re
import sys
import tomllib
from pathlib import Path

from marketing_agent.captions import CaptionResult, VideoEvidence, YouTubeCaptions
from marketing_agent.dashboard_contracts import VideoCard

ROOT = Path(__file__).resolve().parents[1]
LIBRARY_NOTICE = "youtube-transcript-api"


class _Captions:
    def __init__(self, result):
        self.result = result

    def fetch(self, video_id):
        return self.result


class _Comments:
    def __init__(self, error=None):
        self.error = error

    def fetch(self, video_id):
        if self.error:
            raise self.error
        return ()


def _card():
    return VideoCard("AbCdEfGhI12", "UC1", "채널", "제목입니다", "2026-01-01T00:00:00+00:00",
                     "https://example.invalid/t.jpg", "설명입니다")


def test_missing_caption_library_reports_code(monkeypatch):
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", None)
    result = YouTubeCaptions().fetch("AbCdEfGhI12")
    assert result.failure_reason == "CAPTIONS_LIBRARY_MISSING"


def test_evidence_notice_explains_missing_library():
    captions = _Captions(CaptionResult(failure_reason="CAPTIONS_LIBRARY_MISSING"))
    evidence = VideoEvidence(captions=captions, comments=_Comments()).collect(_card())
    assert evidence.sources == ("제목", "설명")
    assert LIBRARY_NOTICE in evidence.notice


def test_evidence_notice_combines_comment_notice():
    captions = _Captions(CaptionResult(failure_reason="CAPTIONS_LIBRARY_MISSING"))
    comments = _Comments(ValueError("COMMENTS_KEY_MISSING"))
    evidence = VideoEvidence(captions=captions, comments=comments).collect(_card())
    assert LIBRARY_NOTICE in evidence.notice
    assert "YouTube Data API 키가 없어" in evidence.notice


def test_captions_extra_is_declared_and_installed_by_default():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]["captions"]
    assert any(item.startswith("youtube-transcript-api") for item in extras)
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    match = re.search(r"^-e \.\[([^\]]*)\]", requirements, re.MULTILINE)
    assert match and "captions" in [part.strip() for part in match.group(1).split(",")]
