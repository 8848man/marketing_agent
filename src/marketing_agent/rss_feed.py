"""Keyless, fixed-channel YouTube RSS discovery and ownership rechecks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET

from .dashboard_contracts import VideoCard, VideoList


CHANNELS = {
    "UCxlc0Ky0aWoD8uI09ad44Tg": "외롭여",
    "UC-ee_ziASM251TMXe3P3VZA": "리즈시절 LizTV",
    "UC09L3JxGVcn7SKLa-pjTEmw": "러브커넥트 유지연",
    "UCVdtDW-HF4KluixGaBAcI4w": "연애데이터 노노",
    "UCkGl2jieOVhGiHPdXF77Yyw": "심리조각",
}
ATOM = "{http://www.w3.org/2005/Atom}"
YT = "{http://www.youtube.com/xml/schemas/2015}"
MEDIA = "{http://search.yahoo.com/mrss/}"
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
MAX_FEED_BYTES = 2_000_000


class FeedError(ValueError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise FeedError("RSS_REDIRECT_BLOCKED")


RETRY_HTTP = {404, 408, 429, 500, 502, 503, 504}
CACHE_MAX_AGE_HOURS = 72


def fetch_channel(channel_id: str, *, opener=None, channels=None, attempts: int = 3,
                  sleep=time.sleep) -> bytes:
    """Only fixed YouTube feed URLs are requested; never visit video pages.

    YouTube's feed endpoint intermittently answers 404/5xx for valid channels, so
    transient HTTP and network errors are retried with a short backoff. Redirects,
    oversize bodies and disallowed channels are never retried.
    """
    allowed = CHANNELS if channels is None else channels
    if channel_id not in allowed:
        raise FeedError("CHANNEL_NOT_ALLOWED")
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    client = opener or build_opener(_NoRedirect())
    last = "RSS_NETWORK"
    for attempt in range(max(1, attempts)):
        if attempt:
            sleep(0.7 * attempt)
        request = Request(url, headers={"User-Agent": "marketing-agent-rss/1.0",
                                        "Accept": "application/atom+xml"})
        try:
            with client.open(request, timeout=10) as response:
                data = response.read(MAX_FEED_BYTES + 1)
        except FeedError:
            raise
        except HTTPError as exc:
            last = f"RSS_HTTP_{exc.code}"
            if exc.code not in RETRY_HTTP:
                break
            continue
        except (URLError, TimeoutError, OSError):
            last = "RSS_NETWORK"
            continue
        if len(data) > MAX_FEED_BYTES:
            raise FeedError("RSS_TOO_LARGE")
        return data
    raise FeedError(last)


def _cache_path(cache_dir: Path, channel_id: str) -> Path:
    return Path(cache_dir) / f"{channel_id}.xml"


def _write_cache(cache_dir: Path, channel_id: str, data: bytes) -> None:
    try:
        directory = Path(cache_dir)
        directory.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".rss-", suffix=".tmp", dir=directory)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temporary, _cache_path(directory, channel_id))
    except OSError:
        pass  # the cache is a convenience; listing still works without it


def _read_cache(cache_dir: Path, channel_id: str, now: datetime) -> tuple[bytes, float] | None:
    path = _cache_path(cache_dir, channel_id)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FEED_BYTES:
            return None
        age = (now.timestamp() - path.stat().st_mtime) / 3600
        if age > CACHE_MAX_AGE_HOURS:
            return None
        return path.read_bytes(), age
    except OSError:
        return None


def parse_channel(data: bytes, channel_id: str, *, channels=None) -> tuple[VideoCard, ...]:
    allowed = CHANNELS if channels is None else channels
    if channel_id not in allowed:
        raise FeedError("CHANNEL_NOT_ALLOWED")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise FeedError("RSS_INVALID_XML") from exc
    # YouTube's live feed uses the ID without "UC" at feed level, while each
    # entry carries the full channel ID. Accept only these two known forms.
    feed_channel_id = root.findtext(f"{YT}channelId")
    if root.tag != f"{ATOM}feed" or feed_channel_id not in (channel_id, channel_id[2:]):
        raise FeedError("RSS_CHANNEL_MISMATCH")
    cards = []
    seen = set()
    for entry in root.findall(f"{ATOM}entry"):
        video_id = entry.findtext(f"{YT}videoId", "")
        owner = entry.findtext(f"{YT}channelId", "")
        if owner != channel_id:
            raise FeedError("RSS_CHANNEL_MISMATCH")
        if not VIDEO_ID.fullmatch(video_id):
            raise FeedError("RSS_INVALID_VIDEO_ID")
        if video_id in seen:
            continue
        seen.add(video_id)
        title = entry.findtext(f"{ATOM}title", "").strip()
        published = entry.findtext(f"{ATOM}published", "").strip()
        if not title or not published:
            raise FeedError("RSS_MISSING_METADATA")
        group = entry.find(f"{MEDIA}group")
        thumb = group.find(f"{MEDIA}thumbnail") if group is not None else None
        description = group.findtext(f"{MEDIA}description", "").strip() if group is not None else ""
        thumbnail = thumb.attrib.get("url", "") if thumb is not None else ""
        # The UI is restricted to YouTube's image host. Construct a safe fallback.
        if not thumbnail.startswith(f"https://i.ytimg.com/vi/{video_id}/"):
            thumbnail = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        feed_name = root.findtext(f"{ATOM}title", "").strip()
        cards.append(VideoCard(video_id, channel_id, allowed[channel_id] or feed_name or channel_id,
                               title, published, thumbnail, description))
    return tuple(cards)


def list_videos(*, fetch=fetch_channel, channels=None, cache_dir: str | Path | None = None,
                now=None, fallback=None) -> VideoList:
    """List allowed channels. With cache_dir, a channel whose feed fails after retries
    falls back to its last good feed (<= 72h) for display only; posting still rechecks
    the live feed (recheck_video has no cache)."""
    allowed = CHANNELS if channels is None else channels
    videos = []
    errors = {}
    for channel_id, name in allowed.items():
        label = name or channel_id
        try:
            data = fetch_channel(channel_id, channels=allowed) if fetch is fetch_channel else fetch(channel_id)
            cards = parse_channel(data, channel_id, channels=allowed)
            if cache_dir is not None:
                _write_cache(Path(cache_dir), channel_id, data)
            videos.extend(cards)
        except (OSError, TimeoutError, ValueError, ET.ParseError) as exc:
            reason = str(exc) if isinstance(exc, FeedError) else type(exc).__name__
            cached = _read_cache(Path(cache_dir), channel_id, now or datetime.now(timezone.utc)) \
                if cache_dir is not None else None
            if cached is not None:
                try:
                    videos.extend(parse_channel(cached[0], channel_id, channels=allowed))
                    errors[label] = f"{reason} · 재시도 실패, {cached[1]:.0f}시간 전 받은 목록 표시"
                    continue
                except (ValueError, ET.ParseError):
                    pass
            # IMP-20: no feed and no cache — show approved-draft videos for display only.
            spare = tuple(fallback(channel_id)) if fallback is not None else ()
            if spare:
                videos.extend(spare)
                errors[label] = f"{reason} · 승인 초안 영상 {len(spare)}개만 표시"
                continue
            errors[label] = reason
    videos.sort(key=lambda card: card.published_at, reverse=True)
    return VideoList(tuple(videos), errors)


def recheck_video(video_id: str, channel_id: str, *, fetch=fetch_channel, channels=None) -> VideoCard | None:
    """Fail closed on feed errors or missing entries at posting time."""
    allowed = CHANNELS if channels is None else channels
    if channel_id not in allowed or not VIDEO_ID.fullmatch(video_id):
        return None
    try:
        data = fetch_channel(channel_id, channels=allowed) if fetch is fetch_channel else fetch(channel_id)
        return next((card for card in parse_channel(data, channel_id, channels=allowed)
                     if card.video_id == video_id), None)
    except (OSError, TimeoutError, ValueError, ET.ParseError):
        return None
