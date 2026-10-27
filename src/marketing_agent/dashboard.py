"""Loopback dashboard and guarded HTTP boundary."""

from __future__ import annotations

from dataclasses import asdict, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
import time
import uuid
from pathlib import Path
import re
import secrets
from urllib.parse import parse_qs, urlsplit
import webbrowser

from .chrome_launch import watch_url  # noqa: F401  (re-export)
from .dashboard_settings import DashboardSettings  # noqa: F401  (re-export)
from .dashboard_service import (  # noqa: F401  (re-exports)
    VIDEO_ID, ConfiguredPostingService, DemoService, check_channel_connection,
)
from .dashboard_contracts import (
    AIReadService,
    AITestService,
    AIWriteService,
    BAD_REQUEST,
    ChannelEntryReadService,
    BrandReadService,
    BrandWriteService,
    CommentGenerationReadService,
    CommentGenerationWriteService,
    ChannelEntryWriteService,
    ChannelReadService,
    ChannelWriteService,
    DashboardService,
    ReviewPickService,
    DraftApprovalService,
    OutcomeResolveService,
    DraftGenerationService,
    DraftRefineService,
    HistoryService,
    SetupStatusService,
    FORBIDDEN,
    INTERNAL_ERROR,
    INVALID_VIDEO_ID,
    METHOD_NOT_ALLOWED,
    ProfileAddService,
    ProfileMemoService,
    ProfileOpenService,
    ProfileOptionsService,
    ProfileReadService,
    ProfileVerifyService,
    ProfileWriteService,
    SettingsReadService,
    SettingsWriteService,
    VideoStateService,
    YouTubeKeyService,
)
from .dashboard_ui import FeedDraftService
from .dashboard_page import render_page as _page
from .logging import RequestLogger, request_route


HOST = "127.0.0.1"
MAX_CAPTURE_BYTES = 10 * 1024 * 1024
CAPTURE_NAME = re.compile(r"[A-Za-z0-9_-]{11}-[0-9]+\.png\Z")

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


PAIR_HELP_PAGE = (
    '<!doctype html><html lang="ko"><meta charset="utf-8"><title>대시보드 연결</title>'
    "<p>대시보드를 실행한 창에 표시된 주소로 다시 여세요.</p></html>"
)


def _pair_match(left: str, right: str) -> bool:
    """Pairing check: constant-time compare that tolerates non-ASCII header/query text."""
    return secrets.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


_CSP_TEMPLATE = ("default-src 'self'; img-src 'self' https://i.ytimg.com; script-src {script_src}; "
        "style-src 'unsafe-inline'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
_CSP = _CSP_TEMPLATE.format(script_src="'none'")


def _page_csp(nonce: str) -> str:
    return _CSP_TEMPLATE.format(script_src=f"'nonce-{nonce}'")


def create_server(service: DashboardService | None = None, *, port: int = 0,
                  capture_dir: str | Path | None = None,
                  request_log: RequestLogger | None = None) -> ThreadingHTTPServer:
    """Bind to loopback and call the poster only after request checks."""
    service = service if service is not None else FeedDraftService()
    token = secrets.token_urlsafe(32)
    pair_code = secrets.token_urlsafe(24)
    pair_cookie = secrets.token_urlsafe(32)  # separate from the API session token
    captures = Path(capture_dir) if capture_dir is not None else None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        _request_id = ""
        _status = 0
        _reason = ""
        _error_type = ""

        def send_response(self, code: int, message: str | None = None) -> None:
            super().send_response(code, message)
            self._status = int(code)
            if self._request_id:
                self.send_header("X-Request-Id", self._request_id)

        def _logged(self, handler) -> None:
            self._request_id = uuid.uuid4().hex[:12]
            self._status, self._reason, self._error_type = 0, "", ""
            started = time.monotonic()
            try:
                handler()
            finally:
                if request_log is not None:
                    try:
                        request_log.emit(
                            request_id=self._request_id, method=self.command or "",
                            route=request_route(urlsplit(self.path).path), status=self._status,
                            reason_code=self._reason, error_type=self._error_type,
                            duration_ms=int((time.monotonic() - started) * 1000))
                    except Exception:  # a log failure must never change the response
                        pass

        def do_GET(self) -> None:
            self._logged(self._handle_get)

        def do_POST(self) -> None:
            self._logged(self._handle_post)

        def _headers(self, status: int, content_type: str, size: int, csp: str = _CSP) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", csp)
            self.end_headers()

        def _json(self, status: int, payload: object) -> None:
            if isinstance(payload, dict) and isinstance(payload.get("reason_code"), str):
                self._reason = payload["reason_code"]
                active = sys.exc_info()[1]
                if status >= 500 and active is not None:
                    self._error_type = type(active).__name__
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
            supplied = self.headers.get("X-Session-Token", "")
            return secrets.compare_digest(supplied.encode("utf-8"), token.encode("utf-8"))

        def _paired(self) -> bool:
            cookie_name = f"ma_pair_{self.server.server_port}"
            for part in self.headers.get("Cookie", "").split(";"):
                name, _, value = part.strip().partition("=")
                if name == cookie_name and _pair_match(value, pair_cookie):
                    return True
            return False

        def _unpaired_page(self) -> None:
            body = PAIR_HELP_PAGE.encode("utf-8")
            self._headers(403, "text/html; charset=utf-8", len(body))
            self.wfile.write(body)

        def _handle_get(self) -> None:
            if not self._host_ok():
                return self._reject(403, FORBIDDEN)
            if urlsplit(self.path).path == "/pair":
                code = parse_qs(urlsplit(self.path).query).get("code", [""])[0]
                if not _pair_match(code, pair_code):
                    return self._unpaired_page()
                self.send_response(303)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie",
                                 f"ma_pair_{self.server.server_port}={pair_cookie}; HttpOnly; SameSite=Strict; Path=/")
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", _CSP)
                return self.end_headers()
            if self.path == "/":
                if not self._paired():
                    return self._unpaired_page()
                nonce = secrets.token_urlsafe(16)
                body = _page(token, demo=isinstance(service, DemoService), nonce=nonce)
                self._headers(200, "text/html; charset=utf-8", len(body), _page_csp(nonce))
                return self.wfile.write(body)
            if self.path == "/api/videos":
                if not self._session_ok():
                    return self._reject(403, FORBIDDEN)
                try:
                    result = asdict(service.list_videos())
                    if isinstance(service, VideoStateService):
                        result["states"] = service.video_states()
                    if isinstance(service, ReviewPickService):
                        result["featured"] = service.review_pick()
                    return self._json(200, result)
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/settings" and isinstance(service, SettingsReadService):
                if not self._session_ok():
                    return self._reject(403, FORBIDDEN)
                try:
                    return self._json(200, {"yaml": service.settings_yaml()})
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/channels" and isinstance(service, ChannelReadService):
                if not self._session_ok():
                    return self._reject(403, FORBIDDEN)
                try:
                    entries = service.channel_entries() if isinstance(service, ChannelEntryReadService) else [
                        {"channel_name": channel_id, "channel_id": channel_id}
                        for channel_id in service.channel_ids()]
                    return self._json(200, {"channels": service.channel_ids(), "entries": entries})
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/ai" and isinstance(service, AIReadService):
                if not self._session_ok():
                    return self._reject(403, FORBIDDEN)
                try:
                    return self._json(200, service.ai_public())
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/brand" and isinstance(service, BrandReadService):
                if not self._session_ok():
                    return self._reject(403, FORBIDDEN)
                try:
                    return self._json(200, service.brand_public())
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/comment-settings" and isinstance(service, CommentGenerationReadService):
                if not self._session_ok():
                    return self._reject(403, FORBIDDEN)
                try:
                    return self._json(200, service.comment_generation_public())
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/profile" and isinstance(service, ProfileReadService):
                if not self._session_ok():
                    return self._reject(403, FORBIDDEN)
                try:
                    return self._json(200, service.profile_public())
                except Exception:
                    return self._reject(503, INTERNAL_ERROR)
            if self.path == "/api/profile-options" and isinstance(service, ProfileOptionsService):
                if not self._session_ok():
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
                if not self._session_ok():
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

        def _handle_post(self) -> None:
            if not self._host_ok():
                return self._reject_early_post(403, FORBIDDEN)
            if self.path not in {"/api/post", "/api/settings", "/api/channels",
                                 "/api/channels/test", "/api/ai", "/api/ai/test", "/api/brand", "/api/comment-settings", "/api/youtube-key",
                                 "/api/profile", "/api/profile/add", "/api/profile/memo", "/api/profile/verify", "/api/profile/setup", "/api/drafts/generate", "/api/drafts/approve", "/api/drafts/refine", "/api/posts/resolve"}:
                return self._reject(404, BAD_REQUEST)
            if self.headers.get("Origin") != f"http://{HOST}:{self.server.server_port}":
                return self._reject_early_post(403, FORBIDDEN)
            if not self._session_ok():
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
                elif self.path == "/api/posts/resolve":
                    if (not isinstance(data, dict) or set(data) != {"video_id", "outcome", "reviewer"}
                            or any(not isinstance(value, str) for value in data.values())
                            or not VIDEO_ID.fullmatch(data["video_id"])):
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
            if self.path == "/api/posts/resolve":
                if not isinstance(service, OutcomeResolveService):
                    return self._reject(404, BAD_REQUEST)
                try:
                    return self._json(200, service.resolve_outcome(data["video_id"], data["outcome"], data["reviewer"]))
                except ValueError as exc:
                    reason = str(exc)
                    return self._reject(409, reason if reason in {"OUTCOME_NOT_UNKNOWN", "OUTCOME_INVALID", "REVIEWER_INVALID"}
                                        else "OUTCOME_RESOLVE_FAILED")
                except OSError:
                    return self._reject(503, "OUTCOME_RESOLVE_FAILED")
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

    server = ThreadingHTTPServer((HOST, port), Handler)
    server.pair_code = pair_code
    return server


def run_dashboard(*, port: int = 8765, service: DashboardService | None = None,
                  capture_dir: str | Path | None = None,
                  open_browser: bool = True, port_tries: int = 1,
                  request_log: RequestLogger | None = None) -> None:
    server = None
    for candidate in range(port, port + max(1, min(int(port_tries), 20))):
        try:
            server = create_server(service, port=candidate, capture_dir=capture_dir, request_log=request_log)
            break
        except OSError:
            continue
    if server is None:
        raise OSError(f"PORT_IN_USE {port}-{port + max(1, min(int(port_tries), 20)) - 1}")
    with server:
        url = f"http://{HOST}:{server.server_port}/pair?code={server.pair_code}"
        print(f"Dashboard: {url}", flush=True)  # launchers read this line from a pipe
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Dashboard stopped.")
