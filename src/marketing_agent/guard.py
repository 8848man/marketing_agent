"""Ownership gate for the sole comment submission path."""

from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import parse_qs, urlparse


_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def normalize_video_id(value: str) -> str:
    """Accept a YouTube ID or a canonical watch, short, or live URL."""
    if not isinstance(value, str):
        raise ValueError("INVALID_VIDEO_ID")
    value = value.strip()
    if _ID.fullmatch(value):
        return value
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
        raise ValueError("INVALID_VIDEO_ID")
    host = (parsed.hostname or "").lower()
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            ids = parse_qs(parsed.query).get("v", [])
            candidate = ids[0] if len(ids) == 1 else ""
        elif parsed.path.startswith(("/shorts/", "/live/")):
            candidate = parsed.path.split("/")[2] if len(parsed.path.split("/")) == 3 else ""
        else:
            candidate = ""
    elif host == "youtu.be" and parsed.path.count("/") == 1:
        candidate = parsed.path[1:]
    else:
        candidate = ""
    if not _ID.fullmatch(candidate):
        raise ValueError("INVALID_VIDEO_ID")
    return candidate


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    reason: str
    video_id: str
    owner_channel_id: str | None = None


def check_rss_membership(video: str, channel_id: str, *, recheck=None) -> GuardDecision:
    """Only a fresh entry in one of the fixed feeds proves ownership.

    A direct URL may supply an ID, but an ID absent from the RSS is blocked;
    this function never opens an unverified video page.
    """
    from .rss_feed import CHANNELS, recheck_video

    try:
        video_id = normalize_video_id(video)
    except ValueError:
        return GuardDecision(False, "INVALID_VIDEO_ID", str(video))
    if channel_id not in CHANNELS:
        return GuardDecision(False, "CHANNEL_NOT_ALLOWED", video_id)
    try:
        card = (recheck or recheck_video)(video_id, channel_id)
    except Exception:
        card = None
    if card is None or card.video_id != video_id or card.channel_id != channel_id:
        return GuardDecision(False, "RSS_MEMBERSHIP_UNVERIFIED", video_id)
    return GuardDecision(True, "POST_ALLOWED", video_id, channel_id)


def check_ownership(video: str, allowed_videos: tuple[str, ...] | list[str], ownership: object, api_channel_id: str | None = None) -> GuardDecision:
    """Fail closed on malformed list entries, missing Studio proof, or API mismatch."""
    try:
        video_id = normalize_video_id(video)
    except ValueError:
        return GuardDecision(False, "INVALID_VIDEO_ID", str(video))
    normalized: set[str] = set()
    try:
        normalized = {normalize_video_id(item) for item in allowed_videos}
    except (ValueError, TypeError):
        return GuardDecision(False, "ALLOWLIST_BLOCKED", video_id)
    if video_id not in normalized:
        return GuardDecision(False, "ALLOWLIST_BLOCKED", video_id)
    if not ownership:
        return GuardDecision(False, "OWNERSHIP_BLOCKED", video_id)
    try:
        owner = ownership["owner_channel_id"]
        proof_video = ownership["video_id"]
        evidence = ownership["evidence_path"]
        verified = ownership["verified_at"]
    except (KeyError, IndexError, TypeError):
        return GuardDecision(False, "OWNERSHIP_BLOCKED", video_id)
    if proof_video != video_id or not all(isinstance(x, str) and x.strip() for x in (owner, evidence, verified)):
        return GuardDecision(False, "OWNERSHIP_BLOCKED", video_id)
    if api_channel_id is not None and api_channel_id != owner:
        return GuardDecision(False, "OWNERSHIP_BLOCKED", video_id, owner)
    return GuardDecision(True, "POST_ALLOWED", video_id, owner)
