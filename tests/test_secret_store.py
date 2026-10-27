"""DPAPI-style secret store and its use by dashboard settings (fake cipher, no Windows)."""

from __future__ import annotations

import os

import pytest
import yaml

from marketing_agent import secret_store
from marketing_agent.dashboard_settings import DashboardSettings
from marketing_agent.secret_store import DpapiFileStore

KEY = "test-key-value-123"
YT_KEY = "test-youtube-value-456"


def _protect(data: bytes) -> bytes:
    return data[::-1] + b"!"


def _unprotect(data: bytes) -> bytes:
    assert data.endswith(b"!")
    return data[:-1][::-1]


def _failing(_data: bytes) -> bytes:
    raise OSError("DPAPI_FAILED")


def _store(tmp_path, protect=_protect) -> DpapiFileStore:
    return DpapiFileStore(tmp_path / "data" / "dashboard" / "secrets.dpapi.json", protect, _unprotect)


def _settings(tmp_path, store):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    return DashboardSettings(tmp_path / "config.yaml", secret_store=store)


def test_store_roundtrip_and_file_has_no_plaintext(tmp_path):
    store = _store(tmp_path)
    store.set("OPENAI_API_KEY", KEY)
    assert store.get("OPENAI_API_KEY") == KEY
    assert store.get("GEMINI_API_KEY") is None
    assert store.names() == ["OPENAI_API_KEY"]
    assert KEY not in store.path.read_text(encoding="utf-8")
    store.delete("OPENAI_API_KEY")
    assert store.get("OPENAI_API_KEY") is None


def test_store_rejects_symlink_and_corrupt_file(tmp_path):
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="SECRET_STORE_INVALID"):
        store.get("OPENAI_API_KEY")
    store.path.unlink()
    target = tmp_path / "elsewhere.json"
    target.write_text('{"version": 1, "secrets": {}}', encoding="utf-8")
    try:
        store.path.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="SECRET_STORE_INVALID"):
        store.set("OPENAI_API_KEY", KEY)


def test_save_ai_key_goes_to_store_not_env(tmp_path):
    store = _store(tmp_path)
    settings = _settings(tmp_path, store)
    public = settings.save_ai("openai", "gpt-5.4-mini", KEY)
    assert public["has_key"] is True
    env = tmp_path / ".env"
    assert not env.exists() or KEY not in env.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=" + '"' + KEY not in (env.read_text(encoding="utf-8") if env.exists() else "")
    assert store.get("OPENAI_API_KEY") == KEY
    assert settings.ai_credentials()[2] == KEY
    settings.save_ai("openai", "gpt-5.4-mini", "", clear_key=True)
    assert store.get("OPENAI_API_KEY") is None


def test_youtube_key_goes_to_store_not_env(tmp_path):
    store = _store(tmp_path)
    settings = _settings(tmp_path, store)
    assert settings.save_youtube_api_key(YT_KEY) == {"has_key": True}
    env = tmp_path / ".env"
    assert not env.exists() or YT_KEY not in env.read_text(encoding="utf-8")
    assert settings.youtube_api_key() == YT_KEY


def test_existing_env_keys_migrate_to_store(tmp_path):
    (tmp_path / ".env").write_text(
        f'OTHER_SETTING=keep\nOPENAI_API_KEY="{KEY}"\nYOUTUBE_API_KEY="{YT_KEY}"\n', encoding="utf-8")
    store = _store(tmp_path)
    settings = _settings(tmp_path, store)
    assert settings.youtube_api_key() == YT_KEY
    assert settings.ai_credentials()[2] == KEY
    assert store.get("OPENAI_API_KEY") == KEY
    assert store.get("YOUTUBE_API_KEY") == YT_KEY
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "OTHER_SETTING=keep" in env
    assert KEY not in env and YT_KEY not in env


def test_migration_keeps_env_when_protect_fails(tmp_path):
    (tmp_path / ".env").write_text(f'OPENAI_API_KEY="{KEY}"\nYOUTUBE_API_KEY="{YT_KEY}"\n', encoding="utf-8")
    settings = _settings(tmp_path, _store(tmp_path, protect=_failing))
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert KEY in env and YT_KEY in env
    assert settings.youtube_api_key() == YT_KEY
    assert settings.ai_credentials()[2] == KEY


def test_default_store_only_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    assert secret_store.default_store(tmp_path) is None
    with pytest.raises(OSError):
        secret_store.dpapi_protect(b"x")


def test_no_store_keeps_env_behavior(tmp_path):
    settings = _settings(tmp_path, None)
    settings.save_ai("openai", "gpt-5.4-mini", KEY)
    assert KEY in (tmp_path / ".env").read_text(encoding="utf-8")
    settings.save_youtube_api_key(YT_KEY)
    assert settings.youtube_api_key() == YT_KEY


def test_env_key_overrides_existing_store_value(tmp_path):
    store = _store(tmp_path)
    store.set("OPENAI_API_KEY", "test-old-value-000")
    (tmp_path / ".env").write_text(f'OPENAI_API_KEY="{KEY}"\n', encoding="utf-8")
    settings = _settings(tmp_path, store)
    assert settings.ai_credentials()[2] == KEY
    assert store.get("OPENAI_API_KEY") == KEY
    assert "OPENAI_API_KEY" not in (tmp_path / ".env").read_text(encoding="utf-8")


def test_corrupt_store_falls_back_to_env(tmp_path):
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text("{not json", encoding="utf-8")
    (tmp_path / ".env").write_text(f'YOUTUBE_API_KEY="{YT_KEY}"\n', encoding="utf-8")
    settings = _settings(tmp_path, store)
    assert settings.youtube_api_key() == YT_KEY
    assert YT_KEY in (tmp_path / ".env").read_text(encoding="utf-8")
    assert settings.secret_store_error == "SECRET_STORE_INVALID"


def test_unreadable_store_falls_back(tmp_path):
    good = _store(tmp_path)
    good.set("OPENAI_API_KEY", "test-old-value-000")

    def unreadable(_data: bytes) -> bytes:
        raise OSError("DPAPI_FAILED")

    store = DpapiFileStore(good.path, unreadable, unreadable)
    (tmp_path / ".env").write_text(f'OPENAI_API_KEY="{KEY}"\n', encoding="utf-8")
    settings = _settings(tmp_path, store)
    assert settings.ai_credentials()[2] == KEY
    assert KEY in (tmp_path / ".env").read_text(encoding="utf-8")
    assert settings.secret_store_error == "SECRET_STORE_UNREADABLE"


def test_save_replaces_corrupt_store(tmp_path):
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text("{not json", encoding="utf-8")
    settings = _settings(tmp_path, store)
    settings.save_ai("openai", "gpt-5.4-mini", KEY)
    assert len(list(store.path.parent.glob(store.path.name + ".bad-*"))) == 1
    assert settings.ai_credentials()[2] == KEY
    assert settings.secret_store_error is None


def test_transient_unreadable_store_is_not_quarantined(tmp_path):
    good = _store(tmp_path)
    good.set("OPENAI_API_KEY", "test-old-value-000")
    before = good.path.read_bytes()
    store = DpapiFileStore(good.path, _failing, _failing)
    settings = _settings(tmp_path, store)
    with pytest.raises(ValueError, match="SECRET_STORE_UNAVAILABLE"):
        settings.save_ai("openai", "gpt-5.4-mini", KEY)
    assert good.path.read_bytes() == before
    assert list(good.path.parent.glob("*.bad*")) == []


def test_corrupt_store_quarantine_keeps_previous_backups(tmp_path):
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True)
    settings = _settings(tmp_path, store)
    for _ in range(2):
        store.path.write_text("{not json", encoding="utf-8")
        settings.save_ai("openai", "gpt-5.4-mini", KEY)
    assert len(list(store.path.parent.glob(store.path.name + ".bad-*"))) == 2
