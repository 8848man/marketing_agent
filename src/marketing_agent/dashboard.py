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
import tempfile
from threading import RLock
import webbrowser
import xml.etree.ElementTree as ET

import yaml

from .ai_client import PROVIDERS, create_ai_client, test_ai_connection, validate_model
from .captions import VideoEvidence
from .dashboard_contracts import (BAD_REQUEST, FORBIDDEN, INTERNAL_ERROR,
                                  INVALID_VIDEO_ID, METHOD_NOT_ALLOWED,
                                  DashboardService, DraftPreview, PostStatus, VideoCard, VideoList)
from .dashboard_ui import FeedDraftService, _page as base_page
from .drafts import approve as approve_draft, save_generated, _load_record
from .posting_service import CHANNEL_ID, PostingService
from .profile_emails import ProfileEmails
from .rss_feed import CHANNELS, fetch_channel, list_videos, parse_channel, recheck_video
from .storage import Store


HOST = "127.0.0.1"
CHANNEL_NAME = re.compile(r"[^\x00-\x1f\x7f]{1,100}\Z")
PROFILE_LABEL = re.compile(r'[^\x00-\x1f\x7f\\/:*?"<>|]{1,30}\Z')
PROFILE_ID = re.compile(r"(?:youtube[123]|p-[a-f0-9]{16})\Z")
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


DRAFT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "worry_summary": {"type": "string", "description": "One Korean sentence describing the viewer concern."},
        "cited_detail": {"type": "string", "description": "An exact phrase from video_title."},
        "comment": {"type": "string", "description": "A 40-120 character Korean YouTube comment."},
    },
    "required": ["worry_summary", "cited_detail", "comment"],
    "additionalProperties": False,
}


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


class DashboardSettings:
    """Private YAML settings; only the four safe dashboard fields reach the UI."""

    DEFAULT = {
        "profiles": ["유튜브1", "유튜브2", "유튜브3"],
        "channels": list(CHANNELS),
        "comment": {"min_chars": 40, "max_chars": 120, "brand": "운명원"},
        "limits": {"daily_max_comments": 10},
    }

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = RLock()
        self._current = self._validate(self._read_full())
        self._migrate_legacy_ai_env()
        self._migrate_legacy_ai_key()

    def _ai_env_path(self) -> Path:
        return self.path.parent / ".env"

    def youtube_api_key(self) -> str:
        """Read the project's YouTube key for each explicit draft request."""
        with self._lock:
            path = self._ai_env_path()
            if path.is_symlink():
                raise ValueError("AI_ENV_FILE_UNSAFE")
            if path.exists():
                if not path.is_file() or path.stat().st_size > 16384:
                    raise ValueError("AI_ENV_FILE_INVALID")
                found = None
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip() or line.lstrip().startswith("#"):
                        continue
                    name, separator, value = line.partition("=")
                    if name != "YOUTUBE_API_KEY":
                        continue
                    if not separator or found is not None:
                        raise ValueError("AI_ENV_FILE_INVALID")
                    try:
                        found = json.loads(value) if value.startswith('"') else value
                    except json.JSONDecodeError as exc:
                        raise ValueError("AI_ENV_FILE_INVALID") from exc
                    if not isinstance(found, str):
                        raise ValueError("AI_ENV_FILE_INVALID")
                if found:
                    return found
            return os.getenv("YOUTUBE_API_KEY", "")

    def save_youtube_api_key(self, key: str) -> dict[str, bool]:
        if (not isinstance(key, str) or not 8 <= len(key) <= 256
                or any(ord(char) < 33 or ord(char) > 126 for char in key)):
            raise ValueError("YOUTUBE_KEY_INVALID")
        with self._lock:
            path = self._ai_env_path()
            if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_size > 16384)):
                raise ValueError("AI_ENV_FILE_UNSAFE")
            source = path if path.exists() else path.parent / ".env.example"
            if source.is_symlink() or (source.exists() and source.stat().st_size > 16384):
                raise ValueError("AI_ENV_FILE_UNSAFE")
            lines = source.read_text(encoding="utf-8").splitlines() if source.exists() else []
            lines = [line for line in lines if line.partition("=")[0] != "YOUTUBE_API_KEY"]
            lines.append("YOUTUBE_API_KEY=" + json.dumps(key))
            fd, temporary = tempfile.mkstemp(prefix="youtube-env-", suffix=".tmp", dir=path.parent)
            try:
                os.chmod(temporary, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write("\n".join(lines) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                os.chmod(path, 0o600)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return {"has_key": True}

    def _read_ai_env(self, path: Path | None = None) -> dict[str, str]:
        path = path or self._ai_env_path()
        if path.is_symlink():
            raise ValueError("AI_ENV_FILE_UNSAFE")
        if not path.exists():
            return {}
        if path.stat().st_size > 16384:
            raise ValueError("AI_ENV_FILE_INVALID")
        result = {}
        allowed = {details[1] for details in PROVIDERS.values()}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            name, separator, value = line.partition("=")
            if not separator or name in result:
                raise ValueError("AI_ENV_FILE_INVALID")
            if name not in allowed:
                continue
            try:
                result[name] = json.loads(value) if value.startswith('"') else value
            except json.JSONDecodeError as exc:
                raise ValueError("AI_ENV_FILE_INVALID") from exc
            if not isinstance(result[name], str):
                raise ValueError("AI_ENV_FILE_INVALID")
        return result

    def _write_ai_env(self, values: dict[str, str]) -> None:
        path = self._ai_env_path()
        if path.is_symlink():
            raise ValueError("AI_ENV_FILE_UNSAFE")
        path.parent.mkdir(parents=True, exist_ok=True)
        source = path if path.exists() else path.parent / ".env.example"
        if source.is_symlink():
            raise ValueError("AI_ENV_FILE_UNSAFE")
        if source.exists() and source.stat().st_size > 16384:
            raise ValueError("AI_ENV_FILE_INVALID")
        existing = source.read_text(encoding="utf-8").splitlines() if source.exists() else []
        ai_names = {details[1] for details in PROVIDERS.values()}
        preserved = [line for line in existing if line.partition("=")[0] not in ai_names]
        fd, temporary = tempfile.mkstemp(prefix="ai-env-", suffix=".tmp", dir=path.parent)
        try:
            os.chmod(temporary, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                for line in preserved:
                    stream.write(line + "\n")
                for name, value in values.items():
                    if name not in ai_names or not isinstance(value, str):
                        raise ValueError("AI_ENV_FILE_INVALID")
                    stream.write(f"{name}={json.dumps(value)}\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o600)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _migrate_legacy_ai_env(self) -> None:
        legacy = self.path.parent / "data" / "dashboard" / ".env"
        if legacy.is_symlink():
            raise ValueError("AI_ENV_FILE_UNSAFE")
        if not legacy.exists():
            return
        old = self._read_ai_env(legacy)
        values = self._read_ai_env()
        changed = False
        for name, value in old.items():
            if value and not values.get(name):
                values[name] = value
                changed = True
        if changed or not self._ai_env_path().exists():
            self._write_ai_env(values)
            migrated = self._read_ai_env()
            if any(migrated.get(name) != values[name] for name in old if old[name] and name in values):
                raise ValueError("AI_ENV_MIGRATION_FAILED")
        legacy.unlink()

    def _migrate_legacy_ai_key(self) -> None:
        with self._lock:
            full = self._read_full()
            saved = full.get("ai")
            if not isinstance(saved, dict) or not saved.get("api_key"):
                return
            provider = saved.get("provider", "openai")
            if provider not in PROVIDERS or not isinstance(saved["api_key"], str):
                raise ValueError("AI_SETTINGS_INVALID")
            values = self._read_ai_env()
            if not values.get(PROVIDERS[provider][1]):
                values[PROVIDERS[provider][1]] = saved["api_key"]
            self._write_ai_env(values)
            saved.pop("api_key")
            self._write_full(full)

    def _read_full(self) -> dict:
        if self.path.is_symlink():
            raise ValueError("SETTINGS_SYMLINK_BLOCKED")
        source = self.path if self.path.exists() else self.path.with_name("config.example.yaml")
        if source.stat().st_size > 65_536:
            raise ValueError("SETTINGS_TOO_LARGE")
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("SETTINGS_INVALID")
        return data

    @classmethod
    def _validate(cls, data: dict) -> dict:
        if not isinstance(data, dict):
            raise ValueError("SETTINGS_INVALID")
        value = {key: data.get(key, cls.DEFAULT[key]) for key in cls.DEFAULT}
        profiles = value["profiles"]
        channels = value["channels"]
        comment = value["comment"]
        limits = value["limits"]
        if (not isinstance(profiles, list) or not 1 <= len(profiles) <= 20
                or any(not isinstance(item, str) or item != item.strip()
                       or not PROFILE_LABEL.fullmatch(item) for item in profiles)
                or len({item.casefold() for item in profiles}) != len(profiles)):
            raise ValueError("SETTINGS_PROFILES_INVALID")
        if (not isinstance(channels, list) or not 5 <= len(channels) <= 20
                or any(not isinstance(item, str) or not CHANNEL_ID.fullmatch(item) for item in channels)
                or len(set(channels)) != len(channels)):
            raise ValueError("SETTINGS_CHANNELS_INVALID")
        if (not isinstance(comment, dict) or comment.get("min_chars") != 40
                or comment.get("max_chars") != 120 or comment.get("brand", "운명원") != "운명원"):
            raise ValueError("SETTINGS_COMMENT_PDF_LOCKED")
        if (not isinstance(limits, dict) or limits.get("daily_max_comments") != 10):
            raise ValueError("SETTINGS_LIMIT_PDF_LOCKED")
        return {"profiles": list(profiles), "channels": list(channels),
                "comment": {"min_chars": 40, "max_chars": 120, "brand": "운명원"},
                "limits": {"daily_max_comments": 10}}

    def channels(self) -> dict[str, str]:
        with self._lock:
            full = self._read_full()
            saved_names = full.get("channel_names", {})
            if not isinstance(saved_names, dict):
                saved_names = {}
            return {channel_id: (saved_names.get(channel_id) if isinstance(saved_names.get(channel_id), str)
                                 else CHANNELS.get(channel_id, ""))
                    for channel_id in self._current["channels"]}

    def channel_ids(self) -> list[str]:
        with self._lock:
            return list(self._current["channels"])

    def channel_entries(self) -> list[dict[str, str]]:
        return [{"channel_name": name, "channel_id": channel_id}
                for channel_id, name in self.channels().items()]

    def _ai_data(self, full: dict) -> tuple[str, str, str]:
        saved = full.get("ai", {})
        if not isinstance(saved, dict):
            raise ValueError("AI_SETTINGS_INVALID")
        provider = saved.get("provider", "openai")
        if provider not in PROVIDERS:
            raise ValueError("AI_PROVIDER_INVALID")
        model = validate_model(saved.get("model", PROVIDERS[provider][0]))
        key = self._read_ai_env().get(PROVIDERS[provider][1], "")
        return provider, model, key

    def ai_public(self) -> dict[str, object]:
        with self._lock:
            provider, model, key = self._ai_data(self._read_full())
            source = "local" if key else "environment" if os.getenv(PROVIDERS[provider][1]) else "none"
            return {"provider": provider, "model": model,
                    "has_key": source != "none", "key_source": source}

    def ai_credentials(self) -> tuple[str, str, str]:
        with self._lock:
            provider, model, key = self._ai_data(self._read_full())
            return provider, model, key or os.getenv(PROVIDERS[provider][1], "")

    @staticmethod
    def _selected_profile(full: dict) -> str:
        profiles = full.get("profiles", DashboardSettings.DEFAULT["profiles"])
        if not isinstance(profiles, list) or not profiles:
            raise ValueError("PROFILE_SETTINGS_INVALID")
        label = full.get("selected_chrome_profile", profiles[0])
        if label not in profiles:
            raise ValueError("PROFILE_SETTINGS_INVALID")
        return label

    @classmethod
    def _profile_data(cls, full: dict) -> tuple[str, str]:
        profiles = full.get("chrome_profiles", {})
        saved = profiles.get(cls._selected_profile(full), {}) if isinstance(profiles, dict) else {}
        if not isinstance(saved, dict):
            raise ValueError("PROFILE_SETTINGS_INVALID")
        root, directory = saved.get("user_data_dir", ""), saved.get("profile_directory", "")
        if not isinstance(root, str) or not isinstance(directory, str):
            raise ValueError("PROFILE_SETTINGS_INVALID")
        return root, directory

    def profile_public(self) -> dict[str, object]:
        with self._lock:
            full = self._read_full()
            label = self._selected_profile(full)
            root, directory = self._profile_data(full)
            if root != str(self.app_profile_root(label)) or directory != "Default":
                root, directory = "", ""
            return {"label": label, "user_data_dir": root,
                    "profile_directory": directory, "configured": bool(root and directory)}

    def app_profile_root(self, label: str) -> Path:
        full = self._read_full()
        profiles = full.get("profiles", self.DEFAULT["profiles"])
        if not isinstance(profiles, list) or label not in profiles:
            raise ValueError("PROFILE_SETTINGS_INVALID")
        profile_ids = full.get("profile_ids", {})
        if not isinstance(profile_ids, dict):
            raise ValueError("PROFILE_SETTINGS_INVALID")
        defaults = {f"유튜브{i}": f"youtube{i}" for i in range(1, 4)}
        profile_id = profile_ids.get(label, defaults.get(label, ""))
        if not isinstance(profile_id, str) or not PROFILE_ID.fullmatch(profile_id):
            raise ValueError("PROFILE_SETTINGS_INVALID")
        app_root = self.path.parent.resolve()
        base = app_root / "data" / "dashboard"
        root = base / f"chrome-profile-{profile_id}"
        if (not base.resolve(strict=False).is_relative_to(app_root)
                or not root.resolve(strict=False).is_relative_to(base.resolve(strict=False))):
            raise ValueError("PROFILE_PATH_UNSAFE")
        return root

    def _profile_email_store(self) -> ProfileEmails:
        app_root = self.path.parent.resolve()
        base = self.path.parent / "data" / "dashboard"
        if not base.resolve(strict=False).is_relative_to(app_root):
            raise ValueError("PROFILE_EMAIL_FILE_UNSAFE")
        return ProfileEmails(base / "profile-emails.json", self._current["profiles"])

    def profile_options_public(self) -> dict[str, object]:
        """List only the application's three private profiles, never Chrome's local data."""
        with self._lock:
            full = self._read_full()
            selected = self._selected_profile(full)
            saved = full.get("chrome_profiles", {})
            emails = self._profile_email_store()
            options = []
            for label in self._current["profiles"]:
                root = self.app_profile_root(label)
                configured = (root / "Default").is_dir()
                connected = (configured and isinstance(saved, dict) and
                             saved.get(label) == {"user_data_dir": str(root),
                                                  "profile_directory": "Default"})
                options.append({"label": label, "email": emails.get(label), "configured": configured,
                                "connected": connected, "selected": label == selected})
            return {"selected": selected, "options": options}

    def add_profile(self, label: str) -> dict[str, object]:
        name = label.strip() if isinstance(label, str) else ""
        if not PROFILE_LABEL.fullmatch(name):
            raise ValueError("PROFILE_NAME_INVALID")
        with self._lock:
            full = self._read_full()
            profiles = list(full.get("profiles", self.DEFAULT["profiles"]))
            if any(item.casefold() == name.casefold() for item in profiles):
                raise ValueError("PROFILE_NAME_DUPLICATE")
            if len(profiles) >= 20:
                raise ValueError("PROFILE_LIMIT_REACHED")
            profile_ids = full.get("profile_ids", {})
            if not isinstance(profile_ids, dict):
                raise ValueError("PROFILE_SETTINGS_INVALID")
            used = set(profile_ids.values()) | {"youtube1", "youtube2", "youtube3"}
            profile_id = ""
            while not profile_id or profile_id in used:
                profile_id = "p-" + secrets.token_hex(8)
            profiles.append(name)
            profile_ids = {**profile_ids, name: profile_id}
            full["profiles"] = profiles
            full["profile_ids"] = profile_ids
            normalized = self._validate(full)
            self._write_full(full)
            self._current = normalized
            return {"label": name, "profile_id": profile_id}

    def save_profile_email(self, label: str, email: str) -> dict[str, object]:
        with self._lock:
            self._profile_email_store().set(label, email)
            return self.profile_options_public()

    def save_profile(self, label: str) -> dict[str, object]:
        root = self.app_profile_root(label)
        if not (root / "Default").is_dir():
            raise ValueError("PROFILE_DIRECTORY_MISSING")
        with self._lock:
            full = self._read_full()
            profiles = full.get("chrome_profiles", {})
            if not isinstance(profiles, dict):
                profiles = {}
            profiles[label] = {"user_data_dir": str(root), "profile_directory": "Default"}
            full["chrome_profiles"] = profiles
            full["selected_chrome_profile"] = label
            self._write_full(full)
            return self.profile_public()

    def connect_profile(self, label: str) -> dict[str, object]:
        """Register one private root without changing the global legacy selection."""
        root = self.app_profile_root(label)
        if not (root / "Default").is_dir():
            raise ValueError("PROFILE_DIRECTORY_MISSING")
        with self._lock:
            full = self._read_full()
            profiles = full.get("chrome_profiles", {})
            if not isinstance(profiles, dict):
                profiles = {}
            profiles[label] = {"user_data_dir": str(root), "profile_directory": "Default"}
            full["chrome_profiles"] = profiles
            self._write_full(full)
            return {"label": label, "user_data_dir": str(root),
                    "profile_directory": "Default", "configured": True}

    def save_ai(self, provider: str, model: str, api_key: str,
                *, clear_key: bool = False) -> dict[str, object]:
        if provider not in PROVIDERS:
            raise ValueError("AI_PROVIDER_INVALID")
        validate_model(model)
        if (not isinstance(api_key, str) or len(api_key) > 4096
                or any(ord(char) < 33 or ord(char) > 126 for char in api_key)):
            raise ValueError("AI_KEY_INVALID")
        if clear_key and api_key:
            raise ValueError("AI_KEY_INVALID")
        with self._lock:
            full = self._read_full()
            values = self._read_ai_env()
            name = PROVIDERS[provider][1]
            if clear_key:
                values.pop(name, None)
            elif api_key:
                values[name] = api_key
            self._write_ai_env(values)
            full["ai"] = {"provider": provider, "model": model}
            self._write_full(full)
            return self.ai_public()

    def save_channels(self, channels: list[str], *, forbidden_channels=()) -> list[str]:
        current_names = self.channels()
        entries = [{"channel_name": current_names.get(channel_id) or CHANNELS.get(channel_id) or channel_id,
                    "channel_id": channel_id} for channel_id in channels]
        self.save_channel_entries(entries, forbidden_channels=forbidden_channels)
        return list(self._current["channels"])

    def save_channel_entries(self, entries: list[dict[str, str]], *, forbidden_channels=()) -> list[dict[str, str]]:
        if (not isinstance(entries, list) or not 5 <= len(entries) <= 20
                or any(not isinstance(item, dict) or set(item) != {"channel_name", "channel_id"}
                       for item in entries)):
            raise ValueError("SETTINGS_CHANNELS_INVALID")
        normalized = []
        for item in entries:
            name = item["channel_name"].strip() if isinstance(item["channel_name"], str) else ""
            channel_id = item["channel_id"].strip() if isinstance(item["channel_id"], str) else ""
            if name and not CHANNEL_NAME.fullmatch(name):
                raise ValueError("SETTINGS_CHANNEL_NAME_INVALID")
            if not CHANNEL_ID.fullmatch(channel_id):
                raise ValueError("SETTINGS_CHANNEL_ID_INVALID")
            normalized.append({"channel_name": name, "channel_id": channel_id})
        ids = [item["channel_id"] for item in normalized]
        if len(set(ids)) != len(ids):
            raise ValueError("SETTINGS_CHANNELS_INVALID")
        if set(ids) & set(forbidden_channels):
            raise ValueError("SETTINGS_TEST_CHANNEL_CONFLICT")
        with self._lock:
            source = {**self._current, "channels": ids}
            validated = self._validate(source)
            full = self._read_full()
            full.update({key: validated[key] for key in ("profiles", "channels")})
            full["comment"] = {**full.get("comment", {}), **validated["comment"]}
            full["limits"] = {**full.get("limits", {}), **validated["limits"]}
            full["channel_names"] = {item["channel_id"]: item["channel_name"] for item in normalized}
            self._write_full(full)
            self._current = validated
            return normalized

    def yaml_text(self) -> str:
        with self._lock:
            current = self._current
            rows = ["profiles: [" + ", ".join(json.dumps(item, ensure_ascii=False)
                                                for item in current["profiles"]) + "]  # Chrome labels",
                    "channels:  # 불러오기 · 게시 허용 범위"]
            for channel_id in current["channels"]:
                label = CHANNELS.get(channel_id, "")
                rows.append(f"  - {channel_id}" + (f"  # {label}" if label else ""))
            rows.extend(["comment: { min_chars: 40, max_chars: 120, brand: 운명원 }",
                         "limits: { daily_max_comments: 10 }", ""])
            return "\n".join(rows)

    def save_yaml(self, source: str, *, forbidden_channels=()) -> str:
        if not isinstance(source, str) or len(source.encode("utf-8")) > 8192:
            raise ValueError("SETTINGS_TOO_LARGE")
        try:
            parsed = yaml.safe_load(source)
        except yaml.YAMLError as exc:
            raise ValueError("SETTINGS_YAML_INVALID") from exc
        if not isinstance(parsed, dict) or set(parsed) != set(self.DEFAULT):
            raise ValueError("SETTINGS_FIELDS_INVALID")
        normalized = self._validate(parsed)
        if set(normalized["channels"]) & set(forbidden_channels):
            raise ValueError("SETTINGS_TEST_CHANNEL_CONFLICT")
        with self._lock:
            full = self._read_full()
            full.update({key: normalized[key] for key in ("profiles", "channels")})
            full["comment"] = {**full.get("comment", {}), **normalized["comment"]}
            full["limits"] = {**full.get("limits", {}), **normalized["limits"]}
            self._write_full(full)
            self._current = normalized
            return self.yaml_text()

    def _write_full(self, full: dict) -> None:
        data = yaml.safe_dump(full, allow_unicode=True, sort_keys=False)
        temp_dir = self.path.parent / "data" / "dashboard"
        temp_dir.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=temp_dir)
        try:
            os.chmod(temporary, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if self.path.is_symlink():
                raise ValueError("SETTINGS_SYMLINK_BLOCKED")
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


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
            result = create_ai_client(provider, model, key).complete_json(
                "You draft Korean YouTube comments. Return only compact JSON with the required fields. Never claim to have used a service.",
                json.dumps({
                    "evidence": evidence.text,
                    "sources": evidence.sources,
                    "instruction": "Use only evidence. Return worry_summary, cited_detail, comment. "
                    "The cited_detail must be an exact phrase from evidence and also appear in comment. "
                    "Write a distinct 40-120 Korean character viewer-perspective comment. Include 운명원 and 사주 naturally. "
                    "No links, hashtags, fabricated testimonials, or invented people, scenes, or quotes.",
                }, ensure_ascii=False),
                response_schema=DRAFT_RESPONSE_SCHEMA,
            )
            record = save_generated(card, result, self.drafts_dir, source_text=evidence.text,
                                    evidence_sources=evidence.sources, profile=profile)
            return {key: record[key] for key in ("video_id", "worry_summary", "cited_detail", "comment", "evidence_sources")} | {"evidence_notice": evidence.notice}

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


def _page(token: str, *, demo: bool = False) -> bytes:
    page = base_page(token).decode("utf-8")
    profile_markup = """
<style>.profile-dialog{border:0;border-radius:16px;padding:0;width:min(620px,calc(100vw - 32px));max-height:85dvh}.profile-dialog::backdrop{background:rgba(20,37,58,.55)}.profile-dialog form{padding:22px;overflow:auto;max-height:85dvh}.profile-dialog h2{margin-top:0}.profile-dialog menu{display:flex;gap:8px;justify-content:flex-end;padding:0;margin:18px 0 0}.profile-dialog menu button{margin:0}.profile-help{color:#526176;font-size:.9rem}.profile-list{display:grid;gap:10px;margin:16px 0;max-height:330px;overflow-y:auto;overscroll-behavior:contain;padding-right:6px}.profile-row{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:96px;padding:12px;border:2px solid #b6c4d3;border-radius:10px}.profile-row.selected{background:#e8f3ff;border-color:#1768b6}.profile-row strong,.profile-row span{display:block}.profile-row button{margin:0;white-space:nowrap}.profile-row span{font-size:.85rem;color:#36516f}.profile-info{flex:1;min-width:200px}.profile-heading{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.profile-change{font-size:.75rem;padding:4px 8px;min-height:28px}.profile-email{max-width:260px;min-width:150px;flex:1;margin:0!important}.profile-add-form{display:flex;align-items:end;gap:8px;margin-top:10px;padding:12px;background:#f2f6fc;border-radius:10px}.profile-add-form[hidden]{display:none}.profile-add-form label{flex:1;font-weight:650}.profile-add-form input{display:block;width:100%;min-height:44px;margin-top:6px;padding:9px;border:1px solid #8b9bb0;border-radius:8px;font:inherit}</style>
<dialog id="profile-dialog" class="profile-dialog" aria-labelledby="profile-title"><form method="dialog"><h2 id="profile-title" tabindex="-1">앱 전용 Chrome 프로필</h2><p class="profile-help">현재 계정 확인은 해당 전용 Chrome에서 실제 YouTube 로그인 계정을 확인합니다. 로그아웃이 명확할 때만 계정 선택 창을 엽니다. 확인할 수 없는 상태에서는 자동 로그인하지 않습니다.</p><div id="profile-list" class="profile-list" role="list" aria-label="앱 전용 프로필 목록"></div><button id="profile-setup" type="button">미연결 프로필 추가</button><div id="profile-add-form" class="profile-add-form" hidden><label for="profile-add-name">새 프로필 이름<input id="profile-add-name" type="text" maxlength="30" autocomplete="off" placeholder="예: 브랜드 계정"></label><button id="profile-add-save" type="button">등록</button><button id="profile-add-cancel" type="button" class="secondary">취소</button></div><p id="profile-state" class="status" role="status" aria-live="polite"></p><menu><button id="profile-cancel" type="button">닫기</button></menu></form></dialog>
"""
    page = page.replace("<script>", profile_markup + "<script>", 1)
    page = page.replace('<div id="capture"></div>', '<button id="post-continue" type="button" hidden>댓글 계속하기</button><div id="capture"></div>', 1)
    advanced_panel = ""
    reason_labels = """
const reasonText={
  TEST_FEED_UNAVAILABLE:'테스트 영상 채널 RSS 조회 실패: 네트워크를 확인하고 다시 선택하세요. 게시하지 않았습니다.',
  TEST_VIDEO_NOT_IN_FEED:'테스트 영상이 채널 RSS에 없습니다. 최신 목록 범위 밖일 수 있어 게시하지 않았습니다.',
  TEST_VIDEO_CHANGED:'테스트 영상의 채널 또는 제목이 등록 정보와 다릅니다. 확인 후 다시 등록하세요.',
  AI_EMPTY_RESPONSE:'AI가 빈 응답을 반환했습니다. 잠시 후 다시 시도하거나 모델 설정을 확인하세요.',
  AI_RESPONSE_INVALID:'AI 응답이 초안 JSON 형식이 아닙니다. 모델 설정을 확인하고 다시 시도하세요.',
  PROFILE_LOCKED:'앱 전용 Chrome 창이 열려 있습니다. 창을 닫은 뒤 다시 확인하세요.',
  PROFILE_EMAIL_VIDEO_UNAVAILABLE:'계정을 확인할 허용 영상이 없습니다. 허용 채널과 네트워크를 확인한 뒤 다시 시도하세요.',
  PROFILE_EMAIL_NOT_VISIBLE:'YouTube 계정 메뉴에서 현재 계정 이메일을 확인하지 못했습니다. 로그인 상태를 확인하세요.',
  PROFILE_SIGNED_OUT:'YouTube 로그아웃 상태가 확인됐습니다.',
  PROFILE_ACCOUNT_UNKNOWN:'현재 YouTube 로그인 상태를 정확히 확인하지 못했습니다.',
  PROFILE_NAME_DUPLICATE:'이미 사용 중인 프로필 이름입니다.',
  PROFILE_NAME_INVALID:'프로필 이름은 1~30자로 입력하고 경로 문자는 제외하세요.',
  PROFILE_LIMIT_REACHED:'프로필은 최대 20개까지 등록할 수 있습니다.',
  BROWSER_LAUNCH_FAILED:'Chrome을 열지 못했습니다. 앱 전용 Chrome 창을 모두 정상 종료한 뒤 영상을 다시 선택해 시도하세요. 계속 실패하면 Chrome 실행 상태를 확인하세요.',
  DEMO_NO_POST:'실제 게시 없음'
};
const explainReason=code=>reasonText[code]||code;
const stateText=state=>({posted:'게시 확인',simulated:'연습 완료',blocked:'게시 차단'}[state]||state);
"""
    page = page.replace("</script>", reason_labels + "</script>")
    page = page.replace("'게시 불가: '+draft.reason_code", "'게시 불가: '+explainReason(draft.reason_code)")
    page = page.replace("[result.state,result.reason_code,result.message]",
                        "[stateText(result.state),explainReason(result.reason_code),result.message]")
    if demo:
        banner = ('<aside role="status" style="padding:12px 24px;background:#fff1ba;'
                  'color:#332600;font-weight:700">오프라인 연습 모드: 예시 자료만 표시합니다. '
                  'YouTube 요청·게시용 Chrome 프로필 실행·DB 예약·실제 게시를 하지 않습니다.</aside>')
        page = page.replace("</header>", "</header>" + banner, 1)
        page = page.replace("설정된 채널의 최신 영상을 확인합니다.",
                            "가상 영상으로 세 단계 조작을 연습합니다.", 1)
        page = page.replace("image.src=video.thumbnail_url;",
                            "if(video.thumbnail_url)image.src=video.thumbnail_url;else image.hidden=true;", 1)
    dialog_style = """
header{position:relative;padding-right:118px}#options-open{position:absolute;right:clamp(16px,3vw,40px);top:25px;background:#fff;color:#14253a;border-color:#fff}.options-menu{position:absolute;right:clamp(16px,3vw,40px);top:76px;z-index:10;width:190px;padding:6px;border:1px solid #d9e2ed;border-radius:12px;background:white;box-shadow:0 18px 42px rgba(10,25,45,.25)}.options-menu[hidden]{display:none}.options-menu button{display:block;width:100%;padding:12px;text-align:left;background:white;color:#14253a;border:0;border-radius:8px}.options-menu button:hover,.options-menu button:focus-visible{background:#eaf2ff}
dialog.channel-dialog{width:min(720px,calc(100vw - 24px));max-height:min(720px,85dvh);padding:0;border:1px solid #d9e2ed;border-radius:18px;box-shadow:0 28px 80px rgba(10,25,45,.3);color:#14253a;overflow:hidden}
dialog.channel-dialog[open]{display:grid;grid-template-rows:auto minmax(0,1fr) auto}dialog.channel-dialog::backdrop{background:rgba(10,24,43,.6)}
.dialog-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:16px 20px;background:#f2f6fc;color:#14253a;border-bottom:1px solid #d9e2ed}.dialog-head h2{margin:0}.dialog-head button,.dialog-actions .secondary,.channel-row button.secondary{background:white;color:#174ea6}
.dialog-scroll{overflow-y:auto;overscroll-behavior:contain;padding:14px 20px}.dialog-actions{display:flex;justify-content:flex-end;align-items:center;gap:10px;padding:12px 20px;background:white;border-top:1px solid #d9e2ed}.channel-row{display:grid;grid-template-columns:minmax(150px,1fr) minmax(210px,1.35fr) auto auto;align-items:end;gap:8px;margin:12px 0;padding:12px;border:1px solid #d9e2ed;border-radius:12px}.channel-row label{display:block;font-weight:650}.channel-row input,.channel-row select{display:block;width:100%;min-height:44px;margin-top:6px;padding:9px;border:1px solid #8b9bb0;border-radius:8px;font:inherit}.channel-row .row-state{grid-column:1/-1;margin:0;font-size:.9rem}.channel-row .candidate-box{display:flex;align-items:end;gap:8px;margin-top:8px}.channel-row .candidate-box select{flex:1}.channel-row button{white-space:nowrap}.channel-count{color:#526176}.demo-hint{background:#fff1ba;padding:10px;border-radius:8px}
.ai-field{display:block;margin:16px 0;font-weight:650}.ai-field[hidden]{display:none}.ai-field select,.ai-field input{display:block;width:100%;min-height:44px;margin-top:6px;padding:9px;border:1px solid #8b9bb0;border-radius:8px;font:inherit}.ai-check{display:flex;align-items:center;gap:8px;min-height:44px}.ai-help{color:#526176;font-size:.95rem}.ai-key-status{padding:10px;border-radius:8px;background:#eef5ff}.ai-dialog .dialog-actions{flex-wrap:wrap}.ai-dialog .dialog-actions #ai-test{margin-right:auto}
@media(max-width:720px){header{padding-right:90px}#options-open{right:16px;top:18px;padding:8px}.channel-row{grid-template-columns:1fr 1fr}.channel-row label{grid-column:1/-1}.channel-row button{width:100%}.dialog-actions{flex-wrap:wrap}}
"""
    page = page.replace("</style>", dialog_style + "</style>", 1)
    page = page.replace("</header>",
                        '''<button id="options-open" type="button" aria-haspopup="menu" aria-controls="options-menu" aria-expanded="false">옵션</button>
<div id="options-menu" class="options-menu" role="menu" hidden><button id="channel-menu-open" type="button" role="menuitem">채널 관리</button><button id="profile-menu-open" type="button" role="menuitem">Chrome 프로필 관리</button><button id="ai-menu-open" type="button" role="menuitem">AI API 관리</button></div></header>''', 1)
    dialog_html = '''<dialog id="channel-dialog" class="channel-dialog" aria-labelledby="channel-title">
<div class="dialog-head"><h2 id="channel-title" tabindex="-1">채널 관리</h2><button id="channel-close" type="button" class="secondary" aria-label="채널 관리 닫기">닫기</button></div>
<div class="dialog-scroll"><p>채널 ID는 필수입니다. 채널명은 선택 사항이며, 비워 두면 연결 테스트에서 RSS의 채널명을 확인해 채웁니다. 연결 테스트는 채널 소유권을 증명하지 않습니다.</p>
<p id="channel-count" class="channel-count" role="status"></p><div id="channel-rows"></div>
<button id="channel-add" type="button" class="secondary">+ 채널 추가</button>
<p id="channel-state" class="status" role="status" aria-live="polite"></p></div>
<div class="dialog-actions"><button id="channel-cancel" type="button" class="secondary">취소</button><button id="channel-save" type="button">채널 저장</button></div>
</dialog>'''
    page = page.replace('<ol class="workflow"', dialog_html + '<ol class="workflow"', 1)
    ai_dialog = '''<dialog id="ai-dialog" class="channel-dialog ai-dialog" aria-labelledby="ai-title">
<div class="dialog-head"><h2 id="ai-title" tabindex="-1">AI API 관리</h2><button id="ai-close" type="button" class="secondary" aria-label="AI API 관리 닫기">닫기</button></div>
<div class="dialog-scroll"><p>제공사와 모델을 선택하고 API 키를 로컬에 저장합니다. 연결 테스트는 저장 후 직접 누를 때만 AI에 요청합니다. 댓글 초안 생성과 게시는 이 화면에서 실행되지 않습니다.</p>
<label class="ai-field" for="ai-provider">AI 제공사<select id="ai-provider"><option value="openai">GPT · OpenAI</option><option value="gemini">Gemini · Google</option><option value="claude">Claude · Anthropic</option><option value="grok">Grok · xAI</option></select></label>
<label class="ai-field" for="ai-model-choice">모델 ID<select id="ai-model-choice"></select></label>
<label class="ai-field" for="ai-model-custom" id="ai-custom-wrap" hidden>직접 입력할 모델 ID<input id="ai-model-custom" type="text" maxlength="80" autocomplete="off" spellcheck="false" placeholder="제공사의 정확한 모델 ID"></label>
<p class="ai-help">모델 ID는 제공사별로 바뀔 수 있습니다. 목록에 없다면 직접 입력을 선택하세요.</p>
<label class="ai-field" for="ai-key">API 키 · 새 키로 교체할 때만 입력<input id="ai-key" type="password" maxlength="4096" autocomplete="off" spellcheck="false" placeholder="비워 두면 같은 제공사의 저장된 키 유지"></label>
<p id="ai-key-status" class="ai-key-status" role="status"></p>
<label class="ai-check"><input id="ai-clear-key" type="checkbox"> 저장된 로컬 키 삭제</label>
<p class="ai-help">다른 제공사로 바꾸면 이전 키는 재사용하지 않습니다. 환경변수 키는 이 화면에서 삭제할 수 없습니다.</p>
<label class="ai-field" for="youtube-key">YouTube Data API 키 · 새 키로 교체할 때만 입력<input id="youtube-key" type="password" maxlength="256" autocomplete="off" spellcheck="false" placeholder="기존 키는 표시하지 않습니다"></label><button id="youtube-key-save" type="button" class="secondary">YouTube 키 저장</button><p id="ai-state" class="status" role="status" aria-live="polite"></p></div>
<div class="dialog-actions"><button id="ai-test" type="button" class="secondary">AI 연결 테스트</button><button id="ai-cancel" type="button" class="secondary">취소</button><button id="ai-save" type="button">AI 설정 저장</button></div>
</dialog>'''
    page = page.replace('<ol class="workflow"', ai_dialog + '<ol class="workflow"', 1)
    channel_script = """
const demoChannels=__DEMO_CHANNELS__;
const demoMode=__DEMO_MODE__;
const channelPattern=/^UC[A-Za-z0-9_-]{22}$/;
const channelErrors={SETTINGS_CHANNELS_INVALID:'채널은 5~20개여야 하며 ID가 중복되면 안 됩니다.',SETTINGS_CHANNEL_NAME_INVALID:'채널명은 비워두거나 1~100자로 입력하세요.',SETTINGS_CHANNEL_ID_INVALID:'채널 ID는 UC로 시작하는 24자리여야 합니다.',SETTINGS_TEST_CHANNEL_CONFLICT:'본인 테스트 영상의 채널은 중복 등록할 수 없습니다.',SETTINGS_WRITE_FAILED:'설정 파일을 저장하지 못했습니다.',RSS_CHANNEL_MISMATCH:'RSS가 다른 채널 ID를 반환했습니다.',RSS_INVALID_XML:'RSS 응답 형식이 올바르지 않습니다.',RSS_REDIRECT_BLOCKED:'RSS가 다른 주소로 이동해 연결을 차단했습니다.',CHANNEL_TEST_NETWORK_FAILED:'YouTube RSS에 연결하지 못했습니다.',CHANNEL_TEST_FAILED:'RSS 연결 확인에 실패했습니다.'};
let savedChannels=[],draftChannels=[],visibleRows=3,previousOverflow='';
const dialog=$('channel-dialog');
const optionsMenu=$('options-menu');
function closeOptions(){optionsMenu.hidden=true;$('options-open').setAttribute('aria-expanded','false');}
$('options-open').addEventListener('click',()=>{const opening=optionsMenu.hidden;optionsMenu.hidden=!opening;$('options-open').setAttribute('aria-expanded',String(opening));if(opening)$('channel-menu-open').focus();});
document.addEventListener('click',event=>{if(!optionsMenu.hidden&&!optionsMenu.contains(event.target)&&event.target!==$('options-open'))closeOptions();});
document.addEventListener('keydown',event=>{if(optionsMenu.hidden)return;if(event.key==='Escape'){event.preventDefault();closeOptions();$('options-open').focus();}if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();const items=[$('channel-menu-open'),$('profile-menu-open'),$('ai-menu-open')];const offset=event.key==='ArrowDown'?1:-1;items[(items.indexOf(document.activeElement)+offset+items.length)%items.length].focus();}});
function channelMessage(message,bad=false){const state=$('channel-state');state.textContent=message;state.classList.toggle('error',bad);}
function rowValid(item){return channelPattern.test(item.channel_id?.trim()||'');}
function updateChannelSaveGuide(){const ids=draftChannels.map(item=>item.channel_id.trim());const valid=draftChannels.length>=5&&draftChannels.length<=20&&draftChannels.every(rowValid)&&new Set(ids).size===ids.length;guideButton($('channel-save'),demoMode?'연습 모드에서는 채널 설정을 저장할 수 없습니다.':valid?'':'채널 ID 5~20개를 중복 없이 입력해주세요.');}
async function testChannel(i,nameInput,idInput,state,test){
  const name=nameInput.value.trim(),id=idInput.value.trim();state.replaceChildren();state.className='row-state muted';
  if(!channelPattern.test(id)){state.textContent='채널 ID는 UC로 시작하는 24자리여야 합니다.';state.className='row-state error';return;}
  guideButton(test,'YouTube RSS를 확인하는 중입니다.');
  try{
    const data=await json(await fetch('/api/channels/test',{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':token},body:JSON.stringify({channel_name:name,channel_id:id})}));
    const resolved=name||data.channel_name||'';if(!name&&resolved)nameInput.value=resolved;state.textContent='연결 확인 · '+(resolved||id)+' · 최근 항목 '+data.video_count+'개 (소유권 확인 아님)';draftChannels[i]={channel_name:resolved,channel_id:id};
  }catch(error){state.textContent=channelErrors[error.message]||'연결 실패: '+error.message;state.className='row-state error';}
  finally{guideButton(test,demoMode?'연습 모드에서는 연결 테스트를 할 수 없습니다.':'');updateChannelSaveGuide();}
}
function renderChannels(){
  const rows=$('channel-rows');rows.replaceChildren();$('channel-count').textContent='현재 '+savedChannels.length+'개 등록 · '+visibleRows+'개 표시';$('channel-add').hidden=visibleRows>=20;
  for(let i=0;i<visibleRows;i++){
    const item=draftChannels[i]||{channel_name:'',channel_id:''};const row=document.createElement('div');row.className='channel-row';
    const idLabel=document.createElement('label');idLabel.textContent=(i+1)+'번째 채널 ID (필수)';idLabel.htmlFor='channel-id-'+i;const idInput=document.createElement('input');idInput.id=idLabel.htmlFor;idInput.value=item.channel_id||'';idInput.maxLength=24;idInput.placeholder='UC로 시작하는 24자리';idInput.autocomplete='off';idInput.spellcheck=false;idInput.readOnly=demoMode;idLabel.append(idInput);
    const nameLabel=document.createElement('label');nameLabel.textContent='채널명 (선택)';nameLabel.htmlFor='channel-name-'+i;const nameInput=document.createElement('input');nameInput.id=nameLabel.htmlFor;nameInput.value=item.channel_name||'';nameInput.maxLength=100;nameInput.autocomplete='off';nameInput.placeholder='비워두면 연결 테스트에서 확인';nameInput.readOnly=demoMode;nameLabel.append(nameInput);
    const state=document.createElement('div');state.className='row-state muted';state.setAttribute('role','status');const test=document.createElement('button');test.type='button';test.className='secondary';test.textContent='연결 테스트';guideButton(test,demoMode?'연습 모드에서는 연결 테스트를 할 수 없습니다. 실제 대시보드를 열어주세요.':'');
    const changed=()=>{draftChannels[i]={channel_name:nameInput.value.trim(),channel_id:idInput.value.trim()};state.replaceChildren();updateChannelSaveGuide();};nameInput.addEventListener('input',changed);idInput.addEventListener('input',changed);test.addEventListener('click',()=>testChannel(i,nameInput,idInput,state,test));
    row.append(idLabel,nameLabel,test);if(i>=5){const remove=document.createElement('button');remove.type='button';remove.className='secondary';remove.textContent='행 삭제';guideButton(remove,demoMode?'연습 모드에서는 채널을 삭제할 수 없습니다.':'');remove.addEventListener('click',()=>{draftChannels.splice(i,1);visibleRows--;renderChannels();});row.append(remove);}row.append(state);rows.append(row);
  }updateChannelSaveGuide();
}
async function refreshChannels(){if(demoMode){savedChannels=demoChannels.map(item=>({...item}));return;}const result=await json(await fetch('/api/channels',{headers:{'X-Session-Token':token}}));if(!Array.isArray(result.entries))throw Error('CHANNEL_LIST_INVALID');savedChannels=result.entries.map(item=>({...item}));}
$('channel-menu-open').addEventListener('click',async()=>{closeOptions();previousOverflow=document.body.style.overflow;document.body.style.overflow='hidden';dialog.showModal();$('channel-title').focus();channelMessage('채널 설정을 불러오는 중입니다…');try{await refreshChannels();draftChannels=savedChannels.map(item=>({...item}));visibleRows=Math.max(3,draftChannels.length);renderChannels();channelMessage(demoMode?'연습 모드: 실제 저장과 연결 테스트를 하지 않습니다.':'채널명과 선택 채널 ID를 확인하세요.');}catch(error){channelMessage('채널 설정을 불러오지 못했습니다: '+error.message,true);}});
function closeChannels(){dialog.close();}$('channel-close').addEventListener('click',closeChannels);$('channel-cancel').addEventListener('click',closeChannels);dialog.addEventListener('close',()=>{document.body.style.overflow=previousOverflow;$('options-open').focus();});
$('channel-add').addEventListener('click',()=>{if(visibleRows>=20)return;if(visibleRows>=draftChannels.length)draftChannels.push({channel_name:'',channel_id:''});visibleRows++;renderChannels();$('channel-id-'+(visibleRows-1)).focus();});
$('channel-save').addEventListener('click',async()=>{const ids=draftChannels.map(item=>item.channel_id.trim());if(draftChannels.length<5||draftChannels.length>20||!draftChannels.every(rowValid)||new Set(ids).size!==ids.length){channelMessage('채널 ID 5~20개를 중복 없이 입력하세요.',true);return;}guideButton($('channel-save'),'채널 설정을 저장하는 중입니다.');channelMessage('채널 설정을 저장하는 중입니다…');try{const result=await json(await fetch('/api/channels',{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':token},body:JSON.stringify({entries:draftChannels})}));savedChannels=result.entries.map(item=>({...item}));draftChannels=savedChannels.map(item=>({...item}));visibleRows=draftChannels.length;renderChannels();selected=null;ready=false;setStep('load');guideButton($('post'),'채널 설정이 바뀌었습니다. 영상을 다시 불러오고 초안을 승인해주세요.');$('videos').replaceChildren();$('selection').className='empty';$('selection').textContent='설정이 바뀌었습니다. 영상을 다시 불러오세요.';$('feed-state').textContent='채널 설정이 저장됐습니다. 영상을 다시 불러오세요.';$('post-state').textContent='승인된 초안을 다시 선택해야 합니다.';channelMessage('저장했습니다. 영상 목록을 다시 불러오세요.');}catch(error){channelMessage(channelErrors[error.message]||'저장 실패: '+error.message,true);}finally{updateChannelSaveGuide();}});
""".replace("__DEMO_CHANNELS__", json.dumps(
        [{"channel_name": name, "channel_id": channel_id} for channel_id, name in CHANNELS.items()],
        ensure_ascii=False)).replace(
        "__DEMO_MODE__", "true" if demo else "false")
    page = page.replace("</script>", channel_script + "</script>")
    ai_script = """
const aiDemo=__AI_DEMO__;
const aiPresets={
  openai:[{id:'gpt-5.4-mini',label:'GPT-5.4 mini · 균형',recommended:true},{id:'gpt-5-mini',label:'GPT-5 mini · 빠른 초안'},{id:'gpt-5-nano',label:'GPT-5 nano · 저비용'}],
  gemini:[{id:'gemini-3.5-flash',label:'Gemini 3.5 Flash · 균형',recommended:true},{id:'gemini-3.5-flash-lite',label:'Gemini 3.5 Flash-Lite · 저비용'},{id:'gemini-2.5-flash',label:'Gemini 2.5 Flash · 기존 계정용'}],
  claude:[{id:'claude-sonnet-4-6',label:'Claude Sonnet 4.6 · 균형',recommended:true},{id:'claude-haiku-4-5',label:'Claude Haiku 4.5 · 빠른 초안'}],
  grok:[{id:'grok-4.7',label:'Grok 4.7 · 균형',recommended:true},{id:'grok-4-1-fast-reasoning',label:'Grok 4.1 Fast Reasoning · 빠른 초안'},{id:'grok-4-1-fast-non-reasoning',label:'Grok 4.1 Fast Non-reasoning · 저비용'}]
};
const aiErrors={AI_PROVIDER_INVALID:'AI 제공사를 선택하세요.',AI_MODEL_INVALID:'제공사의 정확한 모델 ID를 입력하세요.',AI_KEY_INVALID:'API 키 형식을 확인하세요.',AI_KEY_MISSING:'선택한 AI 제공사의 API 키가 없습니다. 프로젝트 루트 .env 또는 AI API 관리에서 키를 설정하세요.',AI_AUTH_FAILED:'API 인증 또는 사용 권한을 확인하세요.',AI_MODEL_UNAVAILABLE:'모델 ID 또는 계정의 모델 접근 권한을 확인하세요.',AI_RATE_LIMITED:'AI 호출 한도에 도달했습니다.',AI_NETWORK_FAILED:'AI 서비스에 연결하지 못했습니다.',AI_REDIRECT_BLOCKED:'AI API 주소 이동을 차단했습니다.',AI_PROVIDER_FAILED:'AI 서비스 요청이 실패했습니다.',AI_EMPTY_RESPONSE:'AI가 빈 응답을 반환했습니다. 잠시 후 다시 시도하세요.',AI_RESPONSE_INVALID:'AI 응답의 JSON 형식을 확인할 수 없습니다.',AI_RESPONSE_TRUNCATED:'AI가 응답을 끝까지 만들기 전에 토큰 한도에 도달했습니다. 다시 시도하세요.',AI_RESPONSE_SCHEMA_INVALID:'AI 응답에 필요한 고민·근거·댓글 항목이 없습니다. 모델 설정을 확인하고 다시 시도하세요.',AI_RESPONSE_TOO_LARGE:'AI 응답이 너무 큽니다.',AI_TEST_FAILED:'AI 연결 테스트에 실패했습니다.',SETTINGS_WRITE_FAILED:'설정 파일을 저장하지 못했습니다.'};
let aiCurrent=null,aiDirty=false,aiPreviousOverflow='';
const aiDialog=$('ai-dialog');
async function checkAiDraftAvailability(button){
  if(aiDemo){guideButton(button,'연습 모드에서는 AI 초안을 만들 수 없습니다. 실제 대시보드를 열어주세요.');return;}
  try{const state=await json(await fetch('/api/ai',{headers:{'X-Session-Token':token}}));
    if(document.body.contains(button))guideButton(button,state.has_key?'':'우측 상단의 옵션 → AI API 관리에서 AI API 키를 입력해주세요.');
  }catch(_){if(document.body.contains(button))guideButton(button,'AI 설정을 확인하지 못했습니다. 페이지를 새로고침해주세요.');}
}
function aiMessage(message,bad=false){const state=$('ai-state');state.textContent=message;state.classList.toggle('error',bad);}
function aiModelValue(){return $('ai-model-choice').value==='custom'?$('ai-model-custom').value.trim():$('ai-model-choice').value;}
function aiPopulateModels(provider,model){
  const select=$('ai-model-choice');select.replaceChildren();
  for(const preset of aiPresets[provider]){const option=document.createElement('option');option.value=preset.id;option.textContent=preset.label+(preset.recommended?' · 추천':'');select.append(option);}
  const custom=document.createElement('option');custom.value='custom';custom.textContent='직접 입력…';select.append(custom);
  if(aiPresets[provider].some(preset=>preset.id===model)){select.value=model;$('ai-model-custom').value='';}
  else{select.value='custom';$('ai-model-custom').value=model;}
  $('ai-custom-wrap').hidden=select.value!=='custom';
}
function aiUpdateKeyStatus(){
  const same=aiCurrent&&$('ai-provider').value===aiCurrent.provider;
  if(!same){$('ai-key-status').textContent='제공사를 바꾸면 이전 제공사의 키는 재사용하지 않습니다.';return;}
  const source=aiCurrent.key_source;
  $('ai-key-status').textContent=source==='local'?'로컬 키가 설정되어 있습니다. 값은 표시하지 않습니다.':source==='environment'?'환경변수 키가 설정되어 있습니다. 값은 표시하지 않습니다.':'설정된 API 키가 없습니다.';
}
function aiMarkDirty(){aiDirty=true;guideButton($('ai-test'),'AI 설정을 저장한 뒤 연결 테스트를 눌러주세요.');const model=aiModelValue();const conflict=$('ai-clear-key').checked&&Boolean($('ai-key').value);guideButton($('ai-save'),aiDemo?'연습 모드에서는 AI 설정을 저장할 수 없습니다.':conflict?'새 키 입력과 저장된 키 삭제 중 하나만 선택해주세요.':/^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(model)?'':'제공사의 정확한 모델 ID를 입력해주세요.');aiUpdateKeyStatus();aiMessage('변경 내용을 저장한 뒤 연결 테스트를 실행하세요.');}
async function aiRefresh(){
  aiCurrent=aiDemo?{provider:'openai',model:'gpt-5.4-mini',has_key:false,key_source:'none'}:
    await json(await fetch('/api/ai',{headers:{'X-Session-Token':token}}));
  $('ai-provider').value=aiCurrent.provider;aiPopulateModels(aiCurrent.provider,aiCurrent.model);
  $('ai-key').value='';$('ai-clear-key').checked=false;aiDirty=false;aiUpdateKeyStatus();
  guideButton($('ai-save'),aiDemo?'연습 모드에서는 AI 설정을 저장할 수 없습니다. 실제 대시보드를 열어주세요.':'');guideButton($('ai-test'),aiDemo?'연습 모드에서는 AI 연결 테스트를 할 수 없습니다.':!aiCurrent.has_key?'선택한 AI 제공사의 API 키를 입력하고 저장해주세요.':'');
  $('ai-key').disabled=aiDemo;$('ai-clear-key').disabled=aiDemo;
  aiMessage(aiDemo?'연습 모드: 설정 저장과 AI 외부 호출을 하지 않습니다.':'모델과 키를 확인한 뒤 저장하세요. 연결 테스트는 API 요청 한 건을 사용합니다.');
}
$('youtube-key-save').addEventListener('click',async()=>{const key=$('youtube-key').value.trim();if(!key){aiMessage('새 YouTube Data API 키를 입력하세요.',true);return;}try{await localPost('/api/youtube-key',{api_key:key});$('youtube-key').value='';aiMessage('YouTube 키를 저장했습니다. 다음 초안 생성부터 적용됩니다.');}catch(error){aiMessage('YouTube 키 저장 실패: '+error.message,true);}});
$('ai-menu-open').addEventListener('click',async()=>{
  closeOptions();aiPreviousOverflow=document.body.style.overflow;document.body.style.overflow='hidden';
  aiDialog.showModal();$('ai-title').focus();aiMessage('AI 설정을 불러오는 중입니다…');
  guideButton($('ai-save'),'AI 설정을 불러오는 중입니다. 잠시 기다려주세요.');guideButton($('ai-test'),'AI 설정을 불러오는 중입니다. 잠시 기다려주세요.');
  try{await aiRefresh();}catch(_){aiMessage('AI 설정을 불러오지 못했습니다.',true);guideButton($('ai-save'),'AI 설정을 불러오지 못했습니다. 대시보드를 새로고침해주세요.');guideButton($('ai-test'),'AI 설정을 불러오지 못했습니다. 대시보드를 새로고침해주세요.');}
});
function aiClose(){aiDialog.close();}
$('ai-close').addEventListener('click',aiClose);$('ai-cancel').addEventListener('click',aiClose);
aiDialog.addEventListener('close',()=>{$('ai-key').value='';document.body.style.overflow=aiPreviousOverflow;$('options-open').focus();});
$('ai-provider').addEventListener('change',()=>{const presets=aiPresets[$('ai-provider').value];aiPopulateModels($('ai-provider').value,(presets.find(preset=>preset.recommended)||presets[0]).id);aiMarkDirty();});
$('ai-model-choice').addEventListener('change',()=>{$('ai-custom-wrap').hidden=$('ai-model-choice').value!=='custom';aiMarkDirty();if(!$('ai-custom-wrap').hidden)$('ai-model-custom').focus();});
for(const id of ['ai-model-custom','ai-key','ai-clear-key'])$(''+id).addEventListener(id==='ai-clear-key'?'change':'input',aiMarkDirty);
$('ai-save').addEventListener('click',async()=>{
  if(aiDemo)return;
  const provider=$('ai-provider').value,model=aiModelValue(),apiKey=$('ai-key').value,clearKey=$('ai-clear-key').checked;
  if(!/^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(model)){aiMessage('제공사의 정확한 모델 ID를 입력하세요.',true);return;}
  if(clearKey&&apiKey){aiMessage('새 키 입력과 저장된 키 삭제를 함께 선택할 수 없습니다.',true);return;}
  guideButton($('ai-save'),'AI 설정을 저장하는 중입니다. 잠시 기다려주세요.');aiMessage('AI 설정을 저장하는 중입니다…');
  try{aiCurrent=await json(await fetch('/api/ai',{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':token},body:JSON.stringify({provider,model,api_key:apiKey,clear_key:clearKey})}));
    $('ai-key').value='';$('ai-clear-key').checked=false;aiDirty=false;aiUpdateKeyStatus();
    guideButton($('ai-test'),aiCurrent.has_key?'':'선택한 AI 제공사의 API 키를 입력하고 저장해주세요.');aiMessage('저장했습니다. 연결 테스트는 직접 누를 때만 실행됩니다.');
  }catch(error){aiMessage(aiErrors[error.message]||'저장 실패: '+error.message,true);}
  finally{guideButton($('ai-save'),aiDemo?'연습 모드에서는 AI 설정을 저장할 수 없습니다.':'');}
});
$('ai-test').addEventListener('click',async()=>{
  if(aiDemo||aiDirty||!aiCurrent||!aiCurrent.has_key)return;
  guideButton($('ai-test'),'AI 연결을 확인하는 중입니다. 잠시 기다려주세요.');aiMessage('저장된 제공사와 모델로 AI 연결을 확인하는 중입니다…');
  try{const result=await json(await fetch('/api/ai/test',{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':token},body:'{}'}));
    aiMessage('연결 확인: '+result.provider+' · '+result.model+' (초안·게시 승인과 무관)');
  }catch(error){aiMessage(aiErrors[error.message]||'연결 실패: '+error.message,true);if(error.message==='AI_AUTH_FAILED')showToast('AI API 키가 유효하지 않습니다. 우측 상단 옵션 → AI API 관리에서 키를 다시 입력해주세요.');}
  finally{guideButton($('ai-test'),aiDirty?'AI 설정을 저장한 뒤 연결 테스트를 눌러주세요.':!aiCurrent.has_key?'선택한 AI 제공사의 API 키를 입력하고 저장해주세요.':'');}
});
""".replace("__AI_DEMO__", "true" if demo else "false")
    page = page.replace("</script>", ai_script + "</script>")
    page = page.replace("async function loadVideos(){", "async function loadVideos(){progressActive=false;")
    page = page.replace("if(!data.videos.length)line($('videos')", "videoStates=data.states||{};if(!data.videos.length)line($('videos')", 1)
    page = page.replace("async function selectVideo(id){", "async function selectVideo(id){progressActive=false;")
    profile_script = """
const profileDialog=$('profile-dialog');
function profileMessage(text,bad=false){const state=$('profile-state');state.textContent=text;state.classList.toggle('error',bad);}
let profileSelectedLabel='유튜브1',profileOptions=[],videoStates={};
async function refreshProfiles(){const data=await json(await fetch('/api/profile-options',{headers:{'X-Session-Token':token}}));profileSelectedLabel=data.selected;profileOptions=data.options||[];renderProfileChoices();return data;}
let loginWatch=null,loginWatchBusy=false;
function watchLoginWindow(label){if(loginWatch)clearInterval(loginWatch);loginWatch=setInterval(async()=>{if(loginWatchBusy)return;loginWatchBusy=true;try{const data=await refreshProfiles();const entry=data.options.find(item=>item.label===label);if(entry&&!entry.login_window_open){clearInterval(loginWatch);loginWatch=null;if(!$('post-continue').hidden)guideButton($('post-continue'));profileMessage(label+' 로그인 창을 닫았습니다. 현재 계정 확인을 눌러 로그인 결과를 확인하세요.');}}catch(error){profileMessage('로그인 창 상태 확인 실패: '+explainReason(error.message),true);}finally{loginWatchBusy=false;}},2000);}
function renderProfileChoices(){const list=$('profile-list');list.replaceChildren();const activeWindow=profileOptions.find(item=>item.login_window_open);for(const entry of profileOptions){const row=document.createElement('div');row.className='profile-row';row.setAttribute('role','listitem');const info=document.createElement('div');info.className='profile-info';const heading=document.createElement('div');heading.className='profile-heading';const name=document.createElement('strong');name.textContent=entry.label;const email=document.createElement('span');email.className='profile-email';email.textContent=entry.account_state==='SIGNED_IN'?(entry.verified_email||'로그인 확인 · 이메일 비공개'):'계정 확인 필요';heading.append(name,email);const status=document.createElement('span');status.textContent=entry.login_window_open?'계정 선택 창 열림':entry.account_state==='SIGNED_IN'?'로그인됨 · '+new Date(entry.verified_at).toLocaleString('ko-KR'):entry.account_state==='SIGNED_OUT'?'로그아웃 확인됨':entry.configured?'로그인 상태 미확인':'전용 프로필 준비 필요';info.append(heading,status);const busyReason=activeWindow?activeWindow.label+' Chrome 창이 열려 있습니다. 그 창을 닫은 뒤 다시 눌러주세요.':'';const verify=document.createElement('button');verify.type='button';verify.textContent=entry.account_state==='SIGNED_OUT'?'로그인하기':'현재 계정 확인';guideButton(verify,busyReason);verify.addEventListener('click',()=>entry.account_state==='SIGNED_OUT'?openAppProfile(entry.label):checkProfileAccount(entry.label));row.append(info,verify);if(entry.account_state==='SIGNED_IN'){const change=document.createElement('button');change.type='button';change.className='secondary profile-change';change.textContent='계정 변경';guideButton(change,busyReason);change.addEventListener('click',()=>openAppProfile(entry.label));heading.append(change);}list.append(row);}guideButton($('profile-setup'),activeWindow?activeWindow.label+' Chrome 창을 닫은 뒤 새 프로필을 추가해주세요.':profileOptions.length>=20?'프로필은 최대 20개까지 등록할 수 있습니다.':'');}
async function openAppProfile(label){profileMessage(label+'의 Google 계정 선택 창을 여는 중입니다…');try{const result=await localPost('/api/profile/setup',{label});videoStates=result.states||videoStates;await refreshProfiles();watchLoginWindow(label);profileMessage(label+' 전용 Chrome에서 계정을 선택하거나 추가하세요. 창을 닫은 뒤 현재 계정 확인을 눌러주세요.');}catch(error){const message='계정 선택 창을 열지 못했습니다: '+explainReason(error.message);profileMessage(message,true);showToast(message);}}
async function checkProfileAccount(label){profileMessage(label+'의 실제 YouTube 로그인 상태를 확인하는 중입니다…');try{const data=await localPost('/api/profile/verify-email',{label,video_id:''});profileOptions=data.options||profileOptions;renderProfileChoices();const entry=profileOptions.find(item=>item.label===label);profileMessage(label+' 로그인 확인 완료 · '+(entry?.verified_email||'계정'));}catch(error){if(['PROFILE_SIGNED_OUT','PROFILE_NOT_CONFIGURED','PROFILE_DIRECTORY_MISSING'].includes(error.message)){profileMessage(label+'은 로그인이 필요합니다. 계정 선택 창을 엽니다.');await openAppProfile(label);return;}const message=error.message==='PROFILE_ACCOUNT_UNKNOWN'?'로그인 여부를 정확히 확인하지 못했습니다. 네트워크와 YouTube 화면을 확인한 뒤 다시 시도하세요.':'계정 확인 실패: '+explainReason(error.message);profileMessage(message,true);showToast(message);}}
async function openProfileDialog(){
  profileDialog.showModal();$('profile-title').focus();profileMessage('현재 연결을 불러오는 중입니다…');
  try{await refreshProfiles();profileMessage('프로필별 현재 계정을 확인할 수 있습니다.');}
  catch(_){profileMessage('프로필 목록을 불러오지 못했습니다.',true);}
}
function createProfileButton(panel){const action=document.createElement('button');action.type='button';action.textContent='앱 전용 프로필 확인';action.addEventListener('click',openProfileDialog);panel.append(action);}
$('profile-menu-open').addEventListener('click',()=>{closeOptions();openProfileDialog();});
$('profile-setup').addEventListener('click',()=>{$('profile-add-form').hidden=false;$('profile-add-name').value='';$('profile-add-name').focus();profileMessage('새 프로필 이름을 입력하세요.');});
$('profile-add-cancel').addEventListener('click',()=>{$('profile-add-form').hidden=true;$('profile-setup').focus();});
$('profile-add-save').addEventListener('click',async()=>{const label=$('profile-add-name').value.trim();if(!label){profileMessage('프로필 이름을 입력하세요.',true);return;}if(profileOptions.some(item=>item.label.toLocaleLowerCase('ko-KR')===label.toLocaleLowerCase('ko-KR'))){profileMessage('이미 사용 중인 프로필 이름입니다.',true);return;}guideButton($('profile-add-save'),'프로필을 준비하는 중입니다.');try{await localPost('/api/profile/add',{label});$('profile-add-form').hidden=true;await refreshProfiles();profileMessage(label+' 프로필을 만들었습니다. 계정 선택 창을 엽니다.');await openAppProfile(label);}catch(error){const messages={PROFILE_NAME_DUPLICATE:'이미 사용 중인 프로필 이름입니다.',PROFILE_NAME_INVALID:'프로필 이름은 1~30자로 입력하고 경로 문자는 제외하세요.',PROFILE_LIMIT_REACHED:'프로필은 최대 20개까지 등록할 수 있습니다.'};profileMessage(messages[error.message]||'프로필 추가 실패: '+explainReason(error.message),true);}finally{guideButton($('profile-add-save'),'');}});
$('profile-cancel').addEventListener('click',()=>profileDialog.close());
profileDialog.addEventListener('close',()=>{if(selected)$('selection').focus?.();});
async function openLoginAfterPost(){progressActive=false;try{await refreshProfiles();const label=videoStates[selected]?.profile||profileSelectedLabel;await localPost('/api/profile/setup',{label});guideButton($('post-continue'),'계정 선택 Chrome 창을 닫은 뒤 댓글 계속하기를 눌러주세요.');watchLoginWindow(label);$('post-state').textContent='로그인이 필요합니다. 열린 전용 Chrome에서 계정을 선택하고 창을 닫은 뒤 댓글 계속하기를 누르세요.';$('post-continue').hidden=false;}catch(error){$('post-state').textContent='계정 선택 창을 열지 못했습니다: '+explainReason(error.message);guideButton($('post-continue'),'계정 선택 창을 다시 열어 로그인한 뒤 계속해주세요.');$('post-continue').hidden=false;}}
$('post-continue').addEventListener('click',async()=>{if(!selected)return;$('post-continue').hidden=true;const videoId=selected;await selectVideo(videoId);if(ready)await postComment();else $('post-continue').hidden=false;});
refreshProfiles().catch(()=>{});
"""
    page = page.replace("</script>", profile_script + "</script>")
    progress = """
let progressActive=false;
$('post-state').setAttribute('aria-live','polite');
const progressLabels={profile_check:'프로필 확인',opening:'브라우저 실행',navigating:'YouTube 탐색',checking_login:'로그인 상태 확인',comment_window:'댓글 입력창 확인',typing:'댓글 입력',submitting:'게시',verifying:'게시 결과 확인',posted:'완료 · 댓글 보기',failed:'게시 실패'};
$('post').addEventListener('click',()=>{progressActive=true;$('capture').replaceChildren();});
async function updateProgress(){
  if(!progressActive)return;
  try {
    const response=await fetch('/api/progress',{headers:{'X-Session-Token':token}});
    if(!response.ok)return;
    const data=await response.json();
    if(!data.events.length)return;
    const last=data.events[data.events.length-1];
    $('post-state').textContent=[progressLabels[last.stage]||last.stage,last.reason_code].filter(Boolean).join(' · ');
    if(last.screenshot_url){
      const img=document.createElement('img');img.src=last.screenshot_url;
      img.alt='실패 화면 캡처';img.style.maxWidth='100%';$('capture').replaceChildren(img);
    }
  } catch (_) {}
}
setInterval(updateProgress,500);
"""
    return page.replace("</script>", progress + "</script>").encode("utf-8")


def _capture_url(path: str, capture_dir: Path | None) -> str:
    if not path or capture_dir is None:
        return ""
    candidate = Path(path)
    try:
        if (CAPTURE_NAME.fullmatch(candidate.name) and candidate.is_file()
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

        def do_GET(self) -> None:
            if not self._host_ok():
                return self._reject(403, FORBIDDEN)
            if self.path == "/":
                body = _page(token, demo=isinstance(service, DemoService))
                self._headers(200, "text/html; charset=utf-8", len(body))
                return self.wfile.write(body)
            if self.path == "/api/videos":
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
                path = captures / capture.group(1)
                if _capture_url(str(path), captures):
                    try:
                        body = path.read_bytes()
                    except OSError:
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

