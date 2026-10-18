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

from .ai_client import test_ai_connection
from .captions import EvidenceResult, VideoEvidence
from .dashboard_contracts import (
    AIReadService, AITestService, AIWriteService, BAD_REQUEST, ChannelEntryReadService,
    BrandReadService, BrandWriteService,
    CommentGenerationReadService, CommentGenerationWriteService,
    ChannelEntryWriteService, ChannelReadService, ChannelWriteService,
    DashboardService, DraftApprovalService, DraftGenerationService, DraftPreview, DraftRefineService,
    HistoryService, SetupStatusService,
    FORBIDDEN, INTERNAL_ERROR, INVALID_VIDEO_ID, METHOD_NOT_ALLOWED,
    PostStatus, ProfileAddService, ProfileMemoService, ProfileOpenService,
    ProfileOptionsService, ProfileReadService, ProfileVerifyService,
    ProfileWriteService, SettingsReadService, SettingsWriteService,
    VideoCard, VideoList, VideoStateService, YouTubeKeyService,
)
from .dashboard_ui import FeedDraftService
from .dashboard_settings import DashboardSettings
from .dashboard_page import render_page as _page
from .drafts import approve as approve_draft, quality_failure, save_generated, _load_record
from .draft_generation import DraftGenerator, ProviderDraftGenerator
from .posting_service import CHANNEL_ID, PostingService
from .prompt_policy import build_draft_prompt, build_revision_prompt
from .draft_review import MAX_REVISIONS, other_comments, review_problems
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


# PDF p.2 example videos, one per "our channel". Used only as the watch page for
# account checks and the manual login window when no RSS video is loaded yet
# (ADR-0003). The program never opens YouTube home or Google account pages.
PDF_EXAMPLE_VIDEOS = {
    "UCxlc0Ky0aWoD8uI09ad44Tg": "akn-AvCeHBI",
    "UC-ee_ziASM251TMXe3P3VZA": "JjY09DSdzx0",
    "UC09L3JxGVcn7SKLa-pjTEmw": "DvxMfC_KjX0",
    "UCVdtDW-HF4KluixGaBAcI4w": "3K82-PjUeP0",
    "UCkGl2jieOVhGiHPdXF77Yyw": "WxXINTXQSd4",
}


def watch_url(video_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id or ""):
        raise ValueError("INVALID_VIDEO_ID")
    return f"https://www.youtube.com/watch?v={video_id}&hl=ko"


def _open_login_window(root: Path, video_id: str) -> subprocess.Popen:
    """Plain (non-automated) Chrome on an allowed watch page; the person signs in."""
    url = watch_url(video_id)
    chrome = _installed_chrome()
    if chrome is None:
        raise ValueError("CHROME_NOT_FOUND")
    try:
        return subprocess.Popen([str(chrome), f"--user-data-dir={root}",
                          "--profile-directory=Default", "--no-first-run",
                          "--no-default-browser-check", "--new-window", url],
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
                 evidence_provider: VideoEvidence | None = None,
                 draft_generator: DraftGenerator | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.settings = settings
        self.evidence_provider = evidence_provider or VideoEvidence(
            key_provider=settings.youtube_api_key if settings is not None else None)
        self.draft_generator = draft_generator or ProviderDraftGenerator()
        self._settings_lock = RLock()
        self._posting_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chrome-post")
        self._login_window_process: subprocess.Popen | None = None
        self._login_window_root: Path | None = None
        self._verified_at: dict[str, str] = {}
        self._account_states: dict[str, str] = {}
        self._ai_test: tuple[bool, str] | None = None      # (ok, code) of the last explicit test
        self._youtube_key_invalid = False                   # set when a draft run reports a bad key
        self._last_feed_errors: dict[str, str] | None = None
        if settings is not None:
            with Store(self.db_path) as store:
                for label, status in store.profile_status().items():
                    if status["active"]:
                        self._account_states[label] = "SIGNED_IN"
                        self._verified_at[label] = status["confirmed_at"]
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

    def brand_public(self) -> dict[str, str]:
        if self.settings is None:
            raise ValueError("BRAND_SETTINGS_UNAVAILABLE")
        return self.settings.brand_public()

    def save_brand(self, name: str, description: str, reference_url: str) -> dict[str, str]:
        if self.settings is None:
            raise ValueError("BRAND_SETTINGS_UNAVAILABLE")
        with self._settings_lock:
            previous = self.settings.brand_public()
            result = self.settings.save_brand(name, description, reference_url)
            if (result["name"], result["description"]) != (previous["name"], previous["description"]):
                self._selected.clear()
            return result

    def comment_generation_public(self) -> dict[str, str | int]:
        if self.settings is None:
            raise ValueError("COMMENT_SETTINGS_UNAVAILABLE")
        return self.settings.comment_generation_public()

    def save_comment_generation(self, name: str, description: str, reference_url: str,
                                min_chars: int, max_chars: int,
                                review_filter: bool = True) -> dict[str, str | int | bool]:
        if self.settings is None:
            raise ValueError("COMMENT_SETTINGS_UNAVAILABLE")
        with self._settings_lock:
            previous = self.settings.comment_generation_public()
            result = self.settings.save_comment_generation(
                name, description, reference_url, min_chars, max_chars, review_filter)
            relevant = ("name", "description", "min_chars", "max_chars")
            if any(result[key] != previous[key] for key in relevant):
                self._selected.clear()
            return result

    def _draft_brand_matches(self, video_id: str) -> bool:
        if self.settings is None:
            return True
        record = _load_record(self.drafts_dir, video_id) or {}
        brand = self.settings.brand_public()
        limits = self.settings.comment_limits()
        return (record.get("brand_name", "운명원") == brand["name"]
                and record.get("brand_description", "연애 고민을 사주 관점에서 살펴보는 서비스")
                == brand["description"]
                and record.get("min_chars", 40) == limits["min_chars"]
                and record.get("max_chars", 120) == limits["max_chars"])

    def profile_public(self) -> dict[str, object]:
        if self.settings is None:
            raise ValueError("PROFILE_SETTINGS_UNAVAILABLE")
        return self.settings.profile_public()

    def setup_status(self) -> dict[str, object]:
        """IMP-17: one local overview of what this PC has configured. No network calls."""
        if self.settings is None:
            raise ValueError("SETTINGS_UNAVAILABLE")
        items: list[dict[str, object]] = []

        def add(key, label, required, state, value, detail, target="", focus=""):
            items.append({"id": key, "label": label, "required": required, "state": state,
                          "value": value, "detail": detail, "target": target, "focus": focus})

        with self._settings_lock:
            entries = self.settings.channel_entries()
            bad = [e["channel_id"] for e in entries if not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", e["channel_id"])]
            names = ", ".join(e["channel_name"] or e["channel_id"] for e in entries[:5])
            failed = self._last_feed_errors or {}
            if bad or not 5 <= len(entries) <= 20:
                add("channels", "YouTube 채널 ID", True, "missing", f"{len(entries)}개",
                    "UC로 시작하는 24자리 ID를 5~20개 등록해야 합니다.", "channel", "#channel-rows input")
            elif failed:
                add("channels", "YouTube 채널 ID", True, "warn", f"{len(entries)}개 · {names}",
                    "최근 영상 불러오기에서 실패한 채널: " + ", ".join(f"{k}({v.split(' ')[0]})" for k, v in failed.items()),
                    "channel", "#channel-rows input")
            else:
                add("channels", "YouTube 채널 ID", True, "ok", f"{len(entries)}개 · {names}",
                    "형식 확인 완료" + (" · 최근 불러오기 성공" if self._last_feed_errors is not None
                                     else " · 아직 영상 불러오기 전"), "channel", "#channel-rows input")
            chrome = _installed_chrome()
            add("chrome", "Google Chrome 설치", True, "ok" if chrome else "missing",
                "설치됨" if chrome else "찾을 수 없음",
                "댓글 게시와 계정 확인에 사용합니다." if chrome else "Google Chrome을 설치한 뒤 대시보드를 다시 시작하세요.")
            options = self.settings.profile_options_public()["options"]
            for index, option in enumerate(options):
                label = option["label"]
                state = self._account_states.get(label, "UNKNOWN")
                prepared = option["configured"] and option["connected"]
                status = ("ok" if state == "SIGNED_IN" else "missing" if state == "SIGNED_OUT" or not prepared
                          else "warn")
                value = {"SIGNED_IN": "로그인됨", "SIGNED_OUT": "로그아웃"}.get(state,
                         "준비됨 · 로그인 미확인" if prepared else "프로필 미준비")
                if option.get("memo"):
                    value += f" · 메모: {option['memo']}"
                detail = ("필수: 이 프로필로 댓글을 게시합니다. 다른 프로필보다 먼저 로그인을 확인합니다." if index == 0 else
                          "선택(가점): 로그인이 확인되면 아직 댓글을 달지 않은 영상이 이 프로필에도 돌아가며 다시 배정됩니다."
                          + ("" if self._account_states.get(options[0]["label"]) == "SIGNED_IN"
                             else f" {options[0]['label']} 로그인을 먼저 확인해야 설정할 수 있습니다."))
                add(f"profile:{label}", f"Chrome 프로필 {label}", index == 0, status, value,
                    detail + " '현재 계정 확인'을 누르면 상태가 갱신됩니다.", "profile", "#profile-list button")
            approved = 0
            try:
                for path in self.drafts_dir.glob("*.json"):
                    record = _load_record(self.drafts_dir, path.stem) if VIDEO_ID.fullmatch(path.stem) else None
                    if record and record.get("approval_hash") and not quality_failure(record):
                        approved += 1
            except (OSError, ValueError):
                pass
            add("drafts", "승인된 댓글 초안", True, "ok" if approved else "missing", f"{approved}개",
                "AI 키 없이도 ②에서 바로 쓸 수 있는 사람 승인 초안입니다." if approved else
                "영상을 불러와 AI 초안을 만들고 검토·승인하세요.", "load", "#load")
            brand = self.settings.brand_public()
            limits = self.settings.comment_limits()
            add("comment", "댓글 생성 설정", True, "ok" if brand["name"] and brand["description"] else "missing",
                f"{brand['name']} · {limits['min_chars']}~{limits['max_chars']}자",
                "브랜드명·설명과 글자 수 범위(없으면 40~120자).", "brand", "#brand-name")
            ai = self.settings.ai_public()
            if not ai["has_key"]:
                state, detail = "missing", "없으면 저장된 승인 초안만 쓸 수 있습니다(새 영상 즉석 초안 불가)."
            elif self._ai_test is None:
                state, detail = "warn", "키 입력됨 · 이번 실행에서 연결 테스트 전입니다."
            elif self._ai_test[0]:
                state, detail = "ok", "연결 테스트 성공."
            else:
                state, detail = "warn", f"연결 테스트 실패({self._ai_test[1]}). 키와 모델을 확인하세요."
            add("ai", "AI API 키", False, state, f"{ai['provider']} · {ai['model']} · " +
                ("키 있음" if ai["has_key"] else "키 없음"), detail, "ai", "#ai-key")
            has_youtube = bool(self.settings.youtube_api_key())
            add("youtube", "YouTube Data API 키", False,
                "missing" if not has_youtube else "warn" if self._youtube_key_invalid else "ok",
                "키 있음" if has_youtube else "키 없음",
                ("최근 초안 생성에서 키가 유효하지 않았습니다." if self._youtube_key_invalid else
                 "AI 초안 근거에 인기 댓글을 더할 때만 씁니다.") if has_youtube else
                "없어도 됩니다. 인기 댓글 없이 자막·제목·설명으로 초안을 만듭니다.", "ai", "#youtube-key")
            enabled = self.settings.review_filter_enabled()
            add("filter", "2차 필터", False, "ok" if enabled else "warn", "켜짐" if enabled else "꺼짐",
                "AI 초안을 검사하고 문제가 있으면 다시 쓰게 합니다.", "brand", "#comment-review-filter")
            add("test_videos", "본인 테스트 영상", False, "ok" if self.test_videos else "missing",
                f"{len(self.test_videos)}개 등록",
                "개발·시연용. README 부록 A의 명령으로 등록합니다(심사에는 필요 없음).")
        required = [item for item in items if item["required"]]
        return {"items": items, "required_total": len(required),
                "required_ok": sum(item["state"] == "ok" for item in required)}

    def _probe_video_id(self) -> str:
        """An allowed watch page for account checks (ADR-0003): loaded RSS first."""
        allowed = set(self.settings.channels()) if self.settings is not None else set()
        for card in self._videos.values():
            if card.channel_id in allowed:
                return card.video_id
        for channel_id in (self.settings.channels() if self.settings is not None else []):
            if channel_id in PDF_EXAMPLE_VIDEOS:
                return PDF_EXAMPLE_VIDEOS[channel_id]
        raise ValueError("PROBE_VIDEO_UNAVAILABLE")

    def _primary_profile(self) -> str:
        options = self.settings.profile_options_public()["options"]
        return options[0]["label"] if options else ""

    def _active_profiles(self) -> set[str]:
        with Store(self.db_path) as store:
            return {label for label, status in store.profile_status().items() if status["active"]}

    def _assignment_candidates(self) -> list[str]:
        """IMP-09/IMP-19: the first profile alone until it is confirmed signed in,
        then every confirmed profile in settings order."""
        all_options = self.settings.profile_options_public()["options"]
        usable = [item["label"] for item in all_options if item["configured"] and item["connected"]]
        primary = all_options[0]["label"] if all_options else ""
        active = self._active_profiles()
        if primary in usable and primary in active:
            return [label for label in usable if label in active]
        if primary in usable:
            return [primary]
        return usable[:1]

    def _require_primary(self, label: str) -> None:
        primary = self._primary_profile()
        if label != primary and primary not in self._active_profiles():
            raise ValueError("PROFILE_PRIMARY_REQUIRED")

    def _set_profile_active(self, label: str, active: bool) -> int:
        """Persist the confirmed state, then re-spread unattempted videos if candidates changed."""
        with Store(self.db_path) as store:
            store.set_profile_active(label, active, datetime.now(timezone.utc))
        return self._sync_assignments()

    def _sync_assignments(self, cards=None) -> int:
        if self.settings is None:
            return 0
        cards = list(self._videos.values()) if cards is None else list(cards)
        candidates = self._assignment_candidates()
        with Store(self.db_path) as store:
            if cards:
                store.assign_dashboard_videos(cards, candidates, datetime.now(timezone.utc))
            if not cards or store.assignment_candidates_key() == json.dumps(candidates, ensure_ascii=False):
                return 0
            return store.rebalance_dashboard_assignments(cards, candidates, datetime.now(timezone.utc))

    def profile_options_public(self) -> dict[str, object]:
        if self.settings is None:
            raise ValueError("PROFILE_SETTINGS_UNAVAILABLE")
        with self._settings_lock:
            result = self.settings.profile_options_public()
            window_open = (self._login_window_process is not None and
                           self._login_window_process.poll() is None)
            for option in result["options"]:
                option["verified_at"] = self._verified_at.get(option["label"], "")
                option["account_state"] = self._account_states.get(option["label"], "UNKNOWN")
                option["login_window_open"] = bool(window_open and
                    self._login_window_root == self.settings.app_profile_root(option["label"]))
            return result

    def verify_profile(self, label: str) -> dict[str, object]:
        return self._posting_worker.submit(self._verify_profile_on_worker, label).result()

    def _verify_profile_on_worker(self, label: str) -> dict[str, object]:
        with self._settings_lock:
            if self.settings is None or self.poster is None:
                raise ValueError("PROFILE_SETTINGS_UNAVAILABLE")
            self._require_primary(label)
            previous = (self._account_states.get(label, "UNKNOWN"), self._verified_at.get(label, ""))
            root = self.settings.app_profile_root(label)
            if (self._login_window_process is not None and
                    self._login_window_root == root and
                    self._login_window_process.poll() is None):
                raise ValueError("PROFILE_LOCKED")
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
                self.poster.check_signed_in(self._probe_video_id())
            except ValueError as exc:
                if str(exc) == "PROFILE_SIGNED_OUT":
                    self._account_states[label] = "SIGNED_OUT"
                    self._verified_at.pop(label, None)
                    self._set_profile_active(label, False)
                else:
                    # Not a clear answer (network, slow page): keep the last known state.
                    self._account_states[label], self._verified_at[label] = previous
                raise
            self._verified_at[label] = datetime.now(timezone.utc).isoformat()
            self._account_states[label] = "SIGNED_IN"
            reassigned = self._set_profile_active(label, True)
            return {**self.profile_options_public(), "reassigned": reassigned,
                    "states": self.video_states() if self._videos else {}}

    def save_profile_memo(self, label: str, memo: str) -> dict[str, object]:
        if self.settings is None:
            raise ValueError("PROFILE_SETTINGS_UNAVAILABLE")
        with self._settings_lock:
            self.settings.save_profile_memo(label, memo)
        return self.profile_options_public()

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
            self._require_primary(label)
            root = self.settings.app_profile_root(label)
            if (self._login_window_process is not None and
                    self._login_window_process.poll() is None):
                raise ValueError("PROFILE_LOCKED")
            # The account may change in this window: stop assigning to it until re-checked.
            self._verified_at.pop(label, None)
            self._account_states[label] = "UNKNOWN"
            reassigned = self._set_profile_active(label, False)
            root.mkdir(parents=True, exist_ok=True)
            profile = root / "Default"
            if not profile.resolve(strict=False).is_relative_to(root.resolve()):
                raise ValueError("PROFILE_PATH_UNSAFE")
            profile.mkdir(exist_ok=True)
            process = _open_login_window(root, self._probe_video_id())
            saved = self.settings.connect_profile(label)
            self._selected.clear()
            self._login_window_process = process
            self._login_window_root = root
            return {**saved, "login_window_opened": True, "reassigned": reassigned,
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
        try:
            test_ai_connection(provider, model, key)
        except Exception as exc:
            self._ai_test = (False, str(exc) if str(exc).isupper() else type(exc).__name__)
            raise
        self._ai_test = (True, "")
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
            self._youtube_key_invalid = "키가 유효하지" in (evidence.notice or "")
            brand = self.settings.brand_public()
            limits = self.settings.comment_limits()
            prompt = build_draft_prompt(evidence, brand_name=brand["name"],
                                        brand_description=brand["description"], **limits)
            result = self.draft_generator.generate(provider, model, key, prompt)
            enabled = self.settings.review_filter_enabled()
            rounds = []
            if enabled:
                result, rounds = self._review_loop(provider, model, key, prompt, result,
                                                   evidence.text, brand, limits, video_id)
            record = save_generated(card, result, self.drafts_dir, source_text=evidence.text,
                                    evidence_sources=evidence.sources, profile=profile,
                                    brand_name=brand["name"], brand_description=brand["description"],
                                    review_rounds=rounds, prompt_version=prompt.version,
                                    **limits)
            return self._draft_view(record, brand, limits, video_id) | {
                "evidence_notice": evidence.notice, "review_filter": enabled, "changed": bool(rounds)}

    def _candidate(self, values: dict, source_text: str, brand: dict, limits: dict) -> dict:
        return {**{k: str(values.get(k, "")) for k in ("worry_summary", "cited_detail", "comment")},
                "source_text": source_text, "brand_name": brand["name"], **limits}

    def _review_loop(self, provider, model, key, prompt, result, source_text, brand, limits, video_id):
        """IMP-15 second pass: deterministic review, then AI rewrite with concrete feedback."""
        others = other_comments(self.drafts_dir, video_id)
        rounds = []
        for _ in range(MAX_REVISIONS):
            problems = review_problems(self._candidate(result, source_text, brand, limits), others)
            if not problems:
                break
            rounds.append({"comment": str(result.get("comment", "")), "problems": problems})
            try:
                revised = self.draft_generator.generate(
                    provider, model, key, build_revision_prompt(prompt, result, problems))
            except ValueError:
                break  # keep the previous draft; the person still reviews it
            if isinstance(revised, dict):
                result = revised
        if rounds:
            final = self._candidate(result, source_text, brand, limits)
            rounds.append({"comment": final["comment"], "problems": review_problems(final, others)})
        return result, rounds

    def _draft_view(self, record: dict, brand: dict, limits: dict, video_id: str) -> dict:
        view = {key: record.get(key, "") for key in ("video_id", "worry_summary", "cited_detail", "comment",
                                                     "evidence_sources", "source_text", "min_chars", "max_chars")}
        current = review_problems(self._candidate(record, record.get("source_text", ""), brand, limits),
                                  other_comments(self.drafts_dir, video_id))
        return view | {"review_rounds": record.get("review_rounds", []), "problems": current,
                       "approved": bool(record.get("approval_hash")),
                       "prompt_version": record.get("prompt_version", "")}

    def refine_draft(self, video_id: str, rewrite: bool = False) -> dict[str, object]:
        """IMP-16: open a saved draft for review, optionally re-running the second-pass filter."""
        if self.settings is None:
            raise ValueError("AI_SETTINGS_UNAVAILABLE")
        with self._settings_lock:
            card = self._videos.get(video_id)
            if card is None:
                raise ValueError("VIDEO_NOT_FOUND")
            record = _load_record(self.drafts_dir, video_id)
            if not record:
                raise ValueError("DRAFT_MISSING")
            brand = self.settings.brand_public()
            limits = self.settings.comment_limits()
            view = self._draft_view(record, brand, limits, video_id) | {
                "review_filter": self.settings.review_filter_enabled(), "changed": False}
            if not rewrite or not view["problems"]:
                return view
            provider, model, key = self.settings.ai_credentials()
            if not key:
                raise ValueError("AI_KEY_MISSING")
            source = str(record.get("source_text") or card.title)
            sources = tuple(record.get("evidence_sources") or ())
            prompt = build_draft_prompt(EvidenceResult(source, sources), brand_name=brand["name"],
                                        brand_description=brand["description"], **limits)
            start = {k: str(record.get(k, "")) for k in ("worry_summary", "cited_detail", "comment")}
            result, rounds = self._review_loop(provider, model, key, prompt, start, source,
                                               brand, limits, video_id)
            if result == start:
                return view | {"review_rounds": view["review_rounds"] + rounds}
            profile = str(record.get("generated_profile") or self._assigned_profile(video_id))
            saved = save_generated(card, result, self.drafts_dir, source_text=source,
                                   evidence_sources=sources, profile=profile,
                                   brand_name=brand["name"], brand_description=brand["description"],
                                   review_rounds=list(record.get("review_rounds", [])) + rounds,
                                   prompt_version=prompt.version + "+refine", **limits)
            return self._draft_view(saved, brand, limits, video_id) | {
                "review_filter": self.settings.review_filter_enabled(), "changed": True}

    def approve_draft(self, video_id: str, values: dict) -> dict[str, object]:
        with self._settings_lock:
            card = self._videos.get(video_id)
            if card is None:
                raise ValueError("VIDEO_NOT_FOUND")
            if self.settings is not None and not self._draft_brand_matches(video_id):
                raise ValueError("BRAND_CHANGED_REGENERATE")
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
            self._last_feed_errors = dict(result.errors)
            if self.settings is not None:
                self._sync_assignments(result.videos)
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
            if self.settings is not None:
                result = replace(result, **self.settings.comment_limits())
            if result.can_post and self.settings is not None:
                if not self._draft_brand_matches(video_id):
                    return replace(result, can_post=False, reason_code="BRAND_CHANGED_REGENERATE")
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
            if video_id in self._videos and self.settings is not None:
                if not self._draft_brand_matches(video_id):
                    return PostStatus("blocked", "BRAND_CHANGED_REGENERATE")
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
            result = super().post_video(video_id)
            if result.reason_code == "LOGIN_REQUIRED" and self.settings is not None and self.profile:
                self._account_states[self.profile] = "SIGNED_OUT"
                self._verified_at.pop(self.profile, None)
                self._set_profile_active(str(self.profile), False)
            return result


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
                    if isinstance(service, VideoStateService):
                        result["states"] = service.video_states()
                    return self._json(200, result)
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/settings" and isinstance(service, SettingsReadService):
                if not secrets.compare_digest(self.headers.get("X-Session-Token", ""), token):
                    return self._reject(403, FORBIDDEN)
                try:
                    return self._json(200, {"yaml": service.settings_yaml()})
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/channels" and isinstance(service, ChannelReadService):
                if not secrets.compare_digest(self.headers.get("X-Session-Token", ""), token):
                    return self._reject(403, FORBIDDEN)
                try:
                    entries = service.channel_entries() if isinstance(service, ChannelEntryReadService) else [
                        {"channel_name": channel_id, "channel_id": channel_id}
                        for channel_id in service.channel_ids()]
                    return self._json(200, {"channels": service.channel_ids(), "entries": entries})
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/ai" and isinstance(service, AIReadService):
                if not secrets.compare_digest(self.headers.get("X-Session-Token", ""), token):
                    return self._reject(403, FORBIDDEN)
                try:
                    return self._json(200, service.ai_public())
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/brand" and isinstance(service, BrandReadService):
                if not secrets.compare_digest(self.headers.get("X-Session-Token", ""), token):
                    return self._reject(403, FORBIDDEN)
                try:
                    return self._json(200, service.brand_public())
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/comment-settings" and isinstance(service, CommentGenerationReadService):
                if not secrets.compare_digest(self.headers.get("X-Session-Token", ""), token):
                    return self._reject(403, FORBIDDEN)
                try:
                    return self._json(200, service.comment_generation_public())
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/profile" and isinstance(service, ProfileReadService):
                if not secrets.compare_digest(self.headers.get("X-Session-Token", ""), token):
                    return self._reject(403, FORBIDDEN)
                try:
                    return self._json(200, service.profile_public())
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/profile-options" and isinstance(service, ProfileOptionsService):
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
            if self.path == "/api/setup-status":
                if not self._session_ok():
                    return self._reject(403, FORBIDDEN)
                if not isinstance(service, SetupStatusService):
                    return self._json(200, {"items": [], "required_total": 0, "required_ok": 0,
                                            "unavailable": True})
                try:
                    return self._json(200, service.setup_status())
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/history":
                if not self._session_ok():
                    return self._reject(403, FORBIDDEN)
                if not isinstance(service, HistoryService):
                    return self._json(200, {"items": [], "posted_today": 0, "daily_limit": 0,
                                            "unavailable": True})
                try:
                    result = service.history()
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
                for item in result["items"]:
                    item["screenshot_url"] = _capture_url(item.pop("screenshot_path", ""), captures)
                return self._json(200, result)
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
                                 "/api/channels/test", "/api/ai", "/api/ai/test", "/api/brand", "/api/comment-settings", "/api/youtube-key",
                                 "/api/profile", "/api/profile/add", "/api/profile/memo", "/api/profile/verify", "/api/profile/setup", "/api/drafts/generate", "/api/drafts/approve", "/api/drafts/refine"}:
                return self._reject(404, BAD_REQUEST)
            if self.headers.get("Origin") != f"http://{HOST}:{self.server.server_port}":
                return self._reject_early_post(403, FORBIDDEN)
            if not secrets.compare_digest(self.headers.get("X-Session-Token", ""), token):
                return self._reject_early_post(403, FORBIDDEN)
            if self.headers.get("Content-Type") != "application/json":
                return self._reject_early_post(400, BAD_REQUEST)
            try:
                size = int(self.headers.get("Content-Length", ""))
                if not 0 < size <= (8192 if self.path in {"/api/settings", "/api/channels", "/api/ai", "/api/brand", "/api/comment-settings"} else 4096):
                    raise ValueError
                data = json.loads(self.rfile.read(size))
                if self.path == "/api/ai":
                    if (not isinstance(data, dict)
                            or set(data) != {"provider", "model", "api_key", "clear_key"}
                            or any(not isinstance(data[key], str)
                                   for key in ("provider", "model", "api_key"))
                            or not isinstance(data["clear_key"], bool)):
                        raise ValueError
                elif self.path == "/api/brand":
                    if (not isinstance(data, dict) or set(data) != {"name", "description", "reference_url"}
                            or any(not isinstance(data[key], str) for key in data)):
                        raise ValueError
                elif self.path == "/api/comment-settings":
                    base = {"name", "description", "reference_url", "min_chars", "max_chars"}
                    if (not isinstance(data, dict)
                            or set(data) not in (base, base | {"review_filter"})
                            or not isinstance(data.get("review_filter", True), bool)
                            or any(not isinstance(data[key], str) for key in ("name", "description", "reference_url"))
                            or any(type(data[key]) is not int for key in ("min_chars", "max_chars"))):
                        raise ValueError
                elif self.path == "/api/profile":
                    if not isinstance(data, dict) or set(data) != {"label"} or not isinstance(data["label"], str):
                        raise ValueError
                elif self.path == "/api/profile/add":
                    if not isinstance(data, dict) or set(data) != {"label"} or not isinstance(data["label"], str):
                        raise ValueError
                elif self.path == "/api/profile/memo":
                    if (not isinstance(data, dict) or set(data) != {"label", "memo"}
                            or not isinstance(data["label"], str) or not isinstance(data["memo"], str)):
                        raise ValueError
                elif self.path == "/api/profile/verify":
                    if (not isinstance(data, dict) or set(data) != {"label"}
                            or not isinstance(data["label"], str)):
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
                elif self.path == "/api/drafts/refine":
                    if (not isinstance(data, dict) or set(data) != {"video_id", "rewrite"}
                            or not isinstance(data["video_id"], str) or not VIDEO_ID.fullmatch(data["video_id"])
                            or not isinstance(data["rewrite"], bool)):
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
                if not isinstance(service, SettingsWriteService):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, {"yaml": service.save_settings_yaml(data["yaml"])})
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(400, reason if reason.startswith("SETTINGS_") else BAD_REQUEST)
                except OSError:
                    return self._reject(503, "SETTINGS_WRITE_FAILED")
            if self.path == "/api/channels":
                if not isinstance(service, ChannelWriteService):
                    return self._reject(404, BAD_REQUEST)
                try:
                    if "entries" in data and isinstance(service, ChannelEntryWriteService):
                        entries = service.save_channel_entries(data["entries"])
                        return self._json(200, {"channels": [item["channel_id"] for item in entries],
                                                "entries": entries})
                    channels = service.save_channel_ids(data["channels"])
                    entries = service.channel_entries() if isinstance(service, ChannelEntryReadService) else [
                        {"channel_name": channel_id, "channel_id": channel_id} for channel_id in channels]
                    return self._json(200, {"channels": channels, "entries": entries})
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(400, reason if reason.startswith("SETTINGS_") else BAD_REQUEST)
                except OSError:
                    return self._reject(503, "SETTINGS_WRITE_FAILED")
            if self.path == "/api/profile/setup":
                if not isinstance(service, ProfileOpenService):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.open_app_profile(data["label"]))
                except ValueError as exc:
                    reason = str(exc)
                    if reason == "PROFILE_SETTINGS_INVALID":
                        return self._reject(400, reason)
                    return self._reject(503, reason if reason in {"CHROME_NOT_FOUND", "BROWSER_LAUNCH_FAILED", "PROFILE_PATH_UNSAFE", "PROFILE_LOCKED", "PROBE_VIDEO_UNAVAILABLE"} else "PROFILE_SETUP_FAILED")
                except OSError:
                    return self._reject(503, "PROFILE_SETUP_FAILED")
            if self.path == "/api/profile/add":
                if not isinstance(service, ProfileAddService):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.add_profile(data["label"]))
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(400, reason if reason.startswith("PROFILE_") else BAD_REQUEST)
                except OSError:
                    return self._reject(503, "PROFILE_SETUP_FAILED")
            if self.path == "/api/profile":
                if not isinstance(service, ProfileWriteService):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.save_profile(data["label"]))
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(400, reason if reason.startswith("PROFILE_") or reason.startswith("USER_") else BAD_REQUEST)
                except OSError:
                    return self._reject(503, "SETTINGS_WRITE_FAILED")
            if self.path == "/api/profile/memo":
                if not isinstance(service, ProfileMemoService):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.save_profile_memo(data["label"], data["memo"]))
                except ValueError as exc:
                    return self._reject(400, str(exc) if str(exc).startswith("PROFILE_") else BAD_REQUEST)
                except OSError:
                    return self._reject(503, "SETTINGS_WRITE_FAILED")
            if self.path == "/api/profile/verify":
                if not isinstance(service, ProfileVerifyService):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.verify_profile(data["label"]))
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(400 if reason == "PROFILE_SETTINGS_INVALID"
                                        else 409 if reason == "PROFILE_SIGNED_OUT" else 503,
                                        reason if reason.startswith(("PROFILE_", "BROWSER_", "USER_", "PROBE_")) else "PROFILE_ACCOUNT_CHECK_FAILED")
                except Exception as exc:
                    reason = getattr(exc, "code", "PROFILE_ACCOUNT_CHECK_FAILED")
                    return self._reject(503, reason)
            if self.path == "/api/channels/test":
                if not isinstance(service, ChannelReadService):
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
                if not isinstance(service, AIWriteService):
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
            if self.path == "/api/brand":
                if not isinstance(service, BrandWriteService):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.save_brand(data["name"], data["description"], data["reference_url"]))
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(400, reason if reason.startswith("BRAND_") else BAD_REQUEST)
                except OSError:
                    return self._reject(503, "SETTINGS_WRITE_FAILED")
            if self.path == "/api/comment-settings":
                if not isinstance(service, CommentGenerationWriteService):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.save_comment_generation(
                        data["name"], data["description"], data["reference_url"],
                        data["min_chars"], data["max_chars"], data.get("review_filter", True)))
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(400, reason if reason.startswith(("BRAND_", "COMMENT_")) else BAD_REQUEST)
                except OSError:
                    return self._reject(503, "SETTINGS_WRITE_FAILED")
            if self.path == "/api/youtube-key":
                if not isinstance(service, YouTubeKeyService):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.save_youtube_api_key(data["api_key"]))
                except (KeyError, ValueError) as exc:
                    return self._reject(400, str(exc) if str(exc) == "YOUTUBE_KEY_INVALID" else BAD_REQUEST)
                except OSError:
                    return self._reject(503, "SETTINGS_WRITE_FAILED")
            if self.path == "/api/ai/test":
                if not isinstance(service, AITestService):
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
                if not isinstance(service, DraftGenerationService):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.generate_draft(data["video_id"]))
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(409 if reason == "AI_KEY_MISSING" else 503,
                                        reason if reason.isupper() else "DRAFT_GENERATION_FAILED")
                except OSError:
                    return self._reject(503, "DRAFT_WRITE_FAILED")
            if self.path == "/api/drafts/refine":
                if not isinstance(service, DraftRefineService):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.refine_draft(data["video_id"], data["rewrite"]))
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(409 if reason in {"AI_KEY_MISSING", "DRAFT_MISSING"} else 503,
                                        reason if reason.isupper() else "DRAFT_REFINE_FAILED")
                except OSError:
                    return self._reject(503, "DRAFT_WRITE_FAILED")
            if self.path == "/api/drafts/approve":
                if not isinstance(service, DraftApprovalService):
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

