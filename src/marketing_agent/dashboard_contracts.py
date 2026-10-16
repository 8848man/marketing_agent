"""Boundary between the local dashboard and video, draft, and posting services.

Implementations of ``post_video`` must repeat ownership, approved draft, duplicate,
and daily limit checks before opening Chrome. The dashboard never treats a preview
as authorization to post.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class VideoCard:
    video_id: str
    channel_id: str
    channel: str
    title: str
    published_at: str
    thumbnail_url: str
    description: str = ""


@dataclass(frozen=True)
class DraftPreview:
    video_id: str
    worry_summary: str = ""
    comment: str = ""
    can_post: bool = False
    reason_code: str = "DRAFT_MISSING"
    cited_detail: str = ""
    evidence_sources: tuple[str, ...] = ()
    source_text: str = ""


@dataclass(frozen=True)
class PostStatus:
    state: str
    reason_code: str = ""
    message: str = ""
    screenshot_url: str = ""


@dataclass(frozen=True)
class VideoList:
    videos: tuple[VideoCard, ...] = ()
    errors: dict[str, str] = field(default_factory=dict)


class DashboardService(Protocol):
    def list_videos(self) -> VideoList: ...

    def select_video(self, video_id: str) -> DraftPreview: ...

    def post_video(self, video_id: str) -> PostStatus: ...


# Stable codes exchanged with the UI. Posting services may add more precise codes.
INVALID_VIDEO_ID = "INVALID_VIDEO_ID"
VIDEO_NOT_FOUND = "VIDEO_NOT_FOUND"
DRAFT_MISSING = "DRAFT_MISSING"
DRAFT_MISMATCH = "DRAFT_MISMATCH"
APPROVAL_MISSING = "APPROVAL_MISSING"
POST_SERVICE_UNAVAILABLE = "POST_SERVICE_UNAVAILABLE"
BAD_REQUEST = "BAD_REQUEST"
FORBIDDEN = "FORBIDDEN"
METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
INTERNAL_ERROR = "INTERNAL_ERROR"
