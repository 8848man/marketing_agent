"""Loopback dashboard and guarded HTTP boundary."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sys
from pathlib import Path
import re
import secrets
import shutil
import subprocess
from threading import RLock
import webbrowser
import xml.etree.ElementTree as ET

from .ai_client import create_ai_client, test_ai_connection
from .captions import VideoEvidence
from .dashboard_contracts import (BAD_REQUEST, FORBIDDEN, INTERNAL_ERROR,
                                  INVALID_VIDEO_ID, METHOD_NOT_ALLOWED,
                                  DashboardService, DraftPreview, PostStatus, VideoCard, VideoList)
from .dashboard_ui import FeedDraftService
from .dashboard_settings import DashboardSettings
from .dashboard_page import render_page as _page
from .drafts import approve as approve_draft, save_generated, _load_record
from .posting_service import CHANNEL_ID, PostingService
from .prompt_policy import DRAFT_RESPONSE_SCHEMA, build_draft_prompt
from .rss_feed import CHANNELS, fetch_channel, list_videos, parse_channel, recheck_video
from .storage import Store


HOST = "127.0.0.1"
MAX_CAPTURE_BYTES = 10 * 1024 * 1024
def _is_default_chrome_user_data_dir(path: Path) -> bool:
    """Whether Chrome 136+ will reject Playwright remote debugging for this root."""
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        candidates = [Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"]
        if local_app_data:
            candidates.append(Path(local_app_data) / "Google" / "Chrome" / "User Data")
    elif sys.platform == "darwin":
        candidates = [Path.home() / "Library" / "Application Support" / "Google" / "Chrome"]
    else:
        candidates = [Path.home() / ".config" / "google-chrome"]
    try:
        resolved = path.expanduser().resolve(strict=False)
        return any(resolved == candidate.expanduser().resolve(strict=False) for candidate in candidates)
    except OSError:
        return False


def _installed_chrome() -> Path | None:
    """Find installed Chrome without inspecting browser profile data."""
    candidates: list[Path] = []
    if os.name == "nt":
        for base in (os.getenv("PROGRAMFILES"), os.getenv("PROGRAMFILES(X86)"),
                     str(Path.home() / "AppData" / "Local")):
            if base:
                candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    elif sys.platform == "darwin":
        candidates.extend((Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                           Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    else:
        for name in ("google-chrome", "google-chrome-stable"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
    return next((candidate for candidate in candidates if candidate.is_file()), None)


GOOGLE_LOGIN_URL = ("https://accounts.google.com/AccountChooser?"
                    "continue=https%3A%2F%2Fmyaccount.google.com%2F&hl=ko")


def _open_login_window(root: Path) -> subprocess.Popen:
    chrome = _installed_chrome()
    if chrome is None:
        raise ValueError("CHROME_NOT_FOUND")
    try:
        return subprocess.Popen([str(chrome), f"--user-data-dir={root}",
                          "--profile-directory=Default", "--no-first-run",
                          "--no-default-browser-check", "--new-window", GOOGLE_LOGIN_URL],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
    except OSError as exc:
        raise ValueError("BROWSER_LAUNCH_FAILED") from exc



def check_channel_connection(channel_id: str, *, fetch=fetch_channel) -> dict[str, object]:
    """Check a single fixed-host RSS feed; this never proves channel ownership."""
    if not isinstance(channel_id, str) or not CHANNEL_ID.fullmatch(channel_id):
        raise ValueError("SETTINGS_CHANNEL_ID_INVALID")
    allowed = {channel_id: ""}
    data = fetch(channel_id, channels=allowed)
    cards = parse_channel(data, channel_id, channels=allowed)
    try:
        channel_name = ET.fromstring(data).findtext(
            "{http://www.w3.org/2005/Atom}title", "").strip()
    except ET.ParseError:
        channel_name = ""
    return {"channel_id": channel_id, "channel_name": channel_name,
            "connected": True, "video_count": len(cards)}




class DemoService:
    """Isolated local walkthrough. No YouTube, posting database, or poster calls."""

    VIDEO_ID = "DEMOvideo01"
    CARD = VideoCard(VIDEO_ID, "DEMO_ONLY", "로컬 연습", "예시 영상 (실제 YouTube 영상 아님)",
                     "연습 자료", "")
    SUMMARY = "연락이 늦어질 때 생기는 불안을 다루는 가상 예시"
    COMMENT = ("연락을 기다리는 장면이 마음에 남네요. 관계가 어디로 갈지 궁금할 때 "
               "운명원 연애 사주 이야기도 한번 살펴보고 싶어져요.")

    def list_videos(self) -> VideoList:
        return VideoList((self.CARD,))

    def select_video(self, video_id: str) -> DraftPreview:
        if video_id != self.VIDEO_ID:
            return DraftPreview(video_id, reason_code="VIDEO_NOT_FOUND")
        return DraftPreview(video_id, self.SUMMARY, self.COMMENT, True, "")

    def post_video(self, video_id: str, *, keep_window_open: bool = False) -> PostStatus:
        if video_id != self.VIDEO_ID:
            return PostStatus("blocked", "VIDEO_NOT_FOUND")
        return PostStatus("simulated", "DEMO_NO_POST",
                          "연습 완료: YouTube 요청, Chrome 실행, DB 예약, 댓글 게시는 수행하지 않았습니다.")
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
CAPTURE_NAME = re.compile(r"[A-Za-z0-9_-]{11}-[0-9]+\.png\Z")


class ConfiguredPostingService(PostingService):
    """Keep posting disabled until a specific local Chrome profile is set."""

    def __init__(self, *args, settings: DashboardSettings | None = None,
                 evidence_provider: VideoEvidence | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.settings = settings
        self.evidence_provider = evidence_provider or VideoEvidence(
            key_provider=settings.youtube_api_key if settings is not None else None)
        self._settings_lock = RLock()
        self._posting_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chrome-post")
        self._login_window_process: subprocess.Popen | None = None
        self._login_window_root: Path | None = None
        self._verified_emails: dict[str, tuple[str, str]] = {}
        self._account_states: dict[str, str] = {}
        if settings is not None:
            selected = settings.profile_public()
            self.profile = str(selected["label"])
            root, directory = str(selected["user_data_dir"]), str(selected["profile_directory"])
            if root and directory and self.poster is not None:
                self.poster.user_data_dir = Path(root)
                self.poster.profile_directory = directory
        if settings is not None and (set(settings.channels()) &
                                     {card.channel_id for card in self.test_videos.values()}):
            raise ValueError("SETTINGS_TEST_CHANNEL_CONFLICT")

    def settings_yaml(self) -> str:
        if self.settings is None:
            raise ValueError("SETTINGS_UNAVAILABLE")
        return self.settings.yaml_text()

    def channel_ids(self) -> list[str]:
        if self.settings is None:
            raise ValueError("SETTINGS_UNAVAILABLE")
        return self.settings.channel_ids()

    def channel_entries(self) -> list[dict[str, str]]:
        if self.settings is None:
            raise ValueError("SETTINGS_UNAVAILABLE")
        return self.settings.channel_entries()

    def ai_public(self) -> dict[str, object]:
        if self.settings is None:
            raise ValueError("AI_SETTINGS_UNAVAILABLE")
        return self.settings.ai_public()

    def profile_public(self) -> dict[str, object]:
        if self.settings is None:
            raise ValueError("PROFILE_SETTINGS_UNAVAILABLE")
        return self.settings.profile_public()

    def profile_options_public(self) -> dict[str, object]:
        if self.settings is None:
            raise ValueError("PROFILE_SETTINGS_UNAVAILABLE")
        with self._settings_lock:
            result = self.settings.profile_options_public()
            window_open = (self._login_window_process is not None and
                           self._login_window_process.poll() is None)
            for option in result["options"]:
                verified = self._verified_emails.get(option["label"])
                option["verified_email"] = verified[0] if verified else ""
                option["verified_at"] = verified[1] if verified else ""
                option["account_state"] = self._account_states.get(option["label"], "UNKNOWN")
                option["login_window_open"] = bool(window_open and
                    self._login_window_root == self.settings.app_profile_root(option["label"]))
            return result

    def verify_profile_email(self, label: str, video_id: str = "") -> dict[str, object]:
        return self._posting_worker.submit(self._verify_profile_email_on_worker, label, video_id).result()

    def _verify_profile_email_on_worker(self, label: str, video_id: str) -> dict[str, object]:
        with self._settings_lock:
            if self.settings is None or self.poster is None:
                raise ValueError("PROFILE_SETTINGS_UNAVAILABLE")
            self._verified_emails.pop(label, None)
            self._account_states[label] = "UNKNOWN"
            root = self.settings.app_profile_root(label)
            if (self._login_window_process is not None and
                    self._login_window_root == root and
                    self._login_window_process.poll() is None):
                raise ValueError("PROFILE_LOCKED")
            if video_id:
                if not VIDEO_ID.fullmatch(video_id) or video_id not in self._videos:
                    raise ValueError("PROFILE_EMAIL_VIDEO_INVALID")
                cards = (self._videos[video_id],)
            else:
                cards = tuple(self._videos.values())
                if not cards:
                    try:
                        cards = tuple(self.feed_loader().videos)
                    except Exception:
                        cards = ()
            card = next((item for item in cards if VIDEO_ID.fullmatch(item.video_id) and
                        (item.channel_id in self.settings.channels() or
                         (item.video_id in self.test_videos and self._test_ownership(item)))), None)
            if card is None and not video_id and self.db_path.is_file():
                with Store(self.db_path) as store:
                    posted = store.latest_posted_video_for_channels(set(self.settings.channels()))
                if posted and VIDEO_ID.fullmatch(posted["video_id"]):
                    card = VideoCard(posted["video_id"], posted["channel_id"], "",
                                     posted["title"], "", "")
            if card is None:
                raise ValueError("PROFILE_EMAIL_VIDEO_INVALID" if video_id else
                                 "PROFILE_EMAIL_VIDEO_UNAVAILABLE")
            option = next(item for item in self.settings.profile_options_public()["options"]
                          if item["label"] == label)
            if not option["configured"] or not option["connected"]:
                raise ValueError("PROFILE_NOT_CONFIGURED")
            self.poster.user_data_dir = root
            self.poster.profile_directory = "Default"
            self.profile = label
            reason = self._profile_reason()
            if reason:
                raise ValueError(reason)
            try:
                email = self.poster.inspect_account_email(card.video_id)
            except ValueError as exc:
                if str(exc) == "PROFILE_SIGNED_OUT":
                    self._account_states[label] = "SIGNED_OUT"
                else:
                    self._account_states[label] = "UNKNOWN"
                raise
            self._verified_emails[label] = (email, datetime.now(timezone.utc).isoformat())
            self._account_states[label] = "SIGNED_IN"
            return self.profile_options_public()

    def save_profile_email(self, label: str, email: str) -> dict[str, object]:
        if self.settings is None:
            raise ValueError("PROFILE_SETTINGS_UNAVAILABLE")
        return self.settings.save_profile_email(label, email)

    def save_profile(self, label: str) -> dict[str, object]:
        if self.settings is None or self.poster is None:
            raise ValueError("PROFILE_SETTINGS_UNAVAILABLE")
        with self._settings_lock:
            result = self.settings.save_profile(label)
            self.poster.user_data_dir = Path(result["user_data_dir"])
            self.poster.profile_directory = str(result["profile_directory"])
            self.profile = str(result["label"])
            self._selected.clear()
            return result

    def add_profile(self, label: str) -> dict[str, object]:
        if self.settings is None or self.poster is None:
            raise ValueError("PROFILE_SETTINGS_UNAVAILABLE")
        with self._settings_lock:
            created = self.settings.add_profile(label)
            root = self.settings.app_profile_root(str(created["label"]))
            root.mkdir(parents=True, exist_ok=False)
            (root / "Default").mkdir()
            self.settings.connect_profile(str(created["label"]))
            return created

    def open_app_profile(self, label: str = "유튜브1") -> dict[str, object]:
        """Open one app-owned profile for manual login; never inspect its files."""
        if self.settings is None or self.poster is None:
            raise ValueError("PROFILE_SETTINGS_UNAVAILABLE")
        with self._settings_lock:
            self._verified_emails.pop(label, None)
            self._account_states[label] = "UNKNOWN"
            root = self.settings.app_profile_root(label)
            if (self._login_window_process is not None and
                    self._login_window_process.poll() is None):
                raise ValueError("PROFILE_LOCKED")
            root.mkdir(parents=True, exist_ok=True)
            profile = root / "Default"
            if not profile.resolve(strict=False).is_relative_to(root.resolve()):
                raise ValueError("PROFILE_PATH_UNSAFE")
            profile.mkdir(exist_ok=True)
            process = _open_login_window(root)
            saved = self.settings.connect_profile(label)
            self._selected.clear()
            if self._videos:
                candidates = [item["label"] for item in self.settings.profile_options_public()["options"]
                              if item["configured"] and item["connected"]]
                with Store(self.db_path) as store:
                    store.assign_dashboard_videos(self._videos.values(), candidates, datetime.now(timezone.utc))
            self._login_window_process = process
            self._login_window_root = root
            return {**saved, "login_window_opened": True,
                    "states": self.video_states() if self._videos else {}}

    def save_ai(self, provider: str, model: str, api_key: str,
                *, clear_key: bool = False) -> dict[str, object]:
        if self.settings is None:
            raise ValueError("AI_SETTINGS_UNAVAILABLE")
        return self.settings.save_ai(provider, model, api_key, clear_key=clear_key)

    def save_youtube_api_key(self, key: str) -> dict[str, bool]:
        if self.settings is None:
            raise ValueError("AI_SETTINGS_UNAVAILABLE")
        return self.settings.save_youtube_api_key(key)

    def test_ai(self) -> dict[str, object]:
        if self.settings is None:
            raise ValueError("AI_SETTINGS_UNAVAILABLE")
        provider, model, key = self.settings.ai_credentials()
        if not key:
            raise ValueError("AI_KEY_MISSING")
        test_ai_connection(provider, model, key)
        return {"connected": True, "provider": provider, "model": model}

    def generate_draft(self, video_id: str) -> dict[str, object]:
        """Call the selected provider only after an explicit local UI request."""
        if self.settings is None:
            raise ValueError("AI_SETTINGS_UNAVAILABLE")
        with self._settings_lock:
            card = self._videos.get(video_id)
            if card is None:
                raise ValueError("VIDEO_NOT_FOUND")
            profile = self._assigned_profile(video_id)
            provider, model, key = self.settings.ai_credentials()
            if not key:
                raise ValueError("AI_KEY_MISSING")
            evidence = self.evidence_provider.collect(card)
            prompt = build_draft_prompt(evidence)
            result = create_ai_client(provider, model, key).complete_json(
                prompt.system, prompt.user,
                response_schema=DRAFT_RESPONSE_SCHEMA,
            )
            record = save_generated(card, result, self.drafts_dir, source_text=evidence.text,
                                    evidence_sources=evidence.sources, profile=profile)
            return {key: record[key] for key in ("video_id", "worry_summary", "cited_detail", "comment", "evidence_sources", "source_text")} | {"evidence_notice": evidence.notice}

    def approve_draft(self, video_id: str, values: dict) -> dict[str, object]:
        with self._settings_lock:
            card = self._videos.get(video_id)
            if card is None:
                raise ValueError("VIDEO_NOT_FOUND")
            record = approve_draft(card, values, self.drafts_dir)
            return {"video_id": record["video_id"], "can_post": True,
                    "worry_summary": record["worry_summary"], "cited_detail": record["cited_detail"],
                    "comment": record["comment"]}

    def save_channel_ids(self, channels: list[str]) -> list[str]:
        if self.settings is None:
            raise ValueError("SETTINGS_UNAVAILABLE")
        with self._settings_lock:
            result = self.settings.save_channels(
                channels, forbidden_channels={card.channel_id for card in self.test_videos.values()})
            self._videos.clear()
            self._selected.clear()
            return result

    def save_channel_entries(self, entries: list[dict[str, str]]) -> list[dict[str, str]]:
        if self.settings is None:
            raise ValueError("SETTINGS_UNAVAILABLE")
        with self._settings_lock:
            result = self.settings.save_channel_entries(
                entries, forbidden_channels={card.channel_id for card in self.test_videos.values()})
            self._videos.clear()
            self._selected.clear()
            return result

    def save_settings_yaml(self, source: str) -> str:
        if self.settings is None:
            raise ValueError("SETTINGS_UNAVAILABLE")
        with self._settings_lock:
            result = self.settings.save_yaml(
                source, forbidden_channels={card.channel_id for card in self.test_videos.values()})
            self._videos.clear()
            self._selected.clear()
            return result

    def list_videos(self) -> VideoList:
        with self._settings_lock:
            result = super().list_videos()
            if self.settings is not None:
                candidates = [item["label"] for item in self.settings.profile_options_public()["options"]
                              if item["configured"] and item["connected"]]
                with Store(self.db_path) as store:
                    store.assign_dashboard_videos(result.videos, candidates, datetime.now(timezone.utc))
            return result

    def video_states(self) -> dict[str, dict[str, str]]:
        states = {}
        with self._settings_lock, Store(self.db_path) as store:
            for video_id in self._videos:
                assignment = store.dashboard_assignment(video_id)
                profile = assignment["profile"] if assignment else None
                posted = store.dashboard_post_status(video_id)
                if posted == "POSTED" and profile:
                    state = "posted"
                elif posted == "POSTED":
                    state = "review"
                elif posted in {"RESERVED", "SUBMITTING", "OUTCOME_UNKNOWN", "POST_OUTCOME_UNKNOWN", "POST_PENDING"}:
                    state = "review"
                elif not profile:
                    state = "unassigned"
                else:
                    try:
                        draft = _load_record(self.drafts_dir, video_id) or {}
                    except (OSError, ValueError, TypeError):
                        draft = {}
                    state = "ai_generated" if draft.get("generated_profile") == profile else "not_started"
                states[video_id] = {"profile": profile or "", "state": state}
        return states

    def _assigned_profile(self, video_id: str) -> str:
        with Store(self.db_path) as store:
            row = store.dashboard_assignment(video_id)
        profile = row["profile"] if row else None
        if self.settings is None or profile not in {
                item["label"] for item in self.settings.profile_options_public()["options"]}:
            raise ValueError("PROFILE_UNASSIGNED")
        return profile

    def _use_assigned_profile(self, video_id: str) -> None:
        if self.settings is None or self.poster is None:
            raise ValueError("PROFILE_NOT_CONFIGURED")
        label = self._assigned_profile(video_id)
        root = self.settings.app_profile_root(label)
        saved = self.settings.profile_options_public()["options"]
        option = next(item for item in saved if item["label"] == label)
        if not option["configured"] or not option["connected"]:
            raise ValueError("PROFILE_NOT_CONFIGURED")
        self.poster.user_data_dir = root
        self.poster.profile_directory = "Default"
        self.profile = label

    def _profile_reason(self) -> str:
        poster = self.poster
        if poster is None or not getattr(poster, "profile_directory", ""):
            return "PROFILE_NOT_CONFIGURED"
        selected = self.profile if self.settings is not None else None
        if (selected is not None and
                (poster.user_data_dir.resolve(strict=False) !=
                 self.settings.app_profile_root(str(selected)).resolve(strict=False)
                 or poster.profile_directory != "Default")):
            return "PROFILE_NOT_CONFIGURED"
        if not poster.PROFILE_NAME.fullmatch(poster.profile_directory):
            return "PROFILE_NAME_INVALID"
        if not poster.user_data_dir.is_dir():
            return "USER_DATA_DIR_MISSING"
        if not (poster.user_data_dir / poster.profile_directory).is_dir():
            return "PROFILE_DIRECTORY_MISSING"
        if _is_default_chrome_user_data_dir(poster.user_data_dir):
            return "DEFAULT_CHROME_USER_DATA_DIR_UNSUPPORTED"
        process = self._login_window_process
        if (process is not None and self._login_window_root is not None
                and poster.user_data_dir.resolve(strict=False) == self._login_window_root
                and process.poll() is None):
            return "PROFILE_LOCKED"
        return ""

    def select_video(self, video_id: str) -> DraftPreview:
        with self._settings_lock:
            result = super().select_video(video_id)
            if video_id in self._videos:
                try:
                    self._assigned_profile(video_id)
                    if result.can_post:
                        self._use_assigned_profile(video_id)
                except ValueError as exc:
                    return replace(result, can_post=False, reason_code=str(exc))
            reason = self._profile_reason() if result.can_post else ""
            return replace(result, can_post=False, reason_code=reason) if result.can_post and reason else result

    def post_video(self, video_id: str, *, keep_window_open: bool = False) -> PostStatus:
        return self._posting_worker.submit(self._post_video_on_worker, video_id, keep_window_open).result()

    def _post_video_on_worker(self, video_id: str, keep_window_open: bool) -> PostStatus:
        with self._settings_lock:
            if video_id in self._videos:
                try:
                    self._use_assigned_profile(video_id)
                except ValueError as exc:
                    return PostStatus("blocked", str(exc))
            if self.poster is not None:
                self.poster.events.clear()
                if self.poster.held_window_open():
                    return PostStatus("blocked", "PROFILE_LOCKED", "이전 댓글 창을 닫은 뒤 다시 시도하세요.")
                self.poster.keep_window_open = keep_window_open
            reason = self._profile_reason()
            if reason:
                return PostStatus("blocked", reason)
            return super().post_video(video_id)


def _capture_url(path: str, capture_dir: Path | None) -> str:
    if not path or capture_dir is None:
        return ""
    candidate = Path(path)
    try:
        if (CAPTURE_NAME.fullmatch(candidate.name) and not capture_dir.is_symlink()
                and not candidate.is_symlink() and candidate.is_file()
                and candidate.stat().st_size <= MAX_CAPTURE_BYTES
                and candidate.resolve().parent == capture_dir.resolve()):
            return f"/captures/{candidate.name}"
    except OSError:
        pass
    return ""


def create_server(service: DashboardService | None = None, *, port: int = 0,
                  capture_dir: str | Path | None = None) -> ThreadingHTTPServer:
    """Bind to loopback and call the poster only after request checks."""
    service = service if service is not None else FeedDraftService()
    token = secrets.token_urlsafe(32)
    captures = Path(capture_dir) if capture_dir is not None else None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def _headers(self, status: int, content_type: str, size: int) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' https://i.ytimg.com; script-src 'unsafe-inline'; style-src 'unsafe-inline'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            self.end_headers()

        def _json(self, status: int, payload: object) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._headers(status, "application/json; charset=utf-8", len(body))
            self.wfile.write(body)

        def _reject(self, status: int, code: str) -> None:
            self._json(status, {"reason_code": code})

        def _reject_early_post(self, status: int, code: str) -> None:
            """Consume a small rejected POST body so Windows keeps the 403 response."""
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                size = 0
            if 0 < size <= 8192:
                previous_timeout = self.connection.gettimeout()
                try:
                    self.connection.settimeout(1)
                    self.rfile.read(size)
                except (OSError, TimeoutError):
                    pass
                finally:
                    self.connection.settimeout(previous_timeout)
            self._reject(status, code)

        def _host_ok(self) -> bool:
            return self.headers.get("Host") == f"{HOST}:{self.server.server_port}"

        def _session_ok(self) -> bool:
            return secrets.compare_digest(self.headers.get("X-Session-Token", ""), token)

        def do_GET(self) -> None:
            if not self._host_ok():
                return self._reject(403, FORBIDDEN)
            if self.path == "/":
                body = _page(token, demo=isinstance(service, DemoService))
                self._headers(200, "text/html; charset=utf-8", len(body))
                return self.wfile.write(body)
            if self.path == "/api/videos":
                if not self._session_ok():
                    return self._reject(403, FORBIDDEN)
                try:
                    result = asdict(service.list_videos())
                    if hasattr(service, "video_states"):
                        result["states"] = service.video_states()
                    return self._json(200, result)
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/settings" and hasattr(service, "settings_yaml"):
                if not secrets.compare_digest(self.headers.get("X-Session-Token", ""), token):
                    return self._reject(403, FORBIDDEN)
                try:
                    return self._json(200, {"yaml": service.settings_yaml()})
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/channels" and hasattr(service, "channel_ids"):
                if not secrets.compare_digest(self.headers.get("X-Session-Token", ""), token):
                    return self._reject(403, FORBIDDEN)
                try:
                    entries = service.channel_entries() if hasattr(service, "channel_entries") else [
                        {"channel_name": channel_id, "channel_id": channel_id}
                        for channel_id in service.channel_ids()]
                    return self._json(200, {"channels": service.channel_ids(), "entries": entries})
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/ai" and hasattr(service, "ai_public"):
                if not secrets.compare_digest(self.headers.get("X-Session-Token", ""), token):
                    return self._reject(403, FORBIDDEN)
                try:
                    return self._json(200, service.ai_public())
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/profile" and hasattr(service, "profile_public"):
                if not secrets.compare_digest(self.headers.get("X-Session-Token", ""), token):
                    return self._reject(403, FORBIDDEN)
                try:
                    return self._json(200, service.profile_public())
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/profile-options" and hasattr(service, "profile_options_public"):
                if not secrets.compare_digest(self.headers.get("X-Session-Token", ""), token):
                    return self._reject(403, FORBIDDEN)
                try:
                    return self._json(200, service.profile_options_public())
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            match = re.fullmatch(r"/api/videos/([A-Za-z0-9_-]{11})/draft", self.path)
            if match:
                if not self._session_ok():
                    return self._reject(403, FORBIDDEN)
                try:
                    return self._json(200, asdict(service.select_video(match.group(1))))
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/progress":
                if not secrets.compare_digest(self.headers.get("X-Session-Token", ""), token):
                    return self._reject(403, FORBIDDEN)
                poster = getattr(service, "poster", None)
                events = getattr(poster, "events", ())
                return self._json(200, {"events": [dict(stage=item.stage,
                    reason_code=item.reason_code,
                    screenshot_url=_capture_url(item.screenshot_path, captures))
                    for item in events[-20:]]})
            capture = re.fullmatch(r"/captures/([A-Za-z0-9_-]{11}-[0-9]+\.png)", self.path)
            if capture and captures is not None:
                if not self._session_ok():
                    return self._reject(403, FORBIDDEN)
                path = captures / capture.group(1)
                if _capture_url(str(path), captures):
                    try:
                        with path.open("rb") as stream:
                            body = stream.read(MAX_CAPTURE_BYTES + 1)
                    except OSError:
                        return self._reject(404, BAD_REQUEST)
                    if len(body) > MAX_CAPTURE_BYTES:
                        return self._reject(404, BAD_REQUEST)
                    self._headers(200, "image/png", len(body))
                    return self.wfile.write(body)
            if self.path == "/api/post":
                return self._reject(405, METHOD_NOT_ALLOWED)
            return self._reject(404, BAD_REQUEST)

        def do_POST(self) -> None:
            if not self._host_ok():
                return self._reject_early_post(403, FORBIDDEN)
            if self.path not in {"/api/post", "/api/settings", "/api/channels",
                                 "/api/channels/test", "/api/ai", "/api/ai/test", "/api/youtube-key",
                                 "/api/profile", "/api/profile/add", "/api/profile/email", "/api/profile/verify-email", "/api/profile/setup", "/api/drafts/generate", "/api/drafts/approve"}:
                return self._reject(404, BAD_REQUEST)
            if self.headers.get("Origin") != f"http://{HOST}:{self.server.server_port}":
                return self._reject_early_post(403, FORBIDDEN)
            if not secrets.compare_digest(self.headers.get("X-Session-Token", ""), token):
                return self._reject_early_post(403, FORBIDDEN)
            if self.headers.get("Content-Type") != "application/json":
                return self._reject_early_post(400, BAD_REQUEST)
            try:
                size = int(self.headers.get("Content-Length", ""))
                if not 0 < size <= (8192 if self.path in {"/api/settings", "/api/channels", "/api/ai"} else 4096):
                    raise ValueError
                data = json.loads(self.rfile.read(size))
                if self.path == "/api/ai":
                    if (not isinstance(data, dict)
                            or set(data) != {"provider", "model", "api_key", "clear_key"}
                            or any(not isinstance(data[key], str)
                                   for key in ("provider", "model", "api_key"))
                            or not isinstance(data["clear_key"], bool)):
                        raise ValueError
                elif self.path == "/api/profile":
                    if not isinstance(data, dict) or set(data) != {"label"} or not isinstance(data["label"], str):
                        raise ValueError
                elif self.path == "/api/profile/add":
                    if not isinstance(data, dict) or set(data) != {"label"} or not isinstance(data["label"], str):
                        raise ValueError
                elif self.path == "/api/profile/email":
                    if (not isinstance(data, dict) or set(data) != {"label", "email"}
                            or not isinstance(data["label"], str) or not isinstance(data["email"], str)):
                        raise ValueError
                elif self.path == "/api/profile/verify-email":
                    if (not isinstance(data, dict) or set(data) != {"label", "video_id"}
                            or not isinstance(data["label"], str)
                            or not isinstance(data["video_id"], str)):
                        raise ValueError
                elif self.path == "/api/post":
                    if (not isinstance(data, dict) or set(data) not in ({"video_id"}, {"video_id", "keep_window_open"})
                            or not isinstance(data.get("video_id"), str)
                            or ("keep_window_open" in data and not isinstance(data["keep_window_open"], bool))):
                        raise ValueError
                elif self.path == "/api/profile/setup":
                    if (not isinstance(data, dict) or set(data) != {"label"}
                            or not isinstance(data.get("label"), str)):
                        raise ValueError
                elif self.path == "/api/ai/test":
                    if data != {}:
                        raise ValueError
                elif self.path == "/api/youtube-key":
                    if (not isinstance(data, dict) or set(data) != {"api_key"}
                            or not isinstance(data["api_key"], str)):
                        raise ValueError
                elif self.path == "/api/channels/test":
                    if (not isinstance(data, dict) or set(data) not in ({"channel_id"}, {"channel_name", "channel_id"})
                            or not isinstance(data["channel_id"], str)
                            or ("channel_name" in data and not isinstance(data["channel_name"], str))):
                        raise ValueError
                elif self.path == "/api/channels":
                    if not isinstance(data, dict) or set(data) not in ({"channels"}, {"entries"}):
                        raise ValueError
                    value = data.get("entries", data.get("channels"))
                    if not isinstance(value, list):
                        raise ValueError
                elif self.path == "/api/drafts/approve":
                    if (not isinstance(data, dict) or set(data) != {"video_id", "draft"}
                            or not isinstance(data["video_id"], str) or not isinstance(data["draft"], dict)
                            or set(data["draft"]) != {"worry_summary", "cited_detail", "comment", "reviewer"}
                            or any(not isinstance(value, str) for value in data["draft"].values())):
                        raise ValueError
                else:
                    field = {"/api/settings": "yaml", "/api/channels": "channels",
                             "/api/post": "video_id",
                             "/api/drafts/generate": "video_id"}[self.path]
                    if (not isinstance(data, dict) or set(data) != {field}
                            or not isinstance(data[field], list if field == "channels" else str)):
                        raise ValueError
            except (ValueError, UnicodeDecodeError):
                return self._reject(400, BAD_REQUEST)
            if self.path == "/api/settings":
                if not hasattr(service, "save_settings_yaml"):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, {"yaml": service.save_settings_yaml(data["yaml"])})
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(400, reason if reason.startswith("SETTINGS_") else BAD_REQUEST)
                except OSError:
                    return self._reject(503, "SETTINGS_WRITE_FAILED")
            if self.path == "/api/channels":
                if not hasattr(service, "save_channel_ids"):
                    return self._reject(404, BAD_REQUEST)
                try:
                    if "entries" in data and hasattr(service, "save_channel_entries"):
                        entries = service.save_channel_entries(data["entries"])
                        return self._json(200, {"channels": [item["channel_id"] for item in entries],
                                                "entries": entries})
                    channels = service.save_channel_ids(data["channels"])
                    entries = service.channel_entries() if hasattr(service, "channel_entries") else [
                        {"channel_name": channel_id, "channel_id": channel_id} for channel_id in channels]
                    return self._json(200, {"channels": channels, "entries": entries})
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(400, reason if reason.startswith("SETTINGS_") else BAD_REQUEST)
                except OSError:
                    return self._reject(503, "SETTINGS_WRITE_FAILED")
            if self.path == "/api/profile/setup":
                if not hasattr(service, "open_app_profile"):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.open_app_profile(data["label"]))
                except ValueError as exc:
                    reason = str(exc)
                    if reason == "PROFILE_SETTINGS_INVALID":
                        return self._reject(400, reason)
                    return self._reject(503, reason if reason in {"CHROME_NOT_FOUND", "BROWSER_LAUNCH_FAILED", "PROFILE_PATH_UNSAFE", "PROFILE_LOCKED"} else "PROFILE_SETUP_FAILED")
                except OSError:
                    return self._reject(503, "PROFILE_SETUP_FAILED")
            if self.path == "/api/profile/add":
                if not hasattr(service, "add_profile"):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.add_profile(data["label"]))
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(400, reason if reason.startswith("PROFILE_") else BAD_REQUEST)
                except OSError:
                    return self._reject(503, "PROFILE_SETUP_FAILED")
            if self.path == "/api/profile":
                if not hasattr(service, "save_profile"):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.save_profile(data["label"]))
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(400, reason if reason.startswith("PROFILE_") or reason.startswith("USER_") else BAD_REQUEST)
                except OSError:
                    return self._reject(503, "SETTINGS_WRITE_FAILED")
            if self.path == "/api/profile/email":
                if not hasattr(service, "save_profile_email"):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.save_profile_email(data["label"], data["email"]))
                except ValueError as exc:
                    return self._reject(400, str(exc) if str(exc).startswith("PROFILE_") else BAD_REQUEST)
                except OSError:
                    return self._reject(503, "PROFILE_EMAIL_WRITE_FAILED")
            if self.path == "/api/profile/verify-email":
                if not hasattr(service, "verify_profile_email"):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.verify_profile_email(data["label"], data["video_id"]))
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(400 if reason in {"PROFILE_EMAIL_VIDEO_INVALID", "PROFILE_SETTINGS_INVALID"}
                                        else 409 if reason == "PROFILE_SIGNED_OUT" else 503,
                                        reason if reason.startswith(("PROFILE_", "BROWSER_", "USER_")) else "PROFILE_EMAIL_CHECK_FAILED")
                except Exception as exc:
                    reason = getattr(exc, "code", "PROFILE_EMAIL_CHECK_FAILED")
                    return self._reject(503, reason)
            if self.path == "/api/channels/test":
                if not hasattr(service, "channel_ids"):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, check_channel_connection(data["channel_id"]))
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(400 if reason == "SETTINGS_CHANNEL_ID_INVALID" else 503,
                                        reason if reason.isupper() else "CHANNEL_TEST_FAILED")
                except (OSError, TimeoutError):
                    return self._reject(503, "CHANNEL_TEST_NETWORK_FAILED")
            if self.path == "/api/ai":
                if not hasattr(service, "save_ai"):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.save_ai(
                        data["provider"], data["model"], data["api_key"],
                        clear_key=data["clear_key"]))
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(400, reason if reason.startswith("AI_") else BAD_REQUEST)
                except OSError:
                    return self._reject(503, "SETTINGS_WRITE_FAILED")
            if self.path == "/api/youtube-key":
                if not hasattr(service, "save_youtube_api_key"):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.save_youtube_api_key(data["api_key"]))
                except (KeyError, ValueError) as exc:
                    return self._reject(400, str(exc) if str(exc) == "YOUTUBE_KEY_INVALID" else BAD_REQUEST)
                except OSError:
                    return self._reject(503, "SETTINGS_WRITE_FAILED")
            if self.path == "/api/ai/test":
                if not hasattr(service, "test_ai"):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.test_ai())
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(409 if reason == "AI_KEY_MISSING" else 503,
                                        reason if reason.startswith("AI_") else "AI_TEST_FAILED")
                except Exception:
                    return self._reject(503, "AI_TEST_FAILED")
            if self.path == "/api/drafts/generate":
                if not hasattr(service, "generate_draft"):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.generate_draft(data["video_id"]))
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(409 if reason == "AI_KEY_MISSING" else 503,
                                        reason if reason.isupper() else "DRAFT_GENERATION_FAILED")
                except OSError:
                    return self._reject(503, "DRAFT_WRITE_FAILED")
            if self.path == "/api/drafts/approve":
                if not hasattr(service, "approve_draft"):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.approve_draft(data["video_id"], data["draft"]))
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(400 if reason in {"DRAFT_APPROVAL_INVALID", "HUMAN_REVIEW_MISSING"}
                                        else 409, reason if reason.isupper() else "DRAFT_APPROVAL_FAILED")
                except OSError:
                    return self._reject(503, "DRAFT_WRITE_FAILED")
            video_id = data["video_id"]
            if not VIDEO_ID.fullmatch(video_id):
                return self._reject(400, INVALID_VIDEO_ID)
            try:
                result = (service.post_video(video_id, keep_window_open=data["keep_window_open"])
                          if "keep_window_open" in data else service.post_video(video_id))
                result = replace(result, screenshot_url=_capture_url(result.screenshot_url, captures))
                return self._json(200 if result.state == "posted" else 409, asdict(result))
            except Exception:
                return self._reject(503, INTERNAL_ERROR)

        def do_PUT(self) -> None:
            self._reject(405, METHOD_NOT_ALLOWED)

        do_PATCH = do_PUT
        do_DELETE = do_PUT

    return ThreadingHTTPServer((HOST, port), Handler)


def run_dashboard(*, port: int = 8765, service: DashboardService | None = None,
                  capture_dir: str | Path | None = None,
                  open_browser: bool = True) -> None:
    with create_server(service, port=port, capture_dir=capture_dir) as server:
        url = f"http://{HOST}:{server.server_port}/"
        print(f"Dashboard: {url}")
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Dashboard stopped.")

