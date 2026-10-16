"""Injectable caption retrieval; a failure never hides title/description evidence."""

from dataclasses import dataclass
from collections.abc import Callable
import json
import os
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.parse import urlencode

from .dashboard_contracts import VideoCard


@dataclass(frozen=True)
class CaptionResult:
    text: str = ""
    failure_reason: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.text.strip())


class CaptionProvider(Protocol):
    def fetch(self, video_id: str) -> CaptionResult: ...


class YouTubeCaptions:
    """Optional youtube-transcript-api adapter, imported only for live retrieval."""

    def fetch(self, video_id: str) -> CaptionResult:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            api = YouTubeTranscriptApi()
            snippets = api.fetch(video_id, languages=["ko", "en"])
            text = " ".join(item.text for item in snippets).strip()
            return CaptionResult(text) if text else CaptionResult(failure_reason="EMPTY_CAPTIONS")
        except Exception as exc:  # Captions are optional, including absent dependency.
            return CaptionResult(failure_reason=f"{type(exc).__name__}: {exc}")


@dataclass(frozen=True)
class EvidenceResult:
    text: str
    sources: tuple[str, ...]
    notice: str = ""


class PopularCommentsProvider(Protocol):
    def fetch(self, video_id: str) -> tuple[str, ...]: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class YouTubeDataComments:
    """Optional public-comment source; resolve its key only for explicit fetches."""

    def __init__(self, api_key: str | None = None,
                 key_provider: Callable[[], str] | None = None):
        self.api_key = api_key if api_key is not None else os.getenv("YOUTUBE_API_KEY", "")
        self.key_provider = key_provider

    def fetch(self, video_id: str) -> tuple[str, ...]:
        api_key = self.key_provider() if self.key_provider is not None else self.api_key
        if not api_key:
            raise ValueError("COMMENTS_KEY_MISSING")
        query = urlencode({"part": "snippet", "videoId": video_id, "maxResults": 10,
                           "order": "relevance", "textFormat": "plainText", "key": api_key})
        request = Request(f"https://www.googleapis.com/youtube/v3/commentThreads?{query}",
                          headers={"Accept": "application/json"})
        try:
            with build_opener(_NoRedirect()).open(request, timeout=10) as response:
                raw = response.read(200_001)
        except HTTPError as exc:
            raise ValueError("COMMENTS_KEY_INVALID" if exc.code in (400, 401) else "COMMENTS_UNAVAILABLE") from None
        except (URLError, OSError, TimeoutError):
            raise ValueError("COMMENTS_UNAVAILABLE") from None
        if len(raw) > 200_000:
            raise ValueError("COMMENTS_UNAVAILABLE")
        try:
            data = json.loads(raw)
            rows = data.get("items", [])
            comments = [row["snippet"]["topLevelComment"]["snippet"]["textDisplay"].strip()
                        for row in rows if isinstance(row, dict)]
        except (TypeError, KeyError, ValueError):
            raise ValueError("COMMENTS_UNAVAILABLE") from None
        return tuple(text for text in comments if text)[:10]


class VideoEvidence:
    """Collect only the evidence needed for one explicit draft-generation request."""

    def __init__(self, captions: CaptionProvider | None = None,
                 comments: PopularCommentsProvider | None = None,
                 key_provider: Callable[[], str] | None = None):
        self.captions = captions or YouTubeCaptions()
        self.comments = comments or YouTubeDataComments(key_provider=key_provider)

    def collect(self, card: VideoCard) -> EvidenceResult:
        caption = self.captions.fetch(card.video_id)
        if caption.available:
            primary, sources = caption.text, ["자막"]
        else:
            primary = "\n".join(part for part in (card.title, card.description) if part.strip())
            sources = ["제목", *( ["설명"] if card.description.strip() else [])]
        if not primary.strip():
            raise ValueError("EVIDENCE_MISSING")
        notice = ""
        try:
            popular = self.comments.fetch(card.video_id)
        except ValueError as exc:
            popular = ()
            notice = "인기 댓글을 가져오지 못해 자막 또는 제목·설명만 근거로 사용합니다."
            if str(exc) == "COMMENTS_KEY_MISSING":
                notice = "YouTube Data API 키가 없어 인기 댓글 없이 자막 또는 제목·설명만 근거로 사용합니다."
            elif str(exc) == "COMMENTS_KEY_INVALID":
                notice = "YouTube Data API 키가 유효하지 않아 인기 댓글 없이 자막 또는 제목·설명만 근거로 사용합니다."
        if popular:
            primary += "\n\n[인기 댓글]\n" + "\n".join(popular)
            sources.append("인기 댓글")
        return EvidenceResult(primary, tuple(sources), notice)
