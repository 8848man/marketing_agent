"""Focused dashboard request boundary and CLI tests."""

from __future__ import annotations

from datetime import datetime, timezone

from contextlib import contextmanager
import http.client
import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import threading
import time
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from marketing_agent import __main__
from marketing_agent.captions import EvidenceResult, YouTubeDataComments
from marketing_agent.dashboard import (HOST, ConfiguredPostingService,
                                       DashboardSettings, DemoService, MAX_CAPTURE_BYTES, _capture_url,
                                       check_channel_connection, create_server)
from marketing_agent.dashboard_contracts import DraftPreview, PostStatus, VideoCard, VideoList
from marketing_agent.draft_generation import ProviderDraftGenerator
from marketing_agent.poster import VisibleChromePoster
from marketing_agent.prompt_policy import DRAFT_RESPONSE_SCHEMA, DraftPrompt
from marketing_agent.rss_feed import list_videos, recheck_video
from marketing_agent.storage import Store


VIDEO_ID = "AbCdEfGhI12"


class FakeService:
    def __init__(self):
        self.posts = 0
        self.reservations = 0
        self.chrome_opens = 0
        self.selections = 0

    def list_videos(self):
        return VideoList((VideoCard(VIDEO_ID, "channel", "채널", "제목",
                                    "2026-10-15", "https://i.ytimg.com/vi/x/hqdefault.jpg"),))

    def select_video(self, video_id):
        self.selections += 1
        return DraftPreview(video_id, "고민", "검토된 초안", True, "")

    def post_video(self, video_id):
        self.posts += 1
        self.reservations += 1
        self.chrome_opens += 1
        return PostStatus("posted")


def no_post_attempts(db_path) -> bool:
    """IMP-19 keeps profile status in posts.db; what must stay empty is the post log."""
    import sqlite3
    if not db_path.exists():
        return True
    with sqlite3.connect(db_path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return all(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
                   for table in ("dashboard_post_reservations", "post_results") if table in tables)


class PairedPort(int):
    """Port number that also carries the server's pairing code."""

    def __new__(cls, port, pair_code):
        obj = super().__new__(cls, port)
        obj.pair_code = pair_code
        return obj


@contextmanager
def running_server(service, **kwargs):
    server = create_server(service, **kwargs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield PairedPort(server.server_port, server.pair_code)
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def _raw_request(port, method, path, *, host=None, origin=None, token=None, body=None, cookie=None):
    connection = http.client.HTTPConnection(HOST, int(port), timeout=3)
    headers = {"Host": host if host is not None else f"{HOST}:{port}"}
    if origin is not None:
        headers["Origin"] = origin
    if token is not None:
        headers["X-Session-Token"] = token
    if cookie is not None:
        headers["Cookie"] = cookie
    if body is not None:
        headers["Content-Type"] = "application/json"
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    result = response.status, response.read().decode("utf-8"), response.getheaders()
    connection.close()
    return result


def pair_cookie(port):
    """Pair like the browser does and return the Cookie header value."""
    status, _, headers = _raw_request(port, "GET", f"/pair?code={port.pair_code}")
    assert status == 303
    cookie = next(v for k, v in headers if k.lower() == "set-cookie")
    return cookie.split(";", 1)[0]


def request(port, method, path, *, host=None, origin=None, token=None, body=None, pair=True):
    """Page requests ('/') are paired first unless pair=False."""
    cookie = pair_cookie(port) if pair and method == "GET" and path == "/" and hasattr(port, "pair_code") else None
    return _raw_request(port, method, path, host=host, origin=origin, token=token, body=body, cookie=cookie)[:2]


def test_dashboard_is_loopback_and_has_three_panels():
    server = create_server(FakeService())
    assert server.server_address[0] == "127.0.0.1"
    server.server_close()
    with running_server(FakeService()) as port:
        status, page = request(port, "GET", "/")
        assert status == 200
        assert all(label in page for label in ("① 영상 불러오기", "② 영상 선택", "③ 댓글 달기"))
        assert "fetch('/api/post'" in page
        selection = page.split("async function selectVideo", 1)[1].split("async function postComment", 1)[0]
        assert "/api/post" not in selection
        assert "POST" not in selection
        assert "const missing=draft.reason_code==='DRAFT_MISSING'" in page
        assert "guideButton($('post')" in page
        assert "/api/profile/verify" in page
        assert "로그인 창 열기" not in page
        assert "verifyProfileAccount" not in page
        assert "function showEvidence(panel,draft)" in page
        assert "el.textContent=value" in page


def test_draft_evidence_requires_token_and_preserves_untrusted_text():
    marker = "<script>ignore approval</script>"

    class EvidenceService(FakeService):
        def select_video(self, video_id):
            return DraftPreview(video_id, reason_code="APPROVAL_MISSING",
                                evidence_sources=("자막",), source_text=marker)

    with running_server(EvidenceService()) as port:
        page = request(port, "GET", "/")[1]
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        path = f"/api/videos/{VIDEO_ID}/draft"
        assert request(port, "GET", path)[0] == 403
        status, body = request(port, "GET", path, token=token)
        assert status == 200
        assert json.loads(body)["source_text"] == marker


def test_rejected_post_requests_never_reach_service():
    service = FakeService()
    with running_server(service) as port:
        page = request(port, "GET", "/")[1]
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        valid = json.dumps({"video_id": VIDEO_ID})
        cases = [
            ("GET", "/api/post", {}, None, 405),
            ("POST", "/api/post", {"host": "evil.example", "origin": f"http://{HOST}:{port}", "token": token}, valid, 403),
            ("POST", "/api/post", {"origin": "http://evil.example", "token": token}, valid, 403),
            ("POST", "/api/post", {"token": token}, valid, 403),
            ("POST", "/api/post", {"origin": f"http://{HOST}:{port}", "token": "wrong"}, valid, 403),
            ("POST", "/api/post", {"origin": f"http://{HOST}:{port}"}, valid, 403),
            ("POST", "/api/post", {"origin": f"http://{HOST}:{port}", "token": token}, json.dumps({"video_id": "bad"}), 400),
        ]
        for method, path, options, body, expected in cases:
            assert request(port, method, path, body=body, **options)[0] == expected
        assert (service.posts, service.reservations, service.chrome_opens) == (0, 0, 0)
        assert request(port, "POST", "/api/post", origin=f"http://{HOST}:{port}", token=token, body=valid)[0] == 200
        assert service.posts == 1


def test_keep_window_flag_is_strictly_validated_before_posting():
    service = FakeService()
    with running_server(service) as port:
        page = request(port, "GET", "/")[1]
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        assert 'id="keep-window"' in page
        assert 'id="profile-open"' not in page
        for bad in ("yes", 1, None):
            status, _ = request(port, "POST", "/api/post", origin=f"http://{HOST}:{port}",
                                token=token, body=json.dumps({"video_id": VIDEO_ID, "keep_window_open": bad}))
            assert status == 400
        assert service.posts == 0


def test_profile_memo_is_plain_note_and_refuses_emails(tmp_path):
    import pytest
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    options = settings.save_profile_memo("유튜브1", "  운명원 마케팅 1호  ")
    assert options["options"][0]["memo"] == "운명원 마케팅 1호"
    assert DashboardSettings(tmp_path / "config.yaml").profile_options_public()["options"][0]["memo"] == "운명원 마케팅 1호"
    assert not (tmp_path / "data" / "dashboard" / "profile-emails.json").exists()
    with pytest.raises(ValueError, match="PROFILE_MEMO_EMAIL_BLOCKED"):
        settings.save_profile_memo("유튜브1", "reviewer@example.com")
    with pytest.raises(ValueError, match="PROFILE_MEMO_INVALID"):
        settings.save_profile_memo("유튜브1", "가" * 41)
    with pytest.raises(ValueError, match="PROFILE_MEMO_INVALID"):
        settings.save_profile_memo("유튜브1", "줄\n바꿈")
    with pytest.raises(ValueError, match="PROFILE_NAME_INVALID"):
        settings.save_profile_memo("유튜브4", "없는 프로필")
    assert settings.save_profile_memo("유튜브1", "")["options"][0]["memo"] == ""
    assert "profile_memos" not in yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))


def test_profile_memo_http_requires_local_token_and_valid_body(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts", settings=settings)
    with running_server(service) as port:
        page = request(port, "GET", "/")[1]
        assert "/api/profile/memo" in page
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        body = json.dumps({"label": "유튜브1", "memo": "운명원 2호"})
        origin = f"http://{HOST}:{port}"
        assert request(port, "POST", "/api/profile/memo", body=body)[0] == 403
        assert request(port, "POST", "/api/profile/memo", origin=origin, token=token,
                       body=json.dumps({"label": "유튜브1", "email": "x"}))[0] == 400
        assert request(port, "POST", "/api/profile/memo", origin=origin, token=token,
                       body=json.dumps({"label": "유튜브1", "memo": "a@b.c"}))[0] == 400
        assert request(port, "POST", "/api/profile/email", origin=origin, token=token, body=body)[0] == 404
        assert request(port, "POST", "/api/profile/memo", origin=origin, token=token, body=body)[0] == 200
        assert settings.profile_options_public()["options"][0]["memo"] == "운명원 2호"


def test_configured_service_uses_settings_channels(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts", settings=settings)
    assert set(service.allowed_channels()) == set(settings.channels())


def test_account_check_needs_no_video_and_never_posts(tmp_path):
    import pytest
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    root = settings.app_profile_root("유튜브1")
    (root / "Default").mkdir(parents=True)
    settings.save_profile("유튜브1")
    poster = VisibleChromePoster(root, "Default", screenshot_dir=tmp_path / "shots")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts",
                                       settings=settings, poster=poster)
    with patch.object(poster, "check_signed_in", return_value="") as inspect:
        result = service.verify_profile("유튜브1")
    inspect.assert_called_once_with("akn-AvCeHBI")
    option = result["options"][0]
    assert "verified_email" not in option
    assert option["verified_at"]
    assert no_post_attempts(tmp_path / "posts.db")
    with patch.object(poster, "check_signed_in", side_effect=ValueError("PROFILE_ACCOUNT_UNKNOWN")):
        with pytest.raises(ValueError, match="PROFILE_ACCOUNT_UNKNOWN"):
            service.verify_profile("유튜브1")
    # IMP-19: an unclear check keeps the last confirmed state
    assert service.profile_options_public()["options"][0]["account_state"] == "SIGNED_IN"
    with patch.object(poster, "check_signed_in", side_effect=ValueError("PROFILE_SIGNED_OUT")):
        with pytest.raises(ValueError, match="PROFILE_SIGNED_OUT"):
            service.verify_profile("유튜브1")
    assert service.profile_options_public()["options"][0]["account_state"] == "SIGNED_OUT"
    restarted = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts",
                                         settings=settings, poster=poster)
    assert restarted.profile_options_public()["options"][0]["verified_at"] == ""


def test_account_check_without_rss_uses_requested_profile(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    for label in ("유튜브1", "유튜브2"):
        (settings.app_profile_root(label) / "Default").mkdir(parents=True)
        settings.save_profile(label)
    poster = VisibleChromePoster(settings.app_profile_root("유튜브1"), "Default",
                                 screenshot_dir=tmp_path / "shots")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts",
                                       settings=settings, poster=poster,
                                       feed_loader=lambda: (_ for _ in ()).throw(AssertionError("RSS called")))
    from marketing_agent.storage import Store
    with Store(tmp_path / "posts.db") as store:   # IMP-19: 유튜브1 confirmed first
        store.set_profile_active("유튜브1", True, datetime.now(timezone.utc))
    with patch.object(poster, "check_signed_in", return_value="") as inspect:
        result = service.verify_profile("유튜브2")
    inspect.assert_called_once_with("akn-AvCeHBI")
    assert poster.user_data_dir == settings.app_profile_root("유튜브2")
    assert result["options"][1]["account_state"] == "SIGNED_IN"
    assert service._videos == {}
    assert no_post_attempts(tmp_path / "posts.db")


def test_account_check_does_not_consult_existing_post_records(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    root = settings.app_profile_root("유튜브1")
    (root / "Default").mkdir(parents=True)
    settings.save_profile("유튜브1")
    allowed = next(iter(settings.channels()))
    with Store(tmp_path / "posts.db") as store:
        for attempt_id, video_id, channel_id, verified in (
                ("one", VIDEO_ID, allowed, "2026-10-15T00:00:00Z"),
                ("two", "QXmBHgPqEUE", "untrusted", "2026-10-16T00:00:00Z")):
            store.db.execute("INSERT INTO dashboard_post_reservations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (attempt_id, video_id, channel_id, "제목", "hash", "approval",
                              "유튜브1", "2026-10-16", verified, "POSTED", None, None, verified))
    poster = VisibleChromePoster(root, "Default", screenshot_dir=tmp_path / "shots")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts",
                                       settings=settings, poster=poster,
                                       feed_loader=lambda: (_ for _ in ()).throw(OSError("RSS down")))
    with patch.object(poster, "check_signed_in", return_value="") as inspect:
        assert service.verify_profile("유튜브1")["options"][0]["account_state"] == "SIGNED_IN"
    inspect.assert_called_once_with("akn-AvCeHBI")
    with Store(tmp_path / "posts.db") as store:
        assert store.db.execute("SELECT COUNT(*) FROM dashboard_post_reservations").fetchone()[0] == 2


def test_verify_http_rejects_untrusted_request_before_browser():
    class Service(FakeService):
        def verify_profile(self, label):
            self.chrome_opens += 1
            return {"options": []}
    service = Service()
    with running_server(service) as port:
        page = request(port, "GET", "/")[1]
        assert "localPost('/api/profile/verify',{label})" in page
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        path = "/api/profile/verify"
        body = json.dumps({"label": "유튜브1"})
        assert request(port, "POST", path, body=body)[0] == 403
        assert request(port, "POST", path, token=token, body=body)[0] == 403
        assert request(port, "POST", path, token=token,
                       origin=f"http://{HOST}:{port}", body='{}')[0] == 400
        assert request(port, "POST", path, token=token,
                       origin=f"http://{HOST}:{port}",
                       body=json.dumps({"label": "유튜브1", "video_id": VIDEO_ID}))[0] == 400
        assert request(port, "POST", path, token=token,
                       origin=f"http://{HOST}:{port}",
                       body=json.dumps({"label": "유튜브1", "url": "https://outside.example/"}))[0] == 400
        assert service.chrome_opens == 0
        assert request(port, "POST", path, token=token,
                       origin=f"http://{HOST}:{port}", body=body)[0] == 200
        assert service.chrome_opens == 1


def test_ai_key_moves_from_yaml_to_private_env_and_survives_restart(tmp_path):
    source = dict(DashboardSettings.DEFAULT)
    source["ai"] = {"provider": "openai", "model": "gpt-5.4-mini", "api_key": "PRIVATE_MIGRATION_KEY"}
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(source, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    assert settings.ai_credentials()[2] == "PRIVATE_MIGRATION_KEY"
    assert "PRIVATE_MIGRATION_KEY" not in (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "api_key" not in yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))["ai"]
    env = tmp_path / ".env"
    assert env.is_file()
    assert DashboardSettings(tmp_path / "config.yaml").ai_credentials()[2] == "PRIVATE_MIGRATION_KEY"
    settings.save_ai("openai", "gpt-5.4-mini", "", clear_key=True)
    assert settings.ai_credentials()[2] == ""
    assert "PRIVATE_MIGRATION_KEY" not in env.read_text(encoding="utf-8")


def test_root_env_preserves_each_provider_and_migrates_old_gemini_key(tmp_path):
    source = dict(DashboardSettings.DEFAULT)
    source["ai"] = {"provider": "gemini", "model": "gemini-3.5-flash"}
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(source, allow_unicode=True), encoding="utf-8")
    (tmp_path / ".env.example").write_text(
        "YOUTUBE_API_KEY=\nOPENAI_API_KEY=\nGEMINI_API_KEY=\n"
        "ANTHROPIC_API_KEY=\nXAI_API_KEY=\n", encoding="utf-8")
    old = tmp_path / "data" / "dashboard" / ".env"
    old.parent.mkdir(parents=True)
    old.write_text('GEMINI_API_KEY="LEGACY_GEMINI_KEY"\n', encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    assert settings.ai_credentials()[2] == "LEGACY_GEMINI_KEY"
    assert not old.exists()
    env = tmp_path / ".env"
    assert "YOUTUBE_API_KEY=" in env.read_text(encoding="utf-8")
    settings.save_ai("openai", "gpt-5.4-mini", "OPENAI_KEY")
    settings.save_ai("claude", "claude-sonnet-4-6", "CLAUDE_KEY")
    settings.save_ai("grok", "grok-4.7", "XAI_KEY")
    settings.save_ai("gemini", "gemini-3.5-flash", "")
    assert settings.ai_credentials()[2] == "LEGACY_GEMINI_KEY"
    settings.save_ai("gemini", "gemini-3.5-flash", "", clear_key=True)
    assert settings.ai_credentials()[2] == ""
    settings.save_ai("openai", "gpt-5.4-mini", "")
    assert settings.ai_credentials()[2] == "OPENAI_KEY"
    settings.save_ai("claude", "claude-sonnet-4-6", "")
    assert settings.ai_credentials()[2] == "CLAUDE_KEY"
    settings.save_ai("grok", "grok-4.7", "")
    assert settings.ai_credentials()[2] == "XAI_KEY"
    assert "YOUTUBE_API_KEY=" in env.read_text(encoding="utf-8")


def test_youtube_key_save_preserves_ai_key_and_returns_no_secret(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    settings.save_ai("openai", "gpt-5.4-mini", "PRIVATE_AI_KEY")
    result = settings.save_youtube_api_key("PRIVATE_YOUTUBE_KEY")
    assert result == {"has_key": True}
    assert settings.youtube_api_key() == "PRIVATE_YOUTUBE_KEY"
    assert settings.ai_credentials()[2] == "PRIVATE_AI_KEY"
    with pytest.raises(ValueError, match="YOUTUBE_KEY_INVALID"):
        settings.save_youtube_api_key("bad\nkey")


def test_draft_comments_use_current_root_youtube_key_and_environment_fallback(tmp_path, monkeypatch):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text('YOUTUBE_API_KEY="ROOT_ONE"\n', encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts", settings=settings)
    comments = service.evidence_provider.comments
    assert isinstance(comments, YouTubeDataComments)
    requested = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps({"items": [{"snippet": {"topLevelComment": {
                "snippet": {"textDisplay": "인기 댓글"}}}}]}).encode()

    class Opener:
        def open(self, request, timeout):
            assert timeout == 10
            requested.append(parse_qs(urlsplit(request.full_url).query)["key"][0])
            return Response()

    with patch("marketing_agent.captions.build_opener", return_value=Opener()):
        assert comments.fetch(VIDEO_ID) == ("인기 댓글",)
        env.write_text('YOUTUBE_API_KEY="ROOT_TWO"\n', encoding="utf-8")
        assert comments.fetch(VIDEO_ID) == ("인기 댓글",)
        monkeypatch.setenv("YOUTUBE_API_KEY", "PROCESS_FALLBACK")
        env.write_text("YOUTUBE_API_KEY=\n", encoding="utf-8")
        assert comments.fetch(VIDEO_ID) == ("인기 댓글",)
    assert requested == ["ROOT_ONE", "ROOT_TWO", "PROCESS_FALLBACK"]
    monkeypatch.delenv("YOUTUBE_API_KEY")
    with pytest.raises(ValueError, match="COMMENTS_KEY_MISSING"):
        comments.fetch(VIDEO_ID)
    env.write_text("YOUTUBE_API_KEY=ROOT_THREE\n", encoding="utf-8")
    settings.save_ai("openai", "gpt-5.4-mini", "AI_TEST_KEY")
    assert settings.youtube_api_key() == "ROOT_THREE"


def test_ai_env_migration_failure_preserves_original_key_file(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    old = tmp_path / "data" / "dashboard" / ".env"
    old.parent.mkdir(parents=True)
    old.write_text('GEMINI_API_KEY="ORIGINAL_KEY"\n', encoding="utf-8")
    with patch.object(DashboardSettings, "_write_ai_env", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            DashboardSettings(tmp_path / "config.yaml")
    assert old.is_file()
    assert not (tmp_path / ".env").exists()


def test_dashboard_video_assignment_is_durable_and_round_robin(tmp_path):
    from datetime import datetime, timezone
    cards = [VideoCard(f"AbCdEfGhI{i:02d}", "UCxlc0Ky0aWoD8uI09ad44Tg",
                       "채널", f"제목 {i}", f"2026-10-{i+1:02d}", "") for i in range(5)]
    path = tmp_path / "posts.db"
    with Store(path) as store:
        store.assign_dashboard_videos(reversed(cards), ["유튜브1", "유튜브2", "유튜브3"],
                                      datetime.now(timezone.utc))
        assert [store.dashboard_assignment(card.video_id)["profile"] for card in cards] == [
            "유튜브1", "유튜브2", "유튜브3", "유튜브1", "유튜브2"]
    with Store(path) as store:
        store.assign_dashboard_videos(cards, ["유튜브3"], datetime.now(timezone.utc))
        assert [store.dashboard_assignment(card.video_id)["profile"] for card in cards] == [
            "유튜브1", "유튜브2", "유튜브3", "유튜브1", "유튜브2"]


def test_private_settings_ui_saves_channels_and_rejects_cross_origin(tmp_path):
    example = dict(DashboardSettings.DEFAULT)
    example["api_key"] = "PRIVATE_TEST_VALUE"
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(example, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts",
                                       settings=settings, feed_loader=lambda: VideoList())
    with running_server(service) as port:
        page = request(port, "GET", "/")[1]
        assert "채널 관리" in page and "options-open" in page
        assert "고급 설정" not in page and "settings-yaml" not in page
        assert "PRIVATE_TEST_VALUE" not in page
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        assert request(port, "GET", "/api/settings")[0] == 403
        status, result = request(port, "GET", "/api/settings", token=token)
        assert status == 200
        original = json.loads(result)["yaml"]
        assert "PRIVATE_TEST_VALUE" not in original
        updated = original.replace("UCkGl2jieOVhGiHPdXF77Yyw", "UCabcdefghijklmnopqrstuv")
        body = json.dumps({"yaml": updated})
        endpoint = "/api/settings"
        assert request(port, "POST", endpoint, token=token, body=body)[0] == 403
        assert request(port, "POST", endpoint, origin="http://evil.example",
                       token=token, body=body)[0] == 403
        assert request(port, "POST", endpoint, origin=f"http://{HOST}:{port}",
                       token="wrong", body=body)[0] == 403
        assert not (tmp_path / "config.yaml").exists()
        status, result = request(port, "POST", endpoint, origin=f"http://{HOST}:{port}",
                                 token=token, body=body)
        assert status == 200
        assert "UCabcdefghijklmnopqrstuv" in json.loads(result)["yaml"]
        assert "UCabcdefghijklmnopqrstuv" in settings.channels()
        saved = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        assert saved["api_key"] == "PRIVATE_TEST_VALUE"
        assert saved["channels"][-1] == "UCabcdefghijklmnopqrstuv"
        bad = updated.replace("daily_max_comments: 10", "daily_max_comments: 100")
        status, result = request(port, "POST", endpoint, origin=f"http://{HOST}:{port}",
                                 token=token, body=json.dumps({"yaml": bad}))
        assert status == 400
        assert json.loads(result)["reason_code"] == "SETTINGS_LIMIT_PDF_LOCKED"
        assert settings.channels()["UCabcdefghijklmnopqrstuv"] == ""


def test_channel_dialog_api_adds_sixth_channel_without_exposing_secrets(tmp_path):
    example = dict(DashboardSettings.DEFAULT)
    example["api_key"] = "SECRET_KEEP"
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(example, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts",
                                       settings=settings, feed_loader=lambda: VideoList())
    extra = "UCabcdefghijklmnopqrstuv"
    with running_server(service) as port:
        page = request(port, "GET", "/")[1]
        assert "SECRET_KEEP" not in page
        assert "id=\"channel-dialog\"" in page
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        assert request(port, "GET", "/api/channels")[0] == 403
        status, result = request(port, "GET", "/api/channels", token=token)
        assert status == 200
        original = json.loads(result)["channels"]
        assert len(original) == 5 and "SECRET_KEEP" not in result
        updated = original + [extra]
        body = json.dumps({"channels": updated})
        endpoint = "/api/channels"
        assert request(port, "POST", endpoint, token=token, body=body)[0] == 403
        assert request(port, "POST", endpoint, origin="http://evil.example",
                       token=token, body=body)[0] == 403
        assert not (tmp_path / "config.yaml").exists()
        status, result = request(port, "POST", endpoint,
                                 origin=f"http://{HOST}:{port}", token=token, body=body)
        assert status == 200 and json.loads(result)["channels"] == updated
        saved = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        assert saved["api_key"] == "SECRET_KEEP"
        assert saved["channels"] == updated and extra in settings.channels()
        bad = json.dumps({"channels": updated + [extra]})
        assert request(port, "POST", endpoint, origin=f"http://{HOST}:{port}",
                       token=token, body=bad)[0] == 400
        assert settings.channel_ids() == updated
        with patch("marketing_agent.dashboard.check_channel_connection",
                   return_value={"channel_id": extra, "connected": True, "video_count": 0}) as probe:
            test_body = json.dumps({"channel_id": extra})
            assert request(port, "POST", "/api/channels/test", token=token,
                           body=test_body)[0] == 403
            assert probe.call_count == 0
            status, result = request(port, "POST", "/api/channels/test",
                                     origin=f"http://{HOST}:{port}", token=token,
                                     body=test_body)
            assert status == 200 and json.loads(result)["video_count"] == 0
            probe.assert_called_once_with(extra)
        assert no_post_attempts(tmp_path / "posts.db")


def test_channel_connection_checks_requested_rss_channel_id():
    channel_id = "UCabcdefghijklmnopqrstuv"
    feed = (f'<feed xmlns="http://www.w3.org/2005/Atom" '
            f'xmlns:yt="http://www.youtube.com/xml/schemas/2015">'
            f'<yt:channelId>{channel_id}</yt:channelId></feed>').encode()
    result = check_channel_connection(channel_id, fetch=lambda _id, **_: feed)
    assert result == {"channel_id": channel_id, "channel_name": "",
                      "connected": True, "video_count": 0}
    try:
        check_channel_connection("bad", fetch=lambda _id, **_: feed)
    except ValueError as exc:
        assert str(exc) == "SETTINGS_CHANNEL_ID_INVALID"
    else:
        assert False, "invalid ID must be rejected before RSS fetch"
    try:
        check_channel_connection(next(iter(DashboardSettings.DEFAULT["channels"])),
                                 fetch=lambda _id, **_: feed)
    except ValueError as exc:
        assert str(exc) == "RSS_CHANNEL_MISMATCH"
    else:
        assert False, "mismatched RSS channel must be rejected"


def test_channel_id_entries_save_optional_names(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    (tmp_path / ".env").write_text("YOUTUBE_API_KEY=SEARCH_KEY\n", encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts",
                                       settings=settings, feed_loader=lambda: VideoList())
    entries = settings.channel_entries()
    entries[0] = {**entries[0], "channel_name": "사람이 읽는 채널명"}
    with running_server(service) as port:
        page = request(port, "GET", "/")[1]
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        status, result = request(port, "POST", "/api/channels",
                                 origin=f"http://{HOST}:{port}", token=token,
                                 body=json.dumps({"entries": entries}))
        assert status == 200
        assert json.loads(result)["entries"][0]["channel_name"] == "사람이 읽는 채널명"
        assert DashboardSettings(tmp_path / "config.yaml").channel_entries()[0] == entries[0]
        entries[0]["channel_name"] = ""
        status, result = request(port, "POST", "/api/channels",
                                 origin=f"http://{HOST}:{port}", token=token,
                                 body=json.dumps({"entries": entries}))
        assert status == 200 and json.loads(result)["entries"][0]["channel_name"] == ""


def test_ai_settings_are_write_only_and_test_requires_local_request_checks(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts",
                                       settings=settings, feed_loader=lambda: VideoList())
    with patch.dict("os.environ", {}, clear=True), running_server(service) as port:
        page = request(port, "GET", "/")[1]
        assert 'id="options-menu"' in page and 'id="ai-dialog"' in page
        assert "gpt-5-nano" in page and "gemini-3.5-flash-lite" in page
        assert "claude-haiku-4-5" in page and "grok-4-1-fast-non-reasoning" in page
        assert "추천" in page and "직접 입력" in page
        assert "updateCommentLength" in page and "await selectVideo(saved.video_id)" in page
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        assert request(port, "GET", "/api/ai")[0] == 403
        public = json.loads(request(port, "GET", "/api/ai", token=token)[1])
        assert public == {"provider": "openai", "model": "gpt-5.4-mini",
                          "has_key": False, "key_source": "none"}
        body = json.dumps({"provider": "openai", "model": "gpt-5.4-mini",
                           "api_key": "PRIVATE_AI_TEST_KEY", "clear_key": False})
        endpoint = "/api/ai"
        assert request(port, "POST", endpoint, token=token, body=body)[0] == 403
        assert request(port, "POST", endpoint, token=token, origin="http://evil.example",
                       body=body)[0] == 403
        assert request(port, "POST", endpoint, token="wrong",
                       origin=f"http://{HOST}:{port}", body=body)[0] == 403
        assert not (tmp_path / "config.yaml").exists()
        status, result = request(port, "POST", endpoint, token=token,
                                 origin=f"http://{HOST}:{port}", body=body)
        assert status == 200 and "PRIVATE_AI_TEST_KEY" not in result
        assert settings.ai_credentials() == ("openai", "gpt-5.4-mini", "PRIVATE_AI_TEST_KEY")
        assert "PRIVATE_AI_TEST_KEY" not in request(port, "GET", "/api/ai", token=token)[1]
        assert "PRIVATE_AI_TEST_KEY" not in settings.yaml_text()
        settings.save_channels(settings.channel_ids())
        assert settings.ai_credentials()[2] == "PRIVATE_AI_TEST_KEY"
        with patch("marketing_agent.dashboard_service.test_ai_connection", return_value=True) as probe:
            assert request(port, "POST", "/api/ai/test", host="evil.example",
                           token=token, origin=f"http://{HOST}:{port}", body="{}")[0] == 403
            assert request(port, "POST", "/api/ai/test", token=token,
                           body="{}")[0] == 403
            assert request(port, "POST", "/api/ai/test", token=token,
                           origin="http://evil.example", body="{}")[0] == 403
            probe.assert_not_called()
            status, result = request(port, "POST", "/api/ai/test", token=token,
                                     origin=f"http://{HOST}:{port}", body="{}")
            assert status == 200 and json.loads(result)["connected"]
            probe.assert_called_once_with("openai", "gpt-5.4-mini", "PRIVATE_AI_TEST_KEY")
        switch = json.dumps({"provider": "grok", "model": "grok-4.7",
                             "api_key": "", "clear_key": False})
        assert request(port, "POST", endpoint, token=token,
                       origin=f"http://{HOST}:{port}", body=switch)[0] == 200
        assert settings.ai_credentials() == ("grok", "grok-4.7", "")
        assert request(port, "POST", "/api/ai/test", token=token,
                       origin=f"http://{HOST}:{port}", body="{}")[0] == 409
        settings.save_ai("grok", "grok-4.7", "SECOND_PRIVATE_KEY")
        settings.save_ai("grok", "grok-4.7", "")
        assert settings.ai_credentials()[2] == "SECOND_PRIVATE_KEY"
        settings.save_ai("grok", "grok-4.7", "", clear_key=True)
        assert settings.ai_credentials()[2] == ""
        assert no_post_attempts(tmp_path / "posts.db")
    with running_server(DemoService()) as port:
        page = request(port, "GET", "/")[1]
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        assert request(port, "GET", "/api/ai", token=token)[0] == 404
        assert request(port, "POST", "/api/ai/test", token=token,
                       origin=f"http://{HOST}:{port}", body="{}")[0] == 404


def test_profile_settings_list_only_app_profiles_and_select_by_label(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    external = tmp_path / "Chrome User Data"
    (external / "Profile 3").mkdir(parents=True)
    prior = settings._read_full()
    prior["chrome_profiles"] = {"유튜브1": {"user_data_dir": str(external),
                                         "profile_directory": "Profile 3"}}
    settings._write_full(prior)
    assert settings.profile_public()["configured"] is False
    assert settings.profile_public()["user_data_dir"] == ""
    root = tmp_path / "data" / "dashboard" / "chrome-profile-youtube2"
    (root / "Default").mkdir(parents=True)
    assert settings.profile_options_public()["options"][1] == {
        "label": "유튜브2", "memo": "", "configured": True, "connected": False, "selected": False}
    saved = settings.save_profile("유튜브2")
    assert saved == {"label": "유튜브2", "user_data_dir": str(root),
                     "profile_directory": "Default", "configured": True}
    assert settings.profile_public() == saved
    choices = settings.profile_options_public()
    assert choices["selected"] == "유튜브2"
    assert choices["options"] == [
        {"label": "유튜브1", "memo": "", "configured": False, "connected": False, "selected": False},
        {"label": "유튜브2", "memo": "", "configured": True, "connected": True, "selected": True},
        {"label": "유튜브3", "memo": "", "configured": False, "connected": False, "selected": False},
    ]
    assert "Chrome User Data" not in str(choices)
    for label in ("Profile 3", "유튜브4"):
        try:
            settings.save_profile(label)
            assert False
        except ValueError as exc:
            assert str(exc) == "PROFILE_SETTINGS_INVALID"
    try:
        settings.save_profile("유튜브3")
        assert False
    except ValueError as exc:
        assert str(exc) == "PROFILE_DIRECTORY_MISSING"
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts",
                                       settings=settings, feed_loader=lambda: VideoList())
    with running_server(service) as port:
        page = request(port, "GET", "/")[1]
        assert "profile-menu-open" in page and "profileRequired" in page
        assert "페이지를 새로고침한 뒤 다시 시도하세요" in page
        assert "profile-list" in page and "현재 계정 확인" in page
        assert "이메일 저장" not in page
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        assert request(port, "GET", "/api/profile-options")[0] == 403
        status, body = request(port, "GET", "/api/profile-options", token=token)
        assert status == 200
        assert json.loads(body)["options"][1]["label"] == "유튜브2"


def test_named_profile_addition_uses_random_private_root_and_rejects_duplicates(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    poster = VisibleChromePoster(tmp_path, "", screenshot_dir=tmp_path / "shots")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts",
                                       settings=settings, poster=poster)
    created = service.add_profile("브랜드 계정")
    assert created["label"] == "브랜드 계정"
    assert re.fullmatch(r"p-[a-f0-9]{16}", created["profile_id"])
    root = settings.app_profile_root("브랜드 계정")
    assert root.name == "chrome-profile-" + created["profile_id"]
    assert "브랜드 계정" not in str(root)
    assert (root / "Default").is_dir()
    option = settings.profile_options_public()["options"][-1]
    assert option["label"] == "브랜드 계정" and option["configured"] and option["connected"]
    with pytest.raises(ValueError, match="PROFILE_NAME_DUPLICATE"):
        settings.add_profile("  브랜드 계정  ")
    with pytest.raises(ValueError, match="PROFILE_NAME_INVALID"):
        settings.add_profile("잘못된/이름")
    restarted = DashboardSettings(tmp_path / "config.yaml")
    assert restarted.app_profile_root("브랜드 계정") == root
    with running_server(service) as port:
        page = request(port, "GET", "/")[1]
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        body = json.dumps({"label": "추가 계정"})
        assert request(port, "POST", "/api/profile/add", token=token, body=body)[0] == 403
        status, response = request(port, "POST", "/api/profile/add", token=token,
                                   origin=f"http://{HOST}:{port}", body=body)
        assert status == 200 and json.loads(response)["label"] == "추가 계정"
        status, response = request(port, "POST", "/api/profile/add", token=token,
                                   origin=f"http://{HOST}:{port}", body=body)
        assert status == 400 and json.loads(response)["reason_code"] == "PROFILE_NAME_DUPLICATE"
    for index in range(15):
        settings.add_profile(f"추가 {index}")
    with pytest.raises(ValueError, match="PROFILE_LIMIT_REACHED"):
        settings.add_profile("한도 초과")


def test_explicit_ai_generation_and_human_approval_do_not_post(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    settings.save_ai("openai", "gpt-5.4-mini", "PRIVATE_AI_TEST_KEY")
    root = settings.app_profile_root("유튜브1")
    (root / "Default").mkdir(parents=True)
    settings.save_profile("유튜브1")
    card = VideoCard(VIDEO_ID, "UCxlc0Ky0aWoD8uI09ad44Tg", "채널", "답장이 늦어질 때", "2026-10-15", "")
    evidence = type("Evidence", (), {"collect": lambda self, _card: EvidenceResult(
        "답장이 늦어질 때 자막 장면\n[인기 댓글]\n공감 댓글", ("자막", "인기 댓글"))})()
    response = {"worry_summary": "답장이 늦어 불안한 마음", "cited_detail": "답장이 늦어질 때",
                "comment": "답장이 늦어질 때 마음이 특히 남네요. 기다리는 동안 운명원 연애 사주로 관계의 흐름을 살펴보고 싶어져요."}
    calls = []
    class FakeGenerator:
        def generate(self, provider, model, key, prompt):
            calls.append((provider, model, key, prompt))
            return response
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts", settings=settings,
                                       evidence_provider=evidence, draft_generator=FakeGenerator(),
                                       feed_loader=lambda: VideoList((card,)))
    service.list_videos()
    generated = service.generate_draft(VIDEO_ID)
    assert calls[0][:3] == ("openai", "gpt-5.4-mini", "PRIVATE_AI_TEST_KEY")
    assert isinstance(calls[0][3], DraftPrompt)
    assert json.loads(calls[0][3].user)["evidence"] == "답장이 늦어질 때 자막 장면\n[인기 댓글]\n공감 댓글"
    assert generated["comment"] == response["comment"]
    assert generated["source_text"] == "답장이 늦어질 때 자막 장면\n[인기 댓글]\n공감 댓글"
    assert service.select_video(VIDEO_ID).source_text == generated["source_text"]
    assert service.select_video(VIDEO_ID).reason_code == "APPROVAL_MISSING"
    approved = service.approve_draft(VIDEO_ID, {key: generated[key] for key in
                                                ("worry_summary", "cited_detail", "comment")} | {"reviewer": "reviewer"})
    assert approved["can_post"] is True
    # The browser re-selects after approval so the posting guard has a fresh
    # approval hash before it evaluates the profile requirement.
    preview = service.select_video(VIDEO_ID)
    assert preview.source_text == generated["source_text"]
    assert preview.reason_code == "PROFILE_NOT_CONFIGURED"
    assert service.post_video(VIDEO_ID).reason_code == "PROFILE_NOT_CONFIGURED"
    with Store(tmp_path / "posts.db") as store:
        assert store.db.execute("SELECT COUNT(*) FROM dashboard_post_reservations").fetchone()[0] == 0


def test_brand_settings_http_validation_and_reference_only(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts", settings=settings)
    with running_server(service) as port:
        page = request(port, "GET", "/")[1]
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        assert "댓글 생성 관리" in page and "추후 브랜드 설명을 고칠 때" in page
        assert request(port, "GET", "/api/brand")[0] == 403
        assert request(port, "POST", "/api/brand", token=token,
                       body=json.dumps({"name": "별빛", "description": "관계 상담", "reference_url": ""}))[0] == 403
        origin = f"http://{HOST}:{port}"
        invalid = {"name": "", "description": "관계 상담", "reference_url": ""}
        status, body = request(port, "POST", "/api/brand", token=token, origin=origin,
                               body=json.dumps(invalid))
        assert status == 400 and json.loads(body)["reason_code"] == "BRAND_NAME_INVALID"
        invalid["name"] = "별빛"
        invalid["reference_url"] = "file:///private/data"
        assert request(port, "POST", "/api/brand", token=token, origin=origin,
                       body=json.dumps(invalid))[0] == 400
        invalid["reference_url"] = "https://brand.example/about"
        assert request(port, "POST", "/api/brand", token=token, origin=origin,
                       body=json.dumps(invalid))[0] == 200
        saved = json.loads(request(port, "GET", "/api/brand", token=token)[1])
        assert saved == invalid
    assert DashboardSettings(tmp_path / "config.yaml").brand_public() == invalid


def test_brand_prompt_uses_description_but_never_reference_url(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    settings.save_brand("별빛", "연애 고민을 대화로 살펴보는 브랜드", "https://brand.example/private-reference")
    settings.save_ai("openai", "gpt-5.4-mini", "PRIVATE_AI_TEST_KEY")
    card = VideoCard(VIDEO_ID, "UCxlc0Ky0aWoD8uI09ad44Tg", "채널", "답장이 늦어질 때", "2026-10-15", "")
    evidence = type("Evidence", (), {"collect": lambda self, _card: EvidenceResult("답장이 늦어질 때 자막", ("자막",))})()
    response = {"worry_summary": "답장이 늦어 불안함", "cited_detail": "답장이 늦어질 때",
                "comment": "답장이 늦어질 때 마음이 복잡하네요. 별빛과 함께 서로의 대화를 차분히 돌아보면 어떨지 궁금해져요."}
    calls = []
    class FakeGenerator:
        def generate(self, provider, model, key, prompt):
            calls.append(prompt)
            return response
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts", settings=settings,
                                       evidence_provider=evidence, draft_generator=FakeGenerator(),
                                       feed_loader=lambda: VideoList((card,)))
    service._videos[VIDEO_ID] = card
    service._assigned_profile = lambda _: "유튜브1"
    generated = service.generate_draft(VIDEO_ID)
    prompt = json.loads(calls[0].user)
    assert prompt["brand"] == {"name": "별빛", "description": "연애 고민을 대화로 살펴보는 브랜드"}
    assert "brand.example" not in calls[0].user + calls[0].system
    assert service.approve_draft(VIDEO_ID, {key: generated[key] for key in
                                           ("worry_summary", "cited_detail", "comment")} | {"reviewer": "reviewer"})["can_post"]
    settings.save_brand("별빛", "연애 고민을 대화로 살펴보는 브랜드", "https://brand.example/updated-reference")
    assert service.select_video(VIDEO_ID).reason_code != "BRAND_CHANGED_REGENERATE"
    settings.save_brand("별빛", "새로운 설명", "https://brand.example/private-reference")
    assert service.select_video(VIDEO_ID).reason_code != "BRAND_CHANGED_REGENERATE"   # IMP-26: tone only
    settings.save_brand("달빛", "새로운 설명", "https://brand.example/private-reference")
    assert service.select_video(VIDEO_ID).reason_code == "BRAND_CHANGED_REGENERATE"


def test_comment_generation_defaults_save_and_validation(tmp_path):
    source = dict(DashboardSettings.DEFAULT)
    source.pop("comment")
    (tmp_path / "config.example.yaml").write_text(yaml.safe_dump(source, allow_unicode=True), encoding="utf-8")
    path = tmp_path / "config.yaml"
    settings = DashboardSettings(path)
    assert not path.exists()
    assert settings.comment_limits() == {"min_chars": 40, "max_chars": 120}
    with pytest.raises(ValueError, match="COMMENT_LENGTH_SETTINGS_INVALID"):
        settings.save_comment_generation("별빛", "연애 대화", "", 121, 120)
    with pytest.raises(ValueError, match="COMMENT_LENGTH_SETTINGS_INVALID"):
        settings.save_comment_generation("별빛", "연애 대화", "", True, 120)
    assert not path.exists()
    saved = settings.save_comment_generation("별빛", "연애 대화", "", 30, 150)
    assert saved == {"name": "별빛", "description": "연애 대화", "reference_url": "",
                     "min_chars": 30, "max_chars": 150, "review_filter": True}
    assert path.exists()
    assert DashboardSettings(path).comment_limits() == {"min_chars": 30, "max_chars": 150}
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["comment"] == {
        "brand": "운명원", "min_chars": 30, "max_chars": 150, "review_filter": True}
    assert "min_chars: 30, max_chars: 150" in settings.yaml_text()
    assert settings.save_comment_generation("별빛", "연애 대화", "", 30, 150, False)["review_filter"] is False
    assert DashboardSettings(path).review_filter_enabled() is False


def test_comment_generation_api_requires_token_and_exact_numbers(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts", settings=settings)
    with running_server(service) as port:
        page = request(port, "GET", "/")[1]
        assert "댓글 생성 관리" in page and 'id="comment-min-chars"' in page
        assert 'id="comment-max-chars"' in page and "draft.min_chars??40" in page
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        origin = f"http://{HOST}:{port}"
        assert request(port, "GET", "/api/comment-settings")[0] == 403
        assert request(port, "POST", "/api/comment-settings", token=token,
                       body=json.dumps({"name": "별빛"}))[0] == 403
        data = {"name": "별빛", "description": "연애 대화", "reference_url": "",
                "min_chars": 30, "max_chars": 150}
        invalid = {**data, "min_chars": True}
        assert request(port, "POST", "/api/comment-settings", token=token, origin=origin,
                       body=json.dumps(invalid))[0] == 400
        invalid = {**data, "min_chars": 151}
        status, response = request(port, "POST", "/api/comment-settings", token=token,
                                   origin=origin, body=json.dumps(invalid))
        assert status == 400 and json.loads(response)["reason_code"] == "COMMENT_LENGTH_SETTINGS_INVALID"
        assert request(port, "POST", "/api/comment-settings", token=token, origin=origin,
                       body=json.dumps(data))[0] == 200
        assert json.loads(request(port, "GET", "/api/comment-settings", token=token)[1]) == data | {"review_filter": True}


def test_comment_length_setting_reaches_prompt_quality_and_approval(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    settings.save_comment_generation("별빛", "연애 대화", "", 20, 150)
    settings.save_ai("openai", "gpt-5.4-mini", "PRIVATE_AI_TEST_KEY")
    card = VideoCard(VIDEO_ID, "UCxlc0Ky0aWoD8uI09ad44Tg", "채널", "답장이 늦어질 때", "2026-10-15", "")
    evidence = type("Evidence", (), {"collect": lambda self, _card: EvidenceResult("답장이 늦어질 때 자막", ("자막",))})()
    response = {"worry_summary": "답장을 기다리는 마음", "cited_detail": "답장이 늦어질 때",
                "comment": "답장이 늦어질 때 별빛의 대화가 궁금해요."}
    calls = []
    class FakeGenerator:
        def generate(self, provider, model, key, prompt):
            calls.append(prompt)
            return response
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts", settings=settings,
                                       evidence_provider=evidence, draft_generator=FakeGenerator(),
                                       feed_loader=lambda: VideoList((card,)))
    service._videos[VIDEO_ID] = card
    service._assigned_profile = lambda _: "유튜브1"
    generated = service.generate_draft(VIDEO_ID)
    assert (generated["min_chars"], generated["max_chars"]) == (20, 150)
    assert "never outside 20-150" in json.loads(calls[0].user)["instruction"]
    assert service.approve_draft(VIDEO_ID, {key: generated[key] for key in
                                           ("worry_summary", "cited_detail", "comment")} | {"reviewer": "reviewer"})["can_post"]
    assert service.select_video(VIDEO_ID).reason_code != "BRAND_CHANGED_REGENERATE"
    settings.save_comment_generation("별빛", "연애 대화", "", 45, 150)
    assert service.select_video(VIDEO_ID).reason_code == "BRAND_CHANGED_REGENERATE"


def test_default_draft_generator_uses_shared_schema():
    calls = []
    class FakeAI:
        def complete_json(self, system, user, *, response_schema=None):
            calls.append((system, user, response_schema))
            return {"comment": "test"}
    factory = lambda provider, model, key: FakeAI() if (provider, model, key) == ("mock", "model", "key") else None
    result = ProviderDraftGenerator(factory).generate("mock", "model", "key", DraftPrompt("system", "user"))
    assert result == {"comment": "test"}
    assert calls == [("system", "user", DRAFT_RESPONSE_SCHEMA)]


def test_rejected_draft_generation_never_calls_service():
    class DraftService(FakeService):
        generated = 0

        def generate_draft(self, video_id):
            self.generated += 1
            return {"video_id": video_id, "worry_summary": "고민", "cited_detail": "근거", "comment": "초안"}

    service = DraftService()
    with running_server(service) as port:
        token = re.search(r'name="session-token" content="([^"]+)"', request(port, "GET", "/")[1]).group(1)
        body = json.dumps({"video_id": VIDEO_ID})
        assert request(port, "POST", "/api/drafts/generate", host="evil.example", token=token,
                       origin=f"http://{HOST}:{port}", body=body)[0] == 403
        assert service.generated == 0 and service.posts == 0
        assert request(port, "POST", "/api/drafts/generate", token=token,
                       origin=f"http://{HOST}:{port}", body=body)[0] == 200
        assert service.generated == 1 and service.posts == 0


def test_configured_channel_drives_rss_and_test_video_conflict(tmp_path):
    channel_id = "UCabcdefghijklmnopqrstuv"
    feed = (f'<feed xmlns="http://www.w3.org/2005/Atom" '
            f'xmlns:yt="http://www.youtube.com/xml/schemas/2015">'
            f'<yt:channelId>{channel_id}</yt:channelId><title>새 채널</title><entry>'
            f'<yt:videoId>{VIDEO_ID}</yt:videoId><yt:channelId>{channel_id}</yt:channelId>'
            f'<title>새 영상</title><published>2026-10-15T00:00:00Z</published>'
            f'</entry></feed>').encode()
    channels = {channel_id: ""}
    loaded = list_videos(fetch=lambda candidate: feed, channels=channels)
    assert len(loaded.videos) == 1
    assert loaded.videos[0].channel == "새 채널"
    assert recheck_video(VIDEO_ID, channel_id, fetch=lambda candidate: feed,
                         channels=channels) == loaded.videos[0]
    assert recheck_video(VIDEO_ID, next(iter(DashboardSettings.DEFAULT["channels"])),
                         fetch=lambda candidate: feed, channels=channels) is None

    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    updated = settings.yaml_text().replace("UCkGl2jieOVhGiHPdXF77Yyw", channel_id)
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts",
        settings=settings,
        test_videos=[{"video_id": VIDEO_ID, "channel_id": channel_id, "title": "내 영상"}])
    try:
        service.save_settings_yaml(updated)
        assert False
    except ValueError as exc:
        assert str(exc) == "SETTINGS_TEST_CHANNEL_CONFLICT"
    assert not (tmp_path / "config.yaml").exists()


def test_selection_only_reads_draft():
    service = FakeService()
    with running_server(service) as port:
        page = request(port, "GET", "/")[1]
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        assert request(port, "GET", "/api/videos")[0] == 403
        assert request(port, "GET", f"/api/videos/{VIDEO_ID}/draft")[0] == 403
        assert service.selections == 0
        assert request(port, "GET", "/api/videos", token=token)[0] == 200
        status, body = request(port, "GET", f"/api/videos/{VIDEO_ID}/draft", token=token)
        assert status == 200
        assert json.loads(body)["worry_summary"] == "고민"
    assert service.selections == 1
    assert (service.posts, service.reservations, service.chrome_opens) == (0, 0, 0)


def test_offline_demo_never_invokes_posting_service():
    service = DemoService()
    with running_server(service) as port:
        status, page = request(port, "GET", "/")
        assert status == 200
        assert "오프라인 연습 모드" in page
        assert "YouTube 요청" in page
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        assert request(port, "GET", "/api/videos", token=token)[0] == 200
        status, body = request(port, "GET", f"/api/videos/{service.VIDEO_ID}/draft", token=token)
        assert status == 200 and json.loads(body)["can_post"]
        status, body = request(port, "POST", "/api/post",
                               origin=f"http://{HOST}:{port}", token=token,
                               body=json.dumps({"video_id": service.VIDEO_ID}))
        assert status == 409
        assert json.loads(body)["reason_code"] == "DEMO_NO_POST"
    with patch("marketing_agent.dashboard.run_dashboard") as run:
        assert __main__.main(["dashboard", "--demo"]) == 0
        assert isinstance(run.call_args.kwargs["service"], DemoService)
        assert run.call_args.kwargs["capture_dir"] is None
        assert __main__.main(["dashboard", "--demo", "--test-videos-config", "config.yaml"]) == 1


def test_dashboard_subcommand_connects_posting_service():
    with patch("marketing_agent.dashboard.run_dashboard") as run:
        assert __main__.main(["dashboard", "--port", "9234"]) == 0
        args = run.call_args.kwargs
        assert args["port"] == 9234
        assert args["service"].poster is not None
        expected = DashboardSettings(__main__._app_path("config.yaml")).profile_public()
        assert args["service"].poster.profile_directory == expected["profile_directory"]
        assert args["service"].daily_limit == 10
        assert args["capture_dir"] == __main__.APP_ROOT / "data/dashboard/screenshots"
    # External Chrome data roots are no longer accepted (safety rule: no reads
    # outside the dashboard folder); argparse rejects the removed options.
    with patch("marketing_agent.dashboard.run_dashboard") as run:
        for removed in ("--chrome-user-data-dir", "--chrome-profile-directory"):
            with pytest.raises(SystemExit):
                __main__.main(["dashboard", removed, "/tmp/chrome"])
        run.assert_not_called()
    assert __main__.main(["--config", "missing-config.yaml", "--once"]) == 1


def test_owned_test_video_cli_requires_explicit_local_evidence(tmp_path):
    video_id = "MyTestVid01"
    channel_id = "UCabcdefghijklmnopqrstuv"
    config = tmp_path / "config.yaml"
    config.write_text(
        "dashboard_test_videos:\n"
        f"  - video_id: {video_id}\n"
        f"    channel_id: {channel_id}\n"
        "    title: My own test video\n", encoding="utf-8")
    work_dir = tmp_path / "data"
    work_dir.mkdir()
    proof = work_dir / "ownership.txt"
    proof.write_text("Checked by the user in YouTube Studio.", encoding="utf-8")
    with patch.object(__main__, "APP_ROOT", tmp_path):
        with patch("marketing_agent.dashboard.run_dashboard") as run:
            command = ["dashboard", "--work-dir", "data", "--test-videos-config",
                       "config.yaml", "--register-owned-test-video", video_id]
            assert __main__.main(command) == 1
            run.assert_not_called()
            assert no_post_attempts(work_dir / "posts.db")
            assert __main__.main(command + ["--ownership-evidence", "config.yaml"]) == 1
            assert no_post_attempts(work_dir / "posts.db")
            assert __main__.main(command + ["--ownership-evidence", "data/ownership.txt"]) == 0
            run.assert_not_called()
            with Store(work_dir / "posts.db") as store:
                record = store.ownership(video_id)
                assert record["owner_channel_id"] == channel_id
                assert record["evidence_path"] == "ownership.txt"
            assert __main__.main(["dashboard", "--work-dir", "data",
                                  "--test-videos-config", "config.yaml"]) == 0
            assert video_id in run.call_args.kwargs["service"].test_videos
            assert __main__.main(["dashboard", "--work-dir", ".."]) == 1


def test_only_dashboard_capture_directory_is_served():
    with TemporaryDirectory() as root:
        captures = Path(root) / "screenshots"
        captures.mkdir()
        allowed = captures / f"{VIDEO_ID}-123.png"
        allowed.write_bytes(b"PNG")
        outside = Path(root) / f"{VIDEO_ID}-456.png"
        outside.write_bytes(b"PNG")
        assert _capture_url(str(allowed), captures) == f"/captures/{allowed.name}"
        assert _capture_url(str(outside), captures) == ""
        with running_server(FakeService(), capture_dir=captures) as port:
            page = request(port, "GET", "/")[1]
            token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
            assert request(port, "GET", f"/captures/{allowed.name}")[0] == 403
            assert request(port, "GET", f"/captures/{allowed.name}", token=token)[0] == 200
            assert request(port, "GET", f"/captures/{outside.name}", token=token)[0] == 404
            assert request(port, "GET", "/captures/../../secret.png")[0] == 404


def test_youtube_key_request_schema_is_strict_and_does_not_echo_key():
    class KeyService(FakeService):
        def __init__(self):
            super().__init__()
            self.saved = []

        def save_youtube_api_key(self, key):
            self.saved.append(key)
            return {"has_key": True}

    service = KeyService()
    with running_server(service) as port:
        page = request(port, "GET", "/")[1]
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        options = {"origin": f"http://{HOST}:{port}", "token": token}
        for invalid in ({}, [], {"api_key": 123}, {"api_key": "secret", "extra": True}):
            status, body = request(port, "POST", "/api/youtube-key", body=json.dumps(invalid), **options)
            assert status == 400 and json.loads(body)["reason_code"] == "BAD_REQUEST"
        assert service.saved == []
        status, body = request(port, "POST", "/api/youtube-key",
                               body=json.dumps({"api_key": "test-secret"}), **options)
        assert status == 200 and json.loads(body) == {"has_key": True}
        assert "test-secret" not in body and service.saved == ["test-secret"]


def test_cli_error_does_not_print_exception_data(monkeypatch, capsys):
    def fail(_path):
        raise ValueError("https://example.invalid/?key=private-value")

    monkeypatch.setattr(__main__, "load_config", fail)
    assert __main__.main(["--once"]) == 1
    output = capsys.readouterr()
    assert "private-value" not in output.err
    assert "https://" not in output.err


def test_oversized_and_linked_captures_are_not_served(tmp_path):
    captures = tmp_path / "screenshots"
    captures.mkdir()
    oversized = captures / f"{VIDEO_ID}-123.png"
    with oversized.open("wb") as stream:
        stream.truncate(MAX_CAPTURE_BYTES + 1)
    assert _capture_url(str(oversized), captures) == ""
    outside = tmp_path / f"{VIDEO_ID}-456.png"
    outside.write_bytes(b"PNG")
    linked = captures / outside.name
    try:
        linked.symlink_to(outside)
    except OSError:
        linked = None
    if linked is not None:
        assert _capture_url(str(linked), captures) == ""
    with running_server(FakeService(), capture_dir=captures) as port:
        page = request(port, "GET", "/")[1]
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        assert request(port, "GET", f"/captures/{oversized.name}", token=token)[0] == 404
        if linked is not None:
            assert request(port, "GET", f"/captures/{linked.name}", token=token)[0] == 404


def test_default_chrome_user_data_root_blocks_before_store_or_chrome(tmp_path, monkeypatch):
    if os.name == "nt":
        local_app_data = tmp_path / "LocalAppData"
        root = local_app_data / "Google" / "Chrome" / "User Data"
        monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    else:  # Path.home() follows $HOME on macOS/Linux
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        root = home / ("Library/Application Support/Google/Chrome" if sys.platform == "darwin"
                       else ".config/google-chrome")
    (root / "Profile 1").mkdir(parents=True)
    poster = VisibleChromePoster(root, "Profile 1", screenshot_dir=tmp_path / "screenshots")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts", poster=poster)
    assert service._profile_reason() == "DEFAULT_CHROME_USER_DATA_DIR_UNSUPPORTED"
    with patch("marketing_agent.dashboard_service.PostingService.post_video") as post:
        result = service.post_video(VIDEO_ID)
    assert result.reason_code == "DEFAULT_CHROME_USER_DATA_DIR_UNSUPPORTED"
    post.assert_not_called()
    assert poster.events == []


def test_missing_profile_blocks_before_store_or_chrome():
    with TemporaryDirectory() as root:
        poster = VisibleChromePoster(root, "", screenshot_dir=Path(root) / "screenshots")
        service = ConfiguredPostingService(Path(root) / "posts.db", Path(root) / "drafts",
                                           poster=poster)
        with patch("marketing_agent.dashboard_service.PostingService.post_video") as post:
            result = service.post_video(VIDEO_ID)
        assert result.reason_code == "PROFILE_NOT_CONFIGURED"
        post.assert_not_called()
        assert poster.events == []


def test_app_profile_setup_is_explicit_and_keeps_existing_profile_on_failure(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    prior = tmp_path / "data" / "dashboard" / "chrome-profile-youtube1"
    (prior / "Default").mkdir(parents=True)
    settings.save_profile("유튜브1")
    poster = VisibleChromePoster(prior, "Default", screenshot_dir=tmp_path / "screenshots")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts",
                                       poster=poster, settings=settings)
    with patch("marketing_agent.dashboard_service._open_login_window",
               side_effect=ValueError("CHROME_NOT_FOUND")):
        try:
            service.open_app_profile()
            assert False
        except ValueError as exc:
            assert str(exc) == "CHROME_NOT_FOUND"
    assert settings.profile_public()["user_data_dir"] == str(prior)
    assert poster.user_data_dir == prior
    root = tmp_path / "data" / "dashboard" / "chrome-profile-youtube1"
    with patch("marketing_agent.dashboard_service._open_login_window") as launch:
        saved = service.open_app_profile("유튜브1")
    launch.assert_called_once_with(root, "akn-AvCeHBI")
    assert saved["profile_directory"] == "Default"
    assert saved["login_window_opened"] is True
    assert (root / "Default").is_dir()
    assert poster.user_data_dir == prior
    assert poster.profile_directory == "Default"
    assert service.profile == "유튜브1"
    assert no_post_attempts(tmp_path / "posts.db")


def test_login_window_opens_allowed_watch_page_not_google(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    poster = VisibleChromePoster(tmp_path, "", screenshot_dir=tmp_path / "shots")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts",
                                       settings=settings, poster=poster)
    from marketing_agent.storage import Store
    with Store(tmp_path / "posts.db") as store:   # IMP-19: 유튜브1 confirmed first
        store.set_profile_active("유튜브1", True, datetime.now(timezone.utc))
    with patch("marketing_agent.dashboard_service._open_login_window") as launch:
        service.open_app_profile("유튜브2")
        launch.assert_called_once_with(settings.app_profile_root("유튜브2"), "akn-AvCeHBI")
    assert settings.profile_public()["label"] == "유튜브1"
    assert settings.profile_options_public()["options"][1]["connected"] is True
    assert poster.user_data_dir == tmp_path
    assert no_post_attempts(tmp_path / "posts.db")
    with patch("marketing_agent.chrome_launch._installed_chrome", return_value=Path("chrome.exe")), \
         patch("marketing_agent.chrome_launch.subprocess.Popen") as start:
        from marketing_agent import chrome_launch as dashboard_module
        from marketing_agent.chrome_launch import _open_login_window
        _open_login_window(settings.app_profile_root("유튜브2"), "akn-AvCeHBI")
        second = start.call_args.args[0]
        _open_login_window(settings.app_profile_root("유튜브1"), "akn-AvCeHBI")
        first = start.call_args.args[0]
        with pytest.raises(ValueError, match="INVALID_VIDEO_ID"):
            _open_login_window(settings.app_profile_root("유튜브1"), "https://accounts.google.com/")
    assert second[-1] == first[-1] == "https://www.youtube.com/watch?v=akn-AvCeHBI&hl=ko"
    assert not hasattr(dashboard_module, "GOOGLE_LOGIN_URL")
    from marketing_agent import dashboard as dashboard_main, dashboard_service
    for module in (dashboard_main, dashboard_service, dashboard_module):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "accounts.google.com" not in source and "myaccount.google.com" not in source
    assert f"--user-data-dir={settings.app_profile_root('유튜브2')}" in second
    assert f"--user-data-dir={settings.app_profile_root('유튜브1')}" in first
    assert first != second


def test_app_profile_setup_http_boundary(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    poster = VisibleChromePoster(tmp_path, "", screenshot_dir=tmp_path / "screenshots")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts",
                                       poster=poster, settings=settings)
    with patch("marketing_agent.dashboard_service._open_login_window") as launch:
        with running_server(service) as port:
            page = request(port, "GET", "/")[1]
            assert "profile-setup" in page
            token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
            assert request(port, "GET", "/api/profile/setup", token=token)[0] == 404
            setup_body = json.dumps({"label": "유튜브1"})
            assert request(port, "POST", "/api/profile/setup", body=setup_body)[0] == 403
            assert request(port, "POST", "/api/profile/setup", token=token,
                           origin="http://evil.invalid", body=setup_body)[0] == 403
            assert request(port, "POST", "/api/profile/setup", token=token,
                           origin=f"http://{HOST}:{port}", body='{"extra":1}')[0] == 400
            assert request(port, "POST", "/api/profile/setup", token=token,
                           origin=f"http://{HOST}:{port}",
                           body=json.dumps({"label": "유튜브1", "video_id": VIDEO_ID}))[0] == 400
            launch.assert_not_called()
            status, body = request(port, "POST", "/api/profile/setup", token=token,
                                    origin=f"http://{HOST}:{port}", body=setup_body)
            assert status == 200
            assert json.loads(body)["login_window_opened"] is True
            launch.assert_called_once()
    assert no_post_attempts(tmp_path / "posts.db")


def test_profile_selection_http_uses_only_private_roots(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    root = tmp_path / "data" / "dashboard" / "chrome-profile-youtube2"
    (root / "Default").mkdir(parents=True)
    poster = VisibleChromePoster(tmp_path, "", screenshot_dir=tmp_path / "screenshots")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts",
                                       poster=poster, settings=settings)
    with running_server(service) as port:
        page = request(port, "GET", "/")[1]
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        body = json.dumps({"label": "유튜브2"})
        assert request(port, "POST", "/api/profile", body=body)[0] == 403
        assert request(port, "POST", "/api/profile", token=token,
                       origin=f"http://{HOST}:{port}", body='{"label":"Profile 2"}')[0] == 400
        status, response = request(port, "POST", "/api/profile", token=token,
                                   origin=f"http://{HOST}:{port}", body=body)
        assert status == 200
        assert json.loads(response)["label"] == "유튜브2"
    assert poster.user_data_dir == root
    assert poster.profile_directory == "Default"
    assert service.profile == "유튜브2"
    assert no_post_attempts(tmp_path / "posts.db")


def test_app_login_window_blocks_post_until_closed(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    poster = VisibleChromePoster(tmp_path, "", screenshot_dir=tmp_path / "screenshots")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts",
                                       poster=poster, settings=settings)
    with patch("marketing_agent.dashboard_service._open_login_window") as launch:
        launch.return_value.poll.return_value = None
        service.open_app_profile()
        poster.user_data_dir = settings.app_profile_root("유튜브1")
        poster.profile_directory = "Default"
        service.profile = "유튜브1"
        assert service._profile_reason() == "PROFILE_LOCKED"
        with patch("marketing_agent.dashboard_service.PostingService.post_video") as post:
            result = service.post_video(VIDEO_ID)
        assert result.reason_code == "PROFILE_LOCKED"
        post.assert_not_called()
        assert poster.events == []
        assert no_post_attempts(tmp_path / "posts.db")
        launch.return_value.poll.return_value = 0
        assert service._profile_reason() == ""


def test_page_requires_pairing_cookie():
    with running_server(FakeService()) as port:
        status, page = request(port, "GET", "/", pair=False)
        assert status == 403
        assert "session-token" not in page
        assert "다시 여세요" in page


def test_pair_sets_cookie_and_page_has_token():
    with running_server(FakeService()) as port:
        status, _, headers = _raw_request(port, "GET", f"/pair?code={port.pair_code}")
        assert status == 303
        assert dict(headers)["Location"] == "/"
        cookie = next(v for k, v in headers if k.lower() == "set-cookie")
        assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
        status, page, _ = _raw_request(port, "GET", "/", cookie=cookie.split(";", 1)[0])
        assert status == 200
        assert 'name="session-token"' in page
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        assert token not in cookie
        # The code stays valid for repeated use.
        assert _raw_request(port, "GET", f"/pair?code={port.pair_code}")[0] == 303


def test_pair_rejects_wrong_code():
    with running_server(FakeService()) as port:
        for path in ("/pair?code=wrong", "/pair"):
            status, _, headers = _raw_request(port, "GET", path)
            assert status == 403
            assert not any(k.lower() == "set-cookie" for k, _ in headers)
        status, page, _ = _raw_request(port, "GET", "/", cookie="ma_pair=wrong")
        assert status == 403 and "session-token" not in page


def test_pair_rejects_non_ascii_code_and_cookie():
    with running_server(FakeService()) as port:
        status, _, headers = _raw_request(port, "GET", "/pair?code=%C3%A9")
        assert status == 403
        assert not any(k.lower() == "set-cookie" for k, _ in headers)
        status, page, _ = _raw_request(port, "GET", "/", cookie=f"ma_pair_{int(port)}=\u00e9")
        assert status == 403 and "session-token" not in page
        status, _, _ = _raw_request(port, "POST", "/api/post", token="\u00e9", origin=f"http://{HOST}:{int(port)}",
                                    body="{}")
        assert status == 403


def test_pair_cookie_name_includes_port_and_redirect_has_security_headers():
    with running_server(FakeService()) as port:
        status, _, headers = _raw_request(port, "GET", f"/pair?code={port.pair_code}")
        assert status == 303
        names = {k.lower(): v for k, v in headers}
        assert names["set-cookie"].startswith(f"ma_pair_{int(port)}=")
        assert names["x-content-type-options"] == "nosniff"
        assert names["x-frame-options"] == "DENY"
        assert "default-src 'self'" in names["content-security-policy"]


def test_pair_checks_host():
    with running_server(FakeService()) as port:
        status, _, headers = _raw_request(port, "GET", f"/pair?code={port.pair_code}", host="evil.example")
        assert status == 403
        assert not any(k.lower() == "set-cookie" for k, _ in headers)


def test_run_dashboard_prints_pair_url(capsys, monkeypatch):
    import marketing_agent.dashboard as dashboard

    holder = {}
    real_create = dashboard.create_server

    def capture(*args, **kwargs):
        holder["server"] = real_create(*args, **kwargs)
        return holder["server"]

    monkeypatch.setattr(dashboard, "create_server", capture)
    thread = threading.Thread(
        target=lambda: dashboard.run_dashboard(port=0, service=FakeService(), open_browser=False), daemon=True)
    thread.start()
    try:
        deadline = time.time() + 5
        out = ""
        while time.time() < deadline and "Dashboard: " not in out:
            out += capsys.readouterr().out
            time.sleep(0.05)
        server = holder["server"]
        assert f"Dashboard: http://127.0.0.1:{server.server_port}/pair?code={server.pair_code}" in out
    finally:
        if "server" in holder:
            holder["server"].shutdown()
        thread.join(timeout=5)


def test_configured_service_uses_60_minute_cooldown(tmp_path):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts", settings=settings)
    assert service.channel_cooldown_minutes == 60


# --- R3-T1 (IMP-34): the settings lock and the browser lock are separate ---------------

def _lock_service(tmp_path, generator=None, posting=True):
    (tmp_path / "config.example.yaml").write_text(
        yaml.safe_dump(DashboardSettings.DEFAULT, allow_unicode=True), encoding="utf-8")
    settings = DashboardSettings(tmp_path / "config.yaml")
    settings.save_ai("openai", "gpt-5.4-mini", "PRIVATE_AI_TEST_KEY")
    for label in ("유튜브1", "유튜브2"):
        (settings.app_profile_root(label) / "Default").mkdir(parents=True)
        settings.save_profile(label)
    settings.save_profile("유튜브1")
    root = settings.app_profile_root("유튜브1")
    poster = VisibleChromePoster(root, "Default", screenshot_dir=tmp_path / "shots")
    card = VideoCard(VIDEO_ID, "UCxlc0Ky0aWoD8uI09ad44Tg", "채널", "답장이 늦어질 때", "2026-10-15", "")
    evidence = type("Evidence", (), {"collect": lambda self, _card: EvidenceResult(
        "답장이 늦어질 때 자막 장면", ("자막",))})()
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts", settings=settings,
                                       poster=poster, evidence_provider=evidence,
                                       draft_generator=generator,
                                       feed_loader=lambda: VideoList((card,)))
    service.list_videos()
    return service, settings, poster


@contextmanager
def _blocked_post(service):
    """Hold a posting run inside the (faked) Chrome step until the test releases it."""
    started, release, seen = threading.Event(), threading.Event(), {}

    def slow_post(_self, video_id):
        seen["during"] = service.poster.user_data_dir
        started.set()
        release.wait(5)
        seen["after"] = service.poster.user_data_dir
        return PostStatus("posted")

    result = {}
    with patch("marketing_agent.dashboard_service.PostingService.post_video", slow_post):
        thread = threading.Thread(target=lambda: result.update(
            status=service.post_video(VIDEO_ID)), daemon=True)
        thread.start()
        try:
            assert started.wait(5)
            yield seen, release
        finally:
            release.set()
            thread.join(5)
    assert not thread.is_alive()


def _finishes_within(seconds, func):
    done, out = threading.Event(), {}

    def run():
        try:
            out["value"] = func()
        except Exception as exc:  # surfaced to the assertion below
            out["error"] = exc
        done.set()

    threading.Thread(target=run, daemon=True).start()
    return done.wait(seconds), out


def test_reads_do_not_wait_for_posting(tmp_path):
    service, _settings, _poster = _lock_service(tmp_path)
    with _blocked_post(service):
        for call in (service.video_states, lambda: service.select_video(VIDEO_ID),
                     service.list_videos):
            finished, out = _finishes_within(1, call)
            assert finished and "error" not in out


def test_verify_profile_waits_for_posting(tmp_path):
    service, settings, poster = _lock_service(tmp_path)
    service._set_profile_active("유튜브1", True)
    assigned_root = settings.app_profile_root(service._assigned_profile(VIDEO_ID))
    other = "유튜브2" if assigned_root == settings.app_profile_root("유튜브1") else "유튜브1"
    checked = threading.Event()
    with patch.object(poster, "check_signed_in", side_effect=lambda _id: checked.set() or ""):
        with _blocked_post(service) as (seen, release):
            verify = threading.Thread(target=lambda: service.verify_profile(other), daemon=True)
            save = threading.Thread(target=lambda: service.save_profile(other), daemon=True)
            verify.start()
            save.start()
            assert not checked.wait(0.5)
            assert poster.user_data_dir == assigned_root
            release.set()
            verify.join(5)
            save.join(5)
        assert not verify.is_alive() and not save.is_alive()
    assert seen["during"] == assigned_root and seen["after"] == assigned_root
    assert checked.is_set()


def test_generate_draft_does_not_hold_settings_lock(tmp_path):
    started, release = threading.Event(), threading.Event()

    class SlowGenerator:
        def generate(self, provider, model, key, prompt):
            started.set()
            release.wait(5)
            return {"worry_summary": "답장이 늦어 불안한 마음", "cited_detail": "답장이 늦어질 때",
                    "comment": "답장이 늦어질 때 마음이 특히 남네요. 기다리는 동안 운명원 연애 사주로 관계의 흐름을 살펴보고 싶어져요."}

    service, _settings, _poster = _lock_service(tmp_path, SlowGenerator())
    worker = threading.Thread(target=lambda: service.generate_draft(VIDEO_ID), daemon=True)
    worker.start()
    try:
        assert started.wait(5)
        finished, out = _finishes_within(1, service.video_states)
        assert finished and "error" not in out
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()


def test_generate_draft_discards_when_brand_changed(tmp_path):
    holder = {}

    class ChangingGenerator:
        def generate(self, provider, model, key, prompt):
            holder["service"].save_brand("다른브랜드", "설명", "")
            return {"worry_summary": "답장이 늦어 불안한 마음", "cited_detail": "답장이 늦어질 때",
                    "comment": "답장이 늦어질 때 마음이 특히 남네요. 기다리는 동안 운명원 연애 사주로 관계의 흐름을 살펴보고 싶어져요."}

    service, _settings, _poster = _lock_service(tmp_path, ChangingGenerator())
    holder["service"] = service
    with pytest.raises(ValueError, match="BRAND_CHANGED_REGENERATE"):
        service.generate_draft(VIDEO_ID)
    assert not (tmp_path / "drafts" / f"{VIDEO_ID}.json").exists()


def _unknown_service(tmp_path):
    service = ConfiguredPostingService(tmp_path / "posts.db", tmp_path / "drafts")
    with Store(tmp_path / "posts.db") as store:
        when = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)
        attempt = store.reserve_reviewed_post(video_id=VIDEO_ID, channel_id="ch", title="t", body_hash="b",
                                              approval_hash="a", profile="p", when=when)
        store.begin_dashboard_submit(attempt, when)
        store.finish_dashboard_post(attempt, "OUTCOME_UNKNOWN", reason_code="COMMENT_NOT_CONFIRMED")
    return service


def test_resolve_api_requires_token_and_schema(tmp_path):
    service = _unknown_service(tmp_path)
    with running_server(service) as port:
        page = request(port, "GET", "/")[1]
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        origin = f"http://{HOST}:{port}"
        good = {"video_id": VIDEO_ID, "outcome": "DISMISSED", "reviewer": "홍길동"}
        path = "/api/posts/resolve"
        assert request(port, "POST", path, body=json.dumps(good))[0] == 403
        assert request(port, "POST", path, origin=origin, token=token,
                       body=json.dumps({"video_id": VIDEO_ID, "outcome": "POSTED"}))[0] == 400
        assert request(port, "POST", path, origin=origin, token=token,
                       body=json.dumps(good | {"extra": "x"}))[0] == 400
        status, body = request(port, "POST", path, origin=origin, token=token,
                               body=json.dumps(good | {"outcome": "RESERVED"}))
        assert status == 409 and json.loads(body)["reason_code"] == "OUTCOME_INVALID"
        status, body = request(port, "POST", path, origin=origin, token=token, body=json.dumps(good))
        assert status == 200 and json.loads(body) == {"video_id": VIDEO_ID, "status": "DISMISSED"}
        status, body = request(port, "POST", path, origin=origin, token=token, body=json.dumps(good))
        assert status == 409 and json.loads(body)["reason_code"] == "OUTCOME_NOT_UNKNOWN"


def test_history_ui_has_resolve_controls(tmp_path):
    import shutil
    import subprocess
    with running_server(FakeService()) as port:
        page = request(port, "GET", "/")[1]
    assert "/api/posts/resolve" in page and "종료됨(재게시 안 함)" in page
    assert "YouTube에서 댓글이 달렸는지 직접 확인한 뒤 선택하세요" in page
    assert "댓글 확인됨" in page and "댓글 없음 — 종료" in page
    for code in ("SECRET_STORE_UNAVAILABLE", "SECRET_STORE_UNREADABLE", "SECRET_STORE_INVALID"):
        assert code in page
    assert "secrets.dpapi.json" in page
    assert "alert(" not in page.split("const HIST_STATUS", 1)[1] and "confirm(" not in page.split("const HIST_STATUS", 1)[1]
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", page, re.S)
    assert scripts
    js = tmp_path / "page.js"
    js.write_text("\n".join(scripts), encoding="utf-8")
    result = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def _wait_log(path, ready):
    """The handler logs after it responds, so poll for the expected records."""
    deadline = time.monotonic() + 3
    records = []
    while time.monotonic() < deadline:
        if path.exists():
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if ready(records):
                break
        time.sleep(0.02)
    return records


def test_server_logs_requests_without_secrets(tmp_path):
    log = tmp_path / "logs" / "req.jsonl"
    from marketing_agent.logging import RequestLogger
    with running_server(FakeService(), request_log=RequestLogger(log)) as port:
        secret = "SECRET-TOKEN-VALUE-123"
        status, _, headers = _raw_request(port, "POST", "/api/post", token=secret,
                                          origin=f"http://{HOST}:{port}", body=json.dumps({"video_id": VIDEO_ID}))
        assert status == 403
        request_id = next(v for k, v in headers if k.lower() == "x-request-id")
        _raw_request(port, "GET", f"/pair?code={port.pair_code}")
        records = _wait_log(log, lambda rs: any(r["request_id"] == request_id for r in rs)
                            and any(r["route"] == "/pair" for r in rs))
    text = log.read_text(encoding="utf-8")
    assert secret not in text and port.pair_code not in text and VIDEO_ID not in text
    post = next(r for r in records if r["request_id"] == request_id)
    assert (post["method"], post["route"], post["status"]) == ("POST", "/api/post", 403)
    assert post["reason_code"] == "FORBIDDEN" and post["error_type"] == ""
    assert any(r["route"] == "/pair" and r["status"] == 303 for r in records)


def test_server_logs_error_type_on_503(tmp_path):
    class Boom(FakeService):
        def post_video(self, video_id):
            raise RuntimeError("private detail xyz")

    log = tmp_path / "req.jsonl"
    from marketing_agent.logging import RequestLogger
    with running_server(Boom(), request_log=RequestLogger(log)) as port:
        page = request(port, "GET", "/")[1]
        token = re.search(r'name="session-token" content="([^"]+)"', page).group(1)
        status, _ = request(port, "POST", "/api/post", origin=f"http://{HOST}:{port}", token=token,
                            body=json.dumps({"video_id": VIDEO_ID}))
        assert status == 503
        records = _wait_log(log, lambda rs: any(r["status"] == 503 for r in rs))
    assert "private detail" not in log.read_text(encoding="utf-8")
    record = next(r for r in records if r["status"] == 503)
    assert record["status"] == 503 and record["error_type"] == "RuntimeError"


def _page_with_headers(port):
    status, body, headers = _raw_request(port, "GET", "/", cookie=pair_cookie(port))
    assert status == 200
    csp = next(v for k, v in headers if k.lower() == "content-security-policy")
    return body, csp


def _csp_nonce(csp):
    match = re.search(r"script-src ([^;]*)", csp)
    assert match, csp
    found = re.findall(r"'nonce-([A-Za-z0-9_-]+)'", match.group(1))
    assert len(found) == 1, csp
    return found[0]


def test_page_csp_uses_nonce_without_unsafe_inline_script():
    with running_server(FakeService()) as port:
        _, csp = _page_with_headers(port)
        script_src = re.search(r"script-src ([^;]*)", csp).group(1)
        assert "unsafe-inline" not in script_src
        assert "nonce-" in script_src
        assert "style-src 'unsafe-inline'" in csp
        status, _, headers = _raw_request(port, "GET", "/api/videos", cookie=pair_cookie(port))
        json_csp = next(v for k, v in headers if k.lower() == "content-security-policy")
        assert "script-src 'none'" in json_csp
        status, _, headers = _raw_request(port, "GET", "/", host="evil.example")
        assert status == 403
        assert "script-src 'none'" in next(v for k, v in headers if k.lower() == "content-security-policy")


def test_every_script_tag_has_matching_nonce():
    with running_server(FakeService()) as port:
        page, csp = _page_with_headers(port)
    nonce = _csp_nonce(csp)
    tags = re.findall(r"<script\b[^>]*>", page)
    assert tags and len(tags) == page.count("<script")
    assert all(tag == f'<script nonce="{nonce}">' for tag in tags)


def test_nonce_changes_per_request():
    with running_server(FakeService()) as port:
        _, first = _page_with_headers(port)
        _, second = _page_with_headers(port)
    assert _csp_nonce(first) != _csp_nonce(second)


def test_rendered_scripts_pass_node_check(tmp_path):
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    from marketing_agent.dashboard_page import render_page
    for demo in (False, True):
        page = render_page("tok", demo=demo, nonce="abc").decode("utf-8")
        scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", page, re.S)
        assert scripts
        for index, body in enumerate(scripts):
            path = tmp_path / f"s{int(demo)}{index}.js"
            path.write_text(body, encoding="utf-8")
            result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
            assert result.returncode == 0, result.stderr


def test_page_has_no_csp_violations_in_headless_browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        with sync_api.sync_playwright() as pw:
            browser = pw.chromium.launch()
    except Exception as exc:  # browser binary missing
        pytest.skip(f"chromium unavailable: {type(exc).__name__}")
    with running_server(FakeService()) as port, browser:
        page = browser.new_page()
        messages = []
        page.on("console", lambda m: messages.append(m.text))
        page.context.add_cookies([{"name": pair_cookie(port).split("=", 1)[0],
                                   "value": pair_cookie(port).split("=", 1)[1],
                                   "url": f"http://{HOST}:{int(port)}/"}])
        page.goto(f"http://{HOST}:{int(port)}/")
        page.wait_for_timeout(500)
    assert [m for m in messages if "Content Security Policy" in m] == []


def test_render_page_requires_nonce():
    from marketing_agent.dashboard_page import render_page
    with pytest.raises(ValueError, match="NONCE_REQUIRED"):
        render_page("tok", nonce="")


def test_render_page_nonce_check_survives_optimize():
    import ast
    import marketing_agent.dashboard_page as page_module
    tree = ast.parse(Path(page_module.__file__).read_text(encoding="utf-8"))
    nonce_asserts = [n for n in ast.walk(tree) if isinstance(n, ast.Assert)
                     and "nonce" in ast.dump(n.test) + (ast.dump(n.msg) if n.msg else "")]
    assert nonce_asserts == []
