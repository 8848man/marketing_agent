"""Dashboard configuration and secret-file storage, independent of HTTP routing."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import tempfile
from threading import RLock
from urllib.parse import urlsplit

import yaml

from .ai_client import PROVIDERS, validate_model
from .posting_service import CHANNEL_ID
from .rss_feed import CHANNELS
from .secret_store import DpapiFileStore, default_store

CHANNEL_NAME = re.compile(r"[^\x00-\x1f\x7f]{1,100}\Z")
PROFILE_MEMO_MAX = 40
PROFILE_LABEL = re.compile(r'[^\x00-\x1f\x7f\\/:*?"<>|]{1,30}\Z')
PROFILE_ID = re.compile(r"(?:youtube[123]|p-[a-f0-9]{16})\Z")
BRAND_NAME = re.compile(r"[^\x00-\x1f\x7f]{1,80}\Z")
BRAND_DESCRIPTION = re.compile(r"[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]{1,1000}\Z")
DEFAULT_BRAND = {"name": "운명원", "description": "연애 고민을 사주 관점에서 살펴보는 서비스", "reference_url": ""}
DEFAULT_COMMENT_LIMITS = {"min_chars": 40, "max_chars": 120}
YOUTUBE_KEY_NAME = "YOUTUBE_API_KEY"
_DEFAULT = object()


def validate_comment_limits(min_chars: object, max_chars: object) -> dict[str, int]:
    if (type(min_chars) is not int or type(max_chars) is not int
            or not 1 <= min_chars <= max_chars <= 1000):
        raise ValueError("COMMENT_LENGTH_SETTINGS_INVALID")
    return {"min_chars": min_chars, "max_chars": max_chars}


class DashboardSettings:
    """Private YAML settings with explicit public views for dashboard dialogs."""

    DEFAULT = {
        "profiles": ["유튜브1", "유튜브2", "유튜브3"],
        "channels": list(CHANNELS),
        "comment": {"min_chars": 40, "max_chars": 120, "brand": "운명원"},
        "limits": {"daily_max_comments": 10},
    }

    def __init__(self, path: str | Path, *, secret_store: DpapiFileStore | None = _DEFAULT):
        self.path = Path(path)
        self._lock = RLock()
        self.secret_store_error: str | None = None
        self._store = default_store(self.path.parent) if secret_store is _DEFAULT else secret_store
        self._current = self._validate(self._read_full())
        self._migrate_legacy_ai_env()
        self._migrate_legacy_ai_key()
        self._migrate_env_secrets()

    def _ai_env_path(self) -> Path:
        return self.path.parent / ".env"

    def _secret_names(self) -> list[str]:
        return [details[1] for details in PROVIDERS.values()] + [YOUTUBE_KEY_NAME]

    def _remove_env_keys(self, names: set[str]) -> None:
        path = self._ai_env_path()
        if path.is_symlink():
            raise ValueError("AI_ENV_FILE_UNSAFE")
        if not path.exists():
            return
        if not path.is_file() or path.stat().st_size > 16384:
            raise ValueError("AI_ENV_FILE_INVALID")
        lines = path.read_text(encoding="utf-8").splitlines()
        kept = [line for line in lines if line.partition("=")[0] not in names]
        if len(kept) == len(lines):
            return
        fd, temporary = tempfile.mkstemp(prefix="env-", suffix=".tmp", dir=path.parent)
        try:
            os.chmod(temporary, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write("".join(line + "\n" for line in kept))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o600)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _env_secret(self, name: str) -> str:
        """Value of one key line in .env (empty when absent)."""
        path = self._ai_env_path()
        if path.is_symlink():
            raise ValueError("AI_ENV_FILE_UNSAFE")
        if not path.exists():
            return ""
        if not path.is_file() or path.stat().st_size > 16384:
            raise ValueError("AI_ENV_FILE_INVALID")
        found = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if key != name:
                continue
            if not separator or found is not None:
                raise ValueError("AI_ENV_FILE_INVALID")
            try:
                found = json.loads(value) if value.startswith('"') else value
            except json.JSONDecodeError as exc:
                raise ValueError("AI_ENV_FILE_INVALID") from exc
            if not isinstance(found, str):
                raise ValueError("AI_ENV_FILE_INVALID")
        return found or ""

    def _note_store_error(self, exc: Exception) -> None:
        code = str(exc)
        self.secret_store_error = code if code in ("SECRET_STORE_INVALID", "SECRET_STORE_UNREADABLE") \
            else "SECRET_STORE_UNREADABLE"

    def _store_get(self, name: str) -> str | None:
        """Read one stored key; an unusable store counts as empty (callers fall back to .env)."""
        try:
            return self._store.get(name)
        except (ValueError, OSError) as exc:
            self._note_store_error(exc)
            return None

    def _store_usable(self) -> bool:
        try:
            for name in self._store.names():
                self._store.get(name)
        except (ValueError, OSError):
            return False
        return True

    def _store_write(self, action) -> None:
        """Run a store write; move an unreadable store file to .bad and retry once."""
        try:
            action()
        except (ValueError, OSError):
            path = self._store.path
            if not (path.exists() or path.is_symlink()) or self._store_usable():
                raise
            os.replace(path, path.with_name(path.name + ".bad"))
            action()
        self.secret_store_error = None

    def _migrate_env_secrets(self) -> None:
        """Move key lines from .env into the secure store; keep .env if the store fails.

        A nonempty .env value is the user's latest input and replaces any stored value."""
        if self._store is None:
            return
        with self._lock:
            moved = set()
            for name in self._secret_names():
                value = self._env_secret(name)
                if not value:
                    continue
                try:
                    self._store.set(name, value)
                except (ValueError, OSError) as exc:
                    self._note_store_error(exc)
                    continue
                moved.add(name)
            if moved:
                self._remove_env_keys(moved)

    def _ai_key_values(self) -> dict[str, str]:
        """AI keys: secure store first, then .env."""
        values = self._read_ai_env()
        if self._store is not None:
            for details in PROVIDERS.values():
                stored = self._store_get(details[1])
                if stored:
                    values[details[1]] = stored
        return values

    def youtube_api_key(self) -> str:
        """Read the project's YouTube key for each explicit draft request."""
        with self._lock:
            if self._store is not None:
                self._migrate_env_secrets()
                stored = self._store_get(YOUTUBE_KEY_NAME)
                if stored:
                    return stored
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
            if self._store is not None:
                self._store_write(lambda: self._store.set(YOUTUBE_KEY_NAME, key))
                self._remove_env_keys({YOUTUBE_KEY_NAME})
                return {"has_key": True}
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
        if not isinstance(comment, dict) or comment.get("brand", "운명원") != "운명원":
            raise ValueError("SETTINGS_COMMENT_INVALID")
        limits_for_comment = validate_comment_limits(
            comment.get("min_chars", 40), comment.get("max_chars", 120))
        if (not isinstance(limits, dict) or limits.get("daily_max_comments") != 10):
            raise ValueError("SETTINGS_LIMIT_PDF_LOCKED")
        return {"profiles": list(profiles), "channels": list(channels),
                "comment": {**limits_for_comment, "brand": "운명원"},
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

    @staticmethod
    def _brand_data(full: dict) -> dict[str, str]:
        saved = full.get("brand_settings", DEFAULT_BRAND)
        if not isinstance(saved, dict) or set(saved) != {"name", "description", "reference_url"}:
            raise ValueError("BRAND_SETTINGS_INVALID")
        name, description, reference_url = (saved[key] for key in ("name", "description", "reference_url"))
        if not isinstance(name, str) or name != name.strip() or not BRAND_NAME.fullmatch(name):
            raise ValueError("BRAND_NAME_INVALID")
        if (not isinstance(description, str) or description != description.strip()
                or not BRAND_DESCRIPTION.fullmatch(description)):
            raise ValueError("BRAND_DESCRIPTION_INVALID")
        if not isinstance(reference_url, str) or reference_url != reference_url.strip() or len(reference_url) > 2048:
            raise ValueError("BRAND_URL_INVALID")
        if reference_url:
            parsed = urlsplit(reference_url)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                    or parsed.password or any(ord(char) <= 32 or ord(char) == 127 for char in reference_url)):
                raise ValueError("BRAND_URL_INVALID")
        return dict(saved)

    def brand_public(self) -> dict[str, str]:
        with self._lock:
            return self._brand_data(self._read_full())

    def comment_limits(self) -> dict[str, int]:
        with self._lock:
            full = self._read_full()
            saved = full.get("comment", {})
            if not isinstance(saved, dict):
                raise ValueError("COMMENT_LENGTH_SETTINGS_INVALID")
            return validate_comment_limits(saved.get("min_chars", 40), saved.get("max_chars", 120))

    def review_filter_enabled(self) -> bool:
        """IMP-16: second-pass draft filter switch; on unless explicitly turned off."""
        with self._lock:
            saved = self._read_full().get("comment", {})
            value = saved.get("review_filter", True) if isinstance(saved, dict) else True
            return value is not False

    def comment_generation_public(self) -> dict[str, str | int | bool]:
        with self._lock:
            return {**self.brand_public(), **self.comment_limits(),
                    "review_filter": self.review_filter_enabled()}

    def save_comment_generation(self, name: str, description: str, reference_url: str,
                                min_chars: int, max_chars: int,
                                review_filter: bool = True) -> dict[str, str | int | bool]:
        if not isinstance(review_filter, bool):
            raise ValueError("COMMENT_REVIEW_FILTER_INVALID")
        brand = self._brand_data({"brand_settings": {"name": name, "description": description,
                                                       "reference_url": reference_url}})
        lengths = validate_comment_limits(min_chars, max_chars)
        with self._lock:
            full = self._read_full()
            full["brand_settings"] = brand
            full["comment"] = {**full.get("comment", {}), "brand": "운명원", **lengths,
                               "review_filter": review_filter}
            normalized = self._validate(full)
            self._write_full(full)
            self._current = normalized
            return {**brand, **lengths, "review_filter": review_filter}

    def save_brand(self, name: str, description: str, reference_url: str) -> dict[str, str]:
        brand = self._brand_data({"brand_settings": {"name": name, "description": description,
                                                       "reference_url": reference_url}})
        with self._lock:
            full = self._read_full()
            full["brand_settings"] = brand
            self._write_full(full)
            return dict(brand)

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
        if self._store is not None:
            self._migrate_env_secrets()
        key = self._ai_key_values().get(PROVIDERS[provider][1], "")
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

    @staticmethod
    def _memos(full: dict) -> dict[str, str]:
        memos = full.get("profile_memos", {})
        if not isinstance(memos, dict):
            return {}
        return {key: value for key, value in memos.items()
                if isinstance(key, str) and isinstance(value, str)}

    def profile_options_public(self) -> dict[str, object]:
        """List only the application's three private profiles, never Chrome's local data."""
        with self._lock:
            full = self._read_full()
            selected = self._selected_profile(full)
            saved = full.get("chrome_profiles", {})
            memos = self._memos(full)
            options = []
            for label in self._current["profiles"]:
                root = self.app_profile_root(label)
                configured = (root / "Default").is_dir()
                connected = (configured and isinstance(saved, dict) and
                             saved.get(label) == {"user_data_dir": str(root),
                                                  "profile_directory": "Default"})
                options.append({"label": label, "memo": memos.get(label, ""), "configured": configured,
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

    def save_profile_memo(self, label: str, memo: str) -> dict[str, object]:
        """A short free-text note per profile (IMP-18). Emails are refused on purpose."""
        text = memo.strip() if isinstance(memo, str) else None
        if text is None or len(text) > PROFILE_MEMO_MAX or any(ord(ch) < 32 for ch in text):
            raise ValueError("PROFILE_MEMO_INVALID")
        if "@" in text:
            raise ValueError("PROFILE_MEMO_EMAIL_BLOCKED")
        with self._lock:
            if label not in self._current["profiles"]:
                raise ValueError("PROFILE_NAME_INVALID")
            full = self._read_full()
            memos = self._memos(full)
            if text:
                memos[label] = text
            else:
                memos.pop(label, None)
            memos = {key: value for key, value in memos.items() if key in self._current["profiles"]}
            if memos:
                full["profile_memos"] = memos
            else:
                full.pop("profile_memos", None)
            self._write_full(full)
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
            name = PROVIDERS[provider][1]
            if self._store is not None:
                if clear_key:
                    self._store_write(lambda: self._store.delete(name))
                    self._remove_env_keys({name})
                elif api_key:
                    self._store_write(lambda: self._store.set(name, api_key))
                    self._remove_env_keys({name})
            else:
                values = self._read_ai_env()
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
            comment = current["comment"]
            rows.extend([f"comment: {{ min_chars: {comment['min_chars']}, max_chars: {comment['max_chars']}, brand: 운명원 }}",
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
