"""One cycle of discovery, classification, timing, writing and guarded delivery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
from uuid import uuid4

from .ai_client import ClaudeClient
from .captions import YouTubeCaptions
from .classifier import Classifier, Video
from .config import AgentConfig, load_config
from .dry_run import save_comment
from .http_client import NoRedirectHandler, ResponseTooLarge, read_limited
from .fixtures import OFFLINE_VIDEO, OfflineAI, OfflineCaptions
from .logging import EventLogger
from .search_budget import SearchBudget
from .storage import Store
from .trigger import evaluate
from .watcher import Watcher
from .writer import Writer


class YouTubeDataAPI:
    """Small Data API adapter; constructing it never performs a request."""

    def __init__(self, key: str):
        if not key:
            raise ValueError("YOUTUBE_API_KEY is required for live search")
        self.key = key

    def _get(self, resource: str, **params) -> dict:
        query = urlencode({**params, "key": self.key})
        request = Request(f"https://www.googleapis.com/youtube/v3/{resource}?{query}")
        try:
            with build_opener(NoRedirectHandler()).open(request, timeout=30) as response:
                raw = read_limited(response, 1_000_000)
        except ResponseTooLarge:
            raise ValueError("YOUTUBE_API_RESPONSE_TOO_LARGE") from None
        except (HTTPError, URLError, OSError, TimeoutError):
            raise ValueError("YOUTUBE_API_FAILED") from None
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise ValueError("YOUTUBE_API_RESPONSE_INVALID") from None
        if not isinstance(result, dict):
            raise ValueError("YOUTUBE_API_RESPONSE_INVALID")
        return result


    def search(self, **parameters) -> dict:
        return self._get("search", **parameters)

    def videos(self, ids: list[str]) -> dict:
        return self._get("videos", part="snippet,statistics", id=",".join(ids))

    def owner(self, video_id: str) -> dict:
        return self._get("videos", part="snippet", id=video_id)

    def comments(self, video_id: str) -> list[str]:
        data = self._get("commentThreads", part="snippet", videoId=video_id, maxResults=20, textFormat="plainText")
        return [item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {}).get("textOriginal", "")
                for item in data.get("items", [])]


def _reason(exc: Exception) -> str:
    # Exception messages may contain a request URL with an API key in its query.
    if isinstance(exc, ValueError) and str(exc).isupper() and str(exc).replace("_", "").isalnum():
        return str(exc)
    return type(exc).__name__


def run_cycle(*, config: AgentConfig, store: Store, logger: EventLogger,
              dry_run_path: str | Path, screenshot_dir: str | Path,
              offline: bool = False, dry_run: bool = False, api=None, ai=None,
              captions=None, now: datetime | None = None, run_id: str | None = None,
               post=None) -> dict:
    """Discover and draft only; the legacy CLI has no public posting capability.

    ``post`` remains accepted for older callers but is never invoked.
    """
    now = now or datetime.now(timezone.utc)
    run_id = run_id or uuid4().hex
    source = "offline_fixture" if offline else "live_search"
    summary = {"run_id": run_id, "candidates": 0, "comments": 0, "post_calls": 0, "errors": 0}

    def emit(event: str, video_id: str, reason: str, *, attempt_id: str | None = None) -> None:
        logger.emit(event=event, run_id=run_id, video_id=video_id,
                    input_source=source, reason=reason, timestamp=now,
                    attempt_id=attempt_id)

    if offline:
        ai = ai or OfflineAI()
        captions = captions or OfflineCaptions()
        candidates = [(OFFLINE_VIDEO, "offline-channel", now - timedelta(hours=2), 1500)]
        emit("DETECTED", OFFLINE_VIDEO.video_id, "OFFLINE_FIXTURE")
    else:
        api = api or YouTubeDataAPI(os.getenv("YOUTUBE_API_KEY", ""))
        ai = ai or ClaudeClient()
        captions = captions or YouTubeCaptions()
        budget = SearchBudget(config.daily_search_budget)
        watcher = Watcher(api, config, budget, clock=lambda: now, store=store, logger=logger, run_id=run_id)
        found = watcher.search_cycle(now)
        candidates = []
        for video_id in found.candidates:
            try:
                item = watcher.candidates[video_id]
                snippet = item.get("snippet", {})
                published = datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00"))
                details = api.videos([video_id]).get("items", [])
                count = int(details[0]["statistics"]["viewCount"])
                video = Video(video_id, snippet.get("title", ""), snippet.get("description", ""))
                candidates.append((video, snippet.get("channelId", "unknown"), published, count))
            except Exception as exc:
                summary["errors"] += 1
                emit("STAGE_ERROR", video_id, f"detect: {_reason(exc)}")
        if not candidates:
            emit("CYCLE_EMPTY", "-", ",".join(found.reasons) or "NO_CANDIDATES")

    for video, channel_id, published, views in candidates:
        video_id = video.video_id
        summary["candidates"] += 1
        try:
            if store.video(video_id) is None:
                store.save_video(video_id, channel_id, now, published_at=published, title=video.title)
            if not store.views(video_id):
                store.add_view(video_id, now, views)
            emit("VIEW_SNAPSHOT", video_id, f"VIEW_COUNT_{views}")
        except Exception as exc:
            summary["errors"] += 1
            emit("STAGE_ERROR", video_id, f"detect: {_reason(exc)}")
            continue
        if store.comment(video_id) is not None or store.attempt(video_id) is not None:
            emit("ALREADY_PROCESSED", video_id, "COMMENT_OR_ATTEMPT_EXISTS")
            continue
        try:
            classification = Classifier(ai, captions, config.topic).classify(video)
            emit("CLASSIFIED", video_id, "ON_TOPIC" if classification.on_topic else "OFF_TOPIC")
            if not classification.on_topic:
                continue
        except Exception as exc:
            summary["errors"] += 1
            emit("STAGE_ERROR", video_id, f"classify: {_reason(exc)}")
            continue
        try:
            timing = evaluate(views, published, now, config.trigger)
            emit("TRIGGER_EVALUATED", video_id, f"{timing.state.upper()}:{timing.reason}")
            if timing.state != "eligible":
                store.save_video(video_id, channel_id, now, published_at=published,
                                 title=video.title, state=timing.state,
                                 classified_reason=classification.reason,
                                 used_captions=classification.used_captions)
                continue
        except Exception as exc:
            summary["errors"] += 1
            emit("STAGE_ERROR", video_id, f"timing: {_reason(exc)}")
            continue
        try:
            existing = () if offline else api.comments(video_id)
            draft = Writer(ai, store=store, min_chars=config.comment.min_chars,
                           max_chars=config.comment.max_chars).write(video, classification,
                                                                    existing_comments=existing)
            emit(draft.state, video_id, draft.reason or "VALIDATED")
            if draft.state != "COMMENT_WRITTEN":
                continue
            store.save_comment(video_id, draft.body, now, state="DRY_RUN_SAVED",
                                            worry_summary=draft.worry_summary, cited_detail=draft.cited_detail,
                                            source=source, fit_result="validated",
                                             dry_run_path=str(dry_run_path))
            summary["comments"] += 1
        except Exception as exc:
            summary["errors"] += 1
            emit("STAGE_ERROR", video_id, f"write: {_reason(exc)}")
            continue
        try:
            save_comment(dry_run_path, video_id=video_id, body=draft.body, reason="READ_ONLY_CLI",
                         run_id=run_id, input_source=source)
            emit("DRY_RUN_SAVED", video_id, "READ_ONLY_CLI")
        except Exception as exc:
            summary["errors"] += 1
            emit("STAGE_ERROR", video_id, f"save: {_reason(exc)}")
    emit("CYCLE_DONE", "-", f"CANDIDATES_{summary['candidates']}_COMMENTS_{summary['comments']}_POST_CALLS_{summary['post_calls']}")
    return summary
