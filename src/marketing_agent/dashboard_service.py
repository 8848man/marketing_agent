"""Dashboard services: configured posting, local demo, and channel connection check."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
from threading import RLock
import xml.etree.ElementTree as ET

from .chrome_launch import PDF_EXAMPLE_VIDEOS, _installed_chrome, _is_default_chrome_user_data_dir, _open_login_window
from .ai_client import test_ai_connection
from .captions import EvidenceResult, VideoEvidence
from .dashboard_contracts import DraftPreview, PostStatus, VideoCard, VideoList
from .dashboard_settings import DashboardSettings
from .drafts import approve as approve_draft, awaiting_approval, quality_failure, save_generated, _load_record
from .draft_generation import DraftGenerator, ProviderDraftGenerator
from .posting_service import CHANNEL_ID, PostingService
from .prompt_policy import build_draft_prompt, build_revision_prompt
from .draft_review import MAX_REVISIONS, other_comments, review_problems
from .rss_feed import fetch_channel, parse_channel
from .storage import Store


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


class ConfiguredPostingService(PostingService):
    """Keep posting disabled until a specific local Chrome profile is set."""

    def __init__(self, *args, settings: DashboardSettings | None = None,
                 evidence_provider: VideoEvidence | None = None,
                 draft_generator: DraftGenerator | None = None, review_mode: bool = False, **kwargs):
        if settings is not None:
            kwargs.setdefault("allowed_channels", settings.channels)
        kwargs.setdefault("channel_cooldown_minutes", 60)
        super().__init__(*args, **kwargs)
        self.settings = settings
        self.review_mode = review_mode
        self.evidence_provider = evidence_provider or VideoEvidence(
            key_provider=settings.youtube_api_key if settings is not None else None)
        self.draft_generator = draft_generator or ProviderDraftGenerator()
        # Lock order is always browser -> settings. The browser lock covers everything that
        # reads or changes the Chrome profile in use; the settings lock only guards state.
        self._browser_lock = RLock()
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
        """H21/IMP-26: a draft stays valid while the brand name and length range are
        unchanged. The description only steers AI tone, so (like the URL) it is not compared."""
        if self.settings is None:
            return True
        record = _load_record(self.drafts_dir, video_id) or {}
        brand = self.settings.brand_public()
        limits = self.settings.comment_limits()
        return (record.get("brand_name", "운명원") == brand["name"]
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
        with self._browser_lock:
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
                probe = self._probe_video_id()
            try:
                self.poster.check_signed_in(probe)
            except ValueError as exc:
                with self._settings_lock:
                    if str(exc) == "PROFILE_SIGNED_OUT":
                        self._account_states[label] = "SIGNED_OUT"
                        self._verified_at.pop(label, None)
                        self._set_profile_active(label, False)
                    else:
                        # Not a clear answer (network, slow page): keep the last known state.
                        self._account_states[label], self._verified_at[label] = previous
                raise
            with self._settings_lock:
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
        with self._browser_lock, self._settings_lock:
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
        with self._browser_lock, self._settings_lock:
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
        """Call the selected provider only after an explicit local UI request.

        The settings lock is held only to snapshot the inputs and to save; evidence collection
        and the AI calls run outside it so the dashboard stays responsive."""
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
            brand = self.settings.brand_public()
            limits = self.settings.comment_limits()
            enabled = self.settings.review_filter_enabled()
        evidence = self.evidence_provider.collect(card)
        key_invalid = "키가 유효하지" in (evidence.notice or "")
        prompt = build_draft_prompt(evidence, brand_name=brand["name"],
                                    brand_description=brand["description"], **limits)
        result = self.draft_generator.generate(provider, model, key, prompt)
        rounds = []
        if enabled:
            result, rounds = self._review_loop(provider, model, key, prompt, result,
                                               evidence.text, brand, limits, video_id)
        with self._settings_lock:
            self._youtube_key_invalid = key_invalid
            self._require_unchanged(video_id, card, brand, limits)
            record = save_generated(card, result, self.drafts_dir, source_text=evidence.text,
                                    evidence_sources=evidence.sources, profile=profile,
                                    brand_name=brand["name"], brand_description=brand["description"],
                                    review_rounds=rounds, prompt_version=prompt.version,
                                    **limits)
            return self._draft_view(record, brand, limits, video_id) | {
                "evidence_notice": evidence.notice, "review_filter": enabled, "changed": bool(rounds)}

    def _require_unchanged(self, video_id: str, card, brand: dict, limits: dict) -> None:
        """Call with the settings lock held: drop a result made for other inputs than today's."""
        if (self._videos.get(video_id) != card
                or self.settings.brand_public()["name"] != brand["name"]
                or self.settings.comment_limits() != limits):
            raise ValueError("BRAND_CHANGED_REGENERATE")

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
        """IMP-16: open a saved draft for review, optionally re-running the second-pass filter.

        Like generate_draft, the AI rewrite runs outside the settings lock."""
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
            enabled = self.settings.review_filter_enabled()
            view = self._draft_view(record, brand, limits, video_id) | {
                "review_filter": enabled, "changed": False}
            if not rewrite or not view["problems"]:
                return view
            provider, model, key = self.settings.ai_credentials()
            if not key:
                raise ValueError("AI_KEY_MISSING")
            profile = str(record.get("generated_profile") or self._assigned_profile(video_id))
        source = str(record.get("source_text") or card.title)
        sources = tuple(record.get("evidence_sources") or ())
        prompt = build_draft_prompt(EvidenceResult(source, sources), brand_name=brand["name"],
                                    brand_description=brand["description"], **limits)
        start = {k: str(record.get(k, "")) for k in ("worry_summary", "cited_detail", "comment")}
        result, rounds = self._review_loop(provider, model, key, prompt, start, source,
                                           brand, limits, video_id)
        if result == start:
            return view | {"review_rounds": view["review_rounds"] + rounds}
        with self._settings_lock:
            self._require_unchanged(video_id, card, brand, limits)
            saved = save_generated(card, result, self.drafts_dir, source_text=source,
                                   evidence_sources=sources, profile=profile,
                                   brand_name=brand["name"], brand_description=brand["description"],
                                   review_rounds=list(record.get("review_rounds", [])) + rounds,
                                   prompt_version=prompt.version + "+refine", **limits)
            return self._draft_view(saved, brand, limits, video_id) | {
                "review_filter": enabled, "changed": True}

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

    def resolve_outcome(self, video_id: str, outcome: str, reviewer: str) -> dict[str, object]:
        """Human closes an OUTCOME_UNKNOWN post; no Chrome, so the settings lock only."""
        with self._settings_lock, Store(self.db_path) as store:
            store.resolve_dashboard_outcome(video_id, outcome, reviewer, self.clock())
        return {"video_id": video_id, "status": outcome}

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

    def review_pick(self) -> dict[str, str] | None:
        """IMP-22: in review mode, the newest loaded video whose AI draft awaits
        approval and that has never been attempted here. Display only."""
        if not self.review_mode:
            return None
        candidates = sorted((card for key, card in self._videos.items() if key not in self.test_videos),
                            key=lambda card: (card.published_at, card.video_id), reverse=True)
        with Store(self.db_path) as store:
            for card in candidates:
                if store.dashboard_post_status(card.video_id):
                    continue
                if store.db.execute("SELECT 1 FROM dashboard_post_reservations WHERE video_id=?",
                                    (card.video_id,)).fetchone():
                    continue
                if not awaiting_approval(self.drafts_dir, card):
                    continue
                # Prefer a draft the second-pass filter has nothing left to fix.
                record = _load_record(Path(self.drafts_dir), card.video_id) or {}
                if review_problems(record, other_comments(Path(self.drafts_dir), card.video_id)):
                    continue
                return {"video_id": card.video_id, "badge": "테스트용"}
        return None

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
                elif posted in {"RESERVED", "SUBMITTING", "OUTCOME_UNKNOWN", "DISMISSED", "POST_OUTCOME_UNKNOWN", "POST_PENDING"}:
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

    def _assigned_profile_root(self, video_id: str) -> tuple[str, Path]:
        """Validate the video's profile without touching the poster."""
        if self.settings is None or self.poster is None:
            raise ValueError("PROFILE_NOT_CONFIGURED")
        label = self._assigned_profile(video_id)
        root = self.settings.app_profile_root(label)
        saved = self.settings.profile_options_public()["options"]
        option = next(item for item in saved if item["label"] == label)
        if not option["configured"] or not option["connected"]:
            raise ValueError("PROFILE_NOT_CONFIGURED")
        return label, root

    def _use_assigned_profile(self, video_id: str) -> None:
        """Point the poster at the video's profile. Call with the browser lock held."""
        label, root = self._assigned_profile_root(video_id)
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
        # Selecting must not wait for Chrome. When a post, account check or login window holds
        # the browser lock, only validate: the poster's profile is left untouched and the post
        # itself repeats every profile check under the browser lock.
        own_browser = self._browser_lock.acquire(blocking=False)
        try:
            with self._settings_lock:
                return self._select_video_locked(video_id, own_browser)
        finally:
            if own_browser:
                self._browser_lock.release()

    def _select_video_locked(self, video_id: str, own_browser: bool) -> DraftPreview:
        result = super().select_video(video_id)
        if self.settings is not None:
            result = replace(result, **self.settings.comment_limits())
        if result.can_post and self.settings is not None:
            if not self._draft_brand_matches(video_id):
                return replace(result, can_post=False, reason_code="BRAND_CHANGED_REGENERATE")
        if not result.can_post and result.reason_code == "APPROVAL_MISSING":
            # IMP-22: a draft awaiting human approval shows the approval step first;
            # profile checks apply once it is approved.
            return result
        if video_id in self._videos:
            try:
                self._assigned_profile(video_id)
                if result.can_post:
                    if own_browser:
                        self._use_assigned_profile(video_id)
                    else:
                        self._assigned_profile_root(video_id)
            except ValueError as exc:
                return replace(result, can_post=False, reason_code=str(exc))
        reason = self._profile_reason() if result.can_post and own_browser else ""
        return replace(result, can_post=False, reason_code=reason) if result.can_post and reason else result

    def post_video(self, video_id: str, *, keep_window_open: bool = False) -> PostStatus:
        return self._posting_worker.submit(self._post_video_on_worker, video_id, keep_window_open).result()

    def _post_video_on_worker(self, video_id: str, keep_window_open: bool) -> PostStatus:
        with self._browser_lock:
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
            result = super().post_video(video_id)  # Chrome: browser lock only
            with self._settings_lock:
                if result.reason_code == "LOGIN_REQUIRED" and self.settings is not None and self.profile:
                    self._account_states[self.profile] = "SIGNED_OUT"
                    self._verified_at.pop(self.profile, None)
                    self._set_profile_active(str(self.profile), False)
            return result
