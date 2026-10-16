"""Keyless, fixed-channel YouTube RSS discovery and ownership rechecks."""

from __future__ import annotations

from dataclasses import dataclass
import re
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


def fetch_channel(channel_id: str, *, opener=None, channels=None) -> bytes:
    """Only fixed YouTube feed URLs are requested; never visit video pages."""
    allowed = CHANNELS if channels is None else channels
    if channel_id not in allowed:
        raise FeedError("CHANNEL_NOT_ALLOWED")
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    request = Request(url, headers={"User-Agent": "marketing-agent-rss/1.0", "Accept": "application/atom+xml"})
    client = opener or build_opener(_NoRedirect())
    with client.open(request, timeout=10) as response:
        data = response.read(MAX_FEED_BYTES + 1)
    if len(data) > MAX_FEED_BYTES:
        raise FeedError("RSS_TOO_LARGE")
    return data


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


def list_videos(*, fetch=fetch_channel, channels=None) -> VideoList:
    allowed = CHANNELS if channels is None else channels
    videos = []
    errors = {}
    for channel_id, name in allowed.items():
        try:
            data = fetch_channel(channel_id, channels=allowed) if fetch is fetch_channel else fetch(channel_id)
            videos.extend(parse_channel(data, channel_id, channels=allowed))
        except (OSError, TimeoutError, ValueError, ET.ParseError) as exc:
            errors[name or channel_id] = str(exc) if isinstance(exc, FeedError) else type(exc).__name__
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
