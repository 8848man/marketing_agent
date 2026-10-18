"""Boundary between the local dashboard and video, draft, and posting services.

Implementations of ``post_video`` must repeat ownership, approved draft, duplicate,
and daily limit checks before opening Chrome. The dashboard never treats a preview
as authorization to post.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


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
    min_chars: int = 40
    max_chars: int = 120


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


# Optional dashboard capabilities remain separate so demo and focused test services
# can implement only the routes they support. Runtime checks test the named method;
# annotations document the expected call and response shape for implementers.
@runtime_checkable
class ReviewPickService(Protocol):
    def review_pick(self) -> dict[str, str] | None: ...


@runtime_checkable
class VideoStateService(Protocol):
    def video_states(self) -> dict[str, dict[str, str]]: ...


@runtime_checkable
class SettingsReadService(Protocol):
    def settings_yaml(self) -> str: ...


@runtime_checkable
class SettingsWriteService(Protocol):
    def save_settings_yaml(self, source: str) -> str: ...


@runtime_checkable
class ChannelReadService(Protocol):
    def channel_ids(self) -> list[str]: ...


@runtime_checkable
class ChannelEntryReadService(Protocol):
    def channel_entries(self) -> list[dict[str, str]]: ...


@runtime_checkable
class ChannelWriteService(Protocol):
    def save_channel_ids(self, channels: list[str]) -> list[str]: ...


@runtime_checkable
class ChannelEntryWriteService(Protocol):
    def save_channel_entries(self, entries: list[dict[str, str]]) -> list[dict[str, str]]: ...


@runtime_checkable
class AIReadService(Protocol):
    def ai_public(self) -> dict[str, object]: ...


@runtime_checkable
class BrandReadService(Protocol):
    def brand_public(self) -> dict[str, str]: ...


@runtime_checkable
class BrandWriteService(Protocol):
    def save_brand(self, name: str, description: str, reference_url: str) -> dict[str, str]: ...


@runtime_checkable
class CommentGenerationReadService(Protocol):
    def comment_generation_public(self) -> dict[str, str | int]: ...


@runtime_checkable
class CommentGenerationWriteService(Protocol):
    def save_comment_generation(self, name: str, description: str, reference_url: str,
                                min_chars: int, max_chars: int) -> dict[str, str | int]: ...


@runtime_checkable
class AIWriteService(Protocol):
    def save_ai(self, provider: str, model: str, api_key: str, *, clear_key: bool) -> dict[str, object]: ...


@runtime_checkable
class AITestService(Protocol):
    def test_ai(self) -> dict[str, object]: ...


@runtime_checkable
class ProfileReadService(Protocol):
    def profile_public(self) -> dict[str, object]: ...


@runtime_checkable
class ProfileOptionsService(Protocol):
    def profile_options_public(self) -> dict[str, object]: ...


@runtime_checkable
class ProfileWriteService(Protocol):
    def save_profile(self, label: str) -> dict[str, object]: ...


@runtime_checkable
class ProfileAddService(Protocol):
    def add_profile(self, label: str) -> dict[str, object]: ...


@runtime_checkable
class ProfileMemoService(Protocol):
    def save_profile_memo(self, label: str, memo: str) -> dict[str, object]: ...


@runtime_checkable
class ProfileVerifyService(Protocol):
    def verify_profile(self, label: str) -> dict[str, object]: ...


@runtime_checkable
class ProfileOpenService(Protocol):
    def open_app_profile(self, label: str) -> dict[str, object]: ...


@runtime_checkable
class YouTubeKeyService(Protocol):
    def save_youtube_api_key(self, key: str) -> dict[str, bool]: ...


@runtime_checkable
class DraftGenerationService(Protocol):
    def generate_draft(self, video_id: str) -> dict[str, object]: ...


@runtime_checkable
class DraftRefineService(Protocol):
    def refine_draft(self, video_id: str, rewrite: bool = False) -> dict[str, object]: ...


@runtime_checkable
class SetupStatusService(Protocol):
    def setup_status(self) -> dict[str, object]: ...


@runtime_checkable
class HistoryService(Protocol):
    def history(self, limit: int = 50) -> dict[str, object]: ...


@runtime_checkable
class DraftApprovalService(Protocol):
    def approve_draft(self, video_id: str, values: dict[str, str]) -> dict[str, object]: ...


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
