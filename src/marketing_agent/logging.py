"""Structured JSONL events with a deliberately narrow output schema."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_REQUEST_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9]{1,32}$")
_VIDEO_SEGMENT = re.compile(r"^[A-Za-z0-9_-]{11}$")
_LITERAL_SEGMENTS = {"youtube-key"}  # 11-character route names that are not video IDs
_MAX_LOG_BYTES = 5 * 1024 * 1024
_SECRET = re.compile(r"(?i)(api[_-]?key|cookie|token|authorization|bearer|secret|password)\s*(?:[:=]|\s)\s*[^\s,;]+")


def _redact(value: str) -> str:
    return _SECRET.sub("[REDACTED]", value)


class EventLogger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, *, event: str, run_id: str, video_id: str, input_source: str, reason: str, attempt_id: str | None = None, precheck_event_id: str | None = None, timestamp: datetime | None = None) -> dict[str, str]:
        if not all(isinstance(v, str) and v.strip() for v in (event, run_id, video_id, input_source, reason)):
            raise ValueError("event, run_id, video_id, input_source and reason are required")
        if not _SAFE_CODE.fullmatch(event):
            raise ValueError("event must be a code")
        if event in {"POST_PENDING", "POST_FAILED", "POST_OUTCOME_UNKNOWN", "POSTED"} and not attempt_id:
            raise ValueError("post event needs attempt_id")
        if event == "POST_PRECHECK_FAILED" and not precheck_event_id:
            raise ValueError("precheck event needs precheck_event_id")
        now = timestamp or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        record = {
            "timestamp": now.isoformat(), "event": event,
            "run_id": _redact(run_id), "video_id": _redact(video_id),
            "input_source": _redact(input_source), "reason": _redact(reason),
        }
        if attempt_id:
            record["attempt_id"] = _redact(attempt_id)
        if precheck_event_id:
            record["precheck_event_id"] = _redact(precheck_event_id)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return record


def request_route(path: str) -> str:
    """Path only (no query); video-ID-shaped segments become {video_id}."""
    parts = path.split("?", 1)[0].split("#", 1)[0].split("/")
    safe = ["{video_id}" if _VIDEO_SEGMENT.fullmatch(p) and p not in _LITERAL_SEGMENTS
            else re.sub(r"[^A-Za-z0-9_.\-]", "?", p)[:60] for p in parts]
    return "/".join(safe)[:200]


class RequestLogger:
    """Dashboard request records: fixed safe fields only, never query, body, headers or messages."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def emit(self, *, request_id: str, method: str, route: str, status: int, reason_code: str = "",
             duration_ms: int, error_type: str = "") -> dict[str, object]:
        def code(value: str) -> str:
            return value if not value or _REQUEST_CODE.fullmatch(value) else "INVALID"
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": str(request_id) if _REQUEST_ID.fullmatch(str(request_id)) else "INVALID",
            "method": str(method) if str(method).isalpha() and len(str(method)) <= 10 else "INVALID",
            "route": request_route(str(route)), "status": int(status),
            "reason_code": code(str(reason_code)), "duration_ms": int(duration_ms),
            "error_type": code(str(error_type)),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self.path.stat().st_size > _MAX_LOG_BYTES:
                os.replace(self.path, self.path.with_name(self.path.name + ".1"))
        except FileNotFoundError:
            pass
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return record


def configure_logging(path: str | Path) -> EventLogger:
    """Return the event writer; arbitrary Python log records are not serialized."""
    return EventLogger(path)
