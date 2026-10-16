"""Local, content-free progress records for the visible posting path."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class PostEvent:
    stage: str
    reason_code: str = ""
    screenshot_path: str = ""
    at: str = ""


def event(stage: str, reason_code: str = "", screenshot_path: str = "") -> PostEvent:
    return PostEvent(stage, reason_code, screenshot_path,
                     datetime.now(timezone.utc).isoformat())
