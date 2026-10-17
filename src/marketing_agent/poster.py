"""One guarded path from an owned test video to a Chrome comment click."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re
import time
from urllib.parse import urlparse

from .post_events import PostEvent, event

from .dry_run import save_comment
from .guard import check_ownership, normalize_video_id
from .storage import ReservationBlocked
from .profile_emails import EMAIL


@dataclass(frozen=True)
class PostResult:
    status: str
    reason: str
    video_id: str
    attempt_id: str | None = None
    screenshot_path: str | None = None


class ProfilePathError(RuntimeError):
    code = "PROFILE_NOT_FOUND"


class ProfileLocked(RuntimeError):
    code = "PROFILE_LOCKED"


class ChromeLaunchFailed(RuntimeError):
    code = "BROWSER_LAUNCH_FAILED"


class LoginRequired(RuntimeError):
    code = "LOGIN_REQUIRED"


class CommentEditorMissing(RuntimeError):
    code = "COMMENT_INPUT_FAILED"


class AuthorUnverified(RuntimeError):
    code = "COMMENT_INPUT_FAILED"


class CommentInputMismatch(RuntimeError):
    code = "COMMENT_INPUT_FAILED"


class CommentNotConfirmed(RuntimeError):
    code = "COMMENT_VERIFICATION_FAILED"


class YoutubeNavigationFailed(RuntimeError):
    code = "YOUTUBE_NAVIGATION_FAILED"


class CommentPostFailed(RuntimeError):
    code = "COMMENT_POST_FAILED"


class VisibleChromePoster:
    """Dashboard poster: accepts only a server-approved card and comment body.

    The caller owns RSS, draft approval, duplicate, and daily-limit decisions.
    ``before_click`` durably marks the attempt uncertain before the UI click.
    No profile files are opened or inspected by this class.
    """

    VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
    PROFILE_NAME = re.compile(r"(?:Default|Profile [1-9][0-9]*)\Z")

    def __init__(self, user_data_dir: str | Path, profile_directory: str, *,
                 screenshot_dir: str | Path, on_event=None, playwright_factory=None):
        self.user_data_dir = Path(user_data_dir).expanduser()
        self.profile_directory = profile_directory
        self.screenshot_dir = Path(screenshot_dir)
        self.on_event = on_event
        self.playwright_factory = playwright_factory
        self.events: list[PostEvent] = []
        self.last_screenshot_path = ""
        self.keep_window_open = False
        self._held = None

    def held_window_open(self) -> bool:
        """Called on the posting worker that owns the Playwright connection."""
        if self._held is None:
            return False
        manager, context, page = self._held
        try:
            page.evaluate("1")
            return True
        except Exception:
            self._held = None
            try:
                context.close()
            except Exception:
                pass
            manager.__exit__(None, None, None)
            return False

    def _emit(self, stage: str, reason: str = "", screenshot: str = "") -> None:
        item = event(stage, reason, screenshot)
        self.events.append(item)
        if self.on_event is not None:
            try:
                self.on_event(item)
            except Exception:
                # An observer must never change the browser click boundary.
                pass

    def _capture(self, page, video_id: str) -> str:
        if page is None:
            return ""
        try:
            self.screenshot_dir.mkdir(parents=True, exist_ok=True)
            path = self.screenshot_dir / f"{video_id}-{int(time.time() * 1000)}.png"
            page.screenshot(path=str(path), full_page=False, timeout=5000)
            self.last_screenshot_path = str(path)
            return str(path)
        except Exception:
            return ""

    @staticmethod
    def _on_youtube_home(url: str) -> bool:
        location = urlparse(url)
        return (location.scheme == "https" and location.netloc == "www.youtube.com"
                and location.path in {"", "/"})

    def inspect_account_email(self) -> str:
        """Read only the active account header on the fixed YouTube home page."""
        if self.held_window_open():
            raise ProfileLocked("PROFILE_LOCKED")
        if (not self.PROFILE_NAME.fullmatch(self.profile_directory or "")
                or not self.user_data_dir.is_dir()
                or not (self.user_data_dir / self.profile_directory).is_dir()):
            raise ProfilePathError("PROFILE_NOT_FOUND")
        factory = self.playwright_factory
        if factory is None:
            from playwright.sync_api import sync_playwright
            factory = sync_playwright
        try:
            with factory() as playwright:
                with playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.user_data_dir), channel="chrome",
                    headless=False, no_viewport=True, locale="ko-KR",
                    ignore_default_args=["--no-sandbox"],
                    args=[f"--profile-directory={self.profile_directory}"],
                ) as context:
                    page = next((p for p in context.pages if p.url == "about:blank"), None)
                    if page is None:
                        page = context.new_page()
                    page.goto("https://www.youtube.com/",
                              wait_until="domcontentloaded", timeout=30000)
                    if not self._on_youtube_home(page.url):
                        raise ValueError("PROFILE_ACCOUNT_UNKNOWN")
                    # YouTube renders its account controls after DOMContentLoaded.
                    # Wait for either outcome before classifying the session.
                    try:
                        page.wait_for_function("""() => {
                          const avatar = document.querySelector('button#avatar-btn');
                          if (avatar && avatar.getClientRects().length) return true;
                          return [...document.querySelectorAll(
                            "a[href*='accounts.google.com/ServiceLogin'], a[href*='accounts.google.com/v3/signin'], a[href*='youtube.com/signin']"
                          )].some(link => link.getClientRects().length);
                        }""", timeout=12000)
                    except Exception:
                        pass
                    avatar = page.locator("button#avatar-btn")
                    if avatar.count() != 1 or not avatar.first.is_visible():
                        login = page.locator(
                            "a[href*='accounts.google.com/ServiceLogin'], "
                            "a[href*='accounts.google.com/v3/signin'], "
                            "a[href*='youtube.com/signin']"
                        )
                        visible_login = any(login.nth(index).is_visible()
                                            for index in range(min(login.count(), 5)))
                        if visible_login:
                            raise ValueError("PROFILE_SIGNED_OUT")
                        raise ValueError("PROFILE_ACCOUNT_UNKNOWN")
                    avatar.first.click(timeout=15000)
                    active = page.locator("ytd-active-account-header-renderer #email")
                    try:
                        active.first.wait_for(state="visible", timeout=5000)
                    except Exception:
                        pass
                    if active.count() == 1 and active.first.is_visible():
                        email = active.first.inner_text(timeout=5000).strip()
                    else:
                        active_header = page.locator("ytd-active-account-header-renderer")
                        account_name = page.locator("ytd-active-account-header-renderer #account-name")
                        channel_handle = page.locator("ytd-active-account-header-renderer #channel-handle")
                        if (active_header.count() == 1 and active_header.first.is_visible()
                                and account_name.count() == 1 and account_name.first.is_visible()
                                and account_name.first.inner_text(timeout=5000).strip()
                                and channel_handle.count() == 1 and channel_handle.first.is_visible()
                                and channel_handle.first.inner_text(timeout=5000).strip()):
                            email = ""  # A signed-in channel can hide its Google email.
                        else:
                            email = None
                    switch = page.get_by_text("계정 전환", exact=True)
                    if (not email and switch.count() == 1 and switch.first.is_visible()):
                        email = None
                    if email is None:
                        try:
                            switch.first.wait_for(state="visible", timeout=5000)
                        except Exception as exc:
                            raise ValueError("PROFILE_ACCOUNT_UNKNOWN") from exc
                        if switch.count() != 1:
                            raise ValueError("PROFILE_ACCOUNT_UNKNOWN")
                        switch.click(timeout=5000)
                        current = page.locator("ytd-google-account-header-renderer #email")
                        try:
                            current.first.wait_for(state="visible", timeout=5000)
                        except Exception as exc:
                            raise ValueError("PROFILE_ACCOUNT_UNKNOWN") from exc
                        if current.count() != 1 or not current.first.is_visible():
                            raise ValueError("PROFILE_ACCOUNT_UNKNOWN")
                        email = current.first.inner_text(timeout=5000).strip()
                    if not self._on_youtube_home(page.url):
                        raise ValueError("PROFILE_ACCOUNT_UNKNOWN")
                    if email and not EMAIL.fullmatch(email):
                        raise ValueError("PROFILE_ACCOUNT_UNKNOWN")
                    return email
        except (ValueError, ProfileLocked, ProfilePathError):
            raise
        except Exception as exc:
            detail = str(exc).lower()
            if any(word in detail for word in ("singletonlock", "processsingleton", "profile in use", "already running")):
                raise ProfileLocked("PROFILE_LOCKED") from exc
            raise ValueError("PROFILE_EMAIL_CHECK_FAILED") from exc
    @staticmethod
    def _author_href(page) -> str:
        avatar = page.locator("ytd-comment-simplebox-renderer #avatar a").first
        try:
            href = avatar.get_attribute("href", timeout=3000)
        except Exception:
            href = None
        if not href:
            # Current YouTube shows only an image in the composer. Its account
            # menu still exposes the signed-in channel's public link.
            try:
                page.locator("button#avatar-btn").first.click()
                own_channel = page.locator(
                    "ytd-multi-page-menu-renderer a[href^='/channel/'], "
                    "ytd-multi-page-menu-renderer a[href^='/@']"
                ).first
                href = own_channel.get_attribute("href", timeout=5000)
            except Exception as exc:
                raise AuthorUnverified("AUTHOR_UNVERIFIED") from exc
            finally:
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
        if not href or not (href.startswith("/channel/") or href.startswith("/@")):
            raise AuthorUnverified("AUTHOR_UNVERIFIED")
        return href.split("?", 1)[0].rstrip("/")

    @staticmethod
    def _confirmed(page, body: str, author_href: str) -> bool:
        # Require both exact visible text and the author link from the composer.
        for _ in range(20):
            comments = page.locator("ytd-comment-view-model, ytd-comment-renderer")
            for index in range(comments.count()):
                comment = comments.nth(index)
                try:
                    if comment.locator("#content-text").inner_text(timeout=1000).strip() != body.strip():
                        continue
                    href = comment.locator("#author-text").get_attribute("href", timeout=1000)
                    if href and href.split("?", 1)[0].rstrip("/") == author_href:
                        return True
                except Exception:
                    continue
            page.wait_for_timeout(500)
        return False

    def __call__(self, video, body: str, before_click) -> bool:
        video_id = getattr(video, "video_id", None)
        if not isinstance(video_id, str) or not self.VIDEO_ID.fullmatch(video_id):
            raise ValueError("INVALID_VIDEO_ID")
        if not isinstance(body, str) or not body.strip() or not callable(before_click):
            raise ValueError("INVALID_POST_DECISION")
        self.events.clear()
        self.last_screenshot_path = ""
        self._emit("profile_check")
        if self.held_window_open():
            self._emit("failed", "PROFILE_LOCKED")
            raise ProfileLocked("PROFILE_LOCKED")
        if not self.PROFILE_NAME.fullmatch(self.profile_directory or ""):
            self._emit("failed", "PROFILE_NAME_INVALID")
            raise ProfilePathError("PROFILE_NAME_INVALID")
        if not self.user_data_dir.is_dir():
            self._emit("failed", "USER_DATA_DIR_MISSING")
            raise ProfilePathError("USER_DATA_DIR_MISSING")
        if not (self.user_data_dir / self.profile_directory).is_dir():
            self._emit("failed", "PROFILE_DIRECTORY_MISSING")
            raise ProfilePathError("PROFILE_DIRECTORY_MISSING")

        factory = self.playwright_factory
        if factory is None:
            from playwright.sync_api import sync_playwright
            factory = sync_playwright
        page = None
        context = None
        self._emit("opening")
        manager = factory()
        playwright = manager.__enter__()
        held = False
        try:
            try:
                # Chrome owns this directory. Never read profile files or choose
                # another profile if launch fails or the profile is locked.
                try:
                    context = playwright.chromium.launch_persistent_context(
                        user_data_dir=str(self.user_data_dir), channel="chrome",
                        headless=False, no_viewport=True, locale="ko-KR",
                        # Playwright adds this Linux-oriented default even when
                        # launching installed Chrome on Windows. It triggers a
                        # security warning tab and can prevent normal navigation.
                        ignore_default_args=["--no-sandbox"],
                        args=[f"--profile-directory={self.profile_directory}"],
                    )
                except Exception as exc:
                    detail = str(exc).lower()
                    if any(word in detail for word in ("singletonlock", "processsingleton", "profile in use", "already running")):
                        raise ProfileLocked("PROFILE_LOCKED") from exc
                    raise ChromeLaunchFailed("CHROME_LAUNCH_FAILED") from exc
                # Persistent Chrome starts with an about:blank tab. Reuse it so the
                # foreground tab visibly navigates instead of leaving a blank first tab.
                page = next((candidate for candidate in context.pages
                             if candidate.url == "about:blank"), None)
                if page is None:
                    page = context.new_page()
                self._emit("navigating")
                try:
                    page.goto(f"https://www.youtube.com/watch?v={video_id}",
                              wait_until="domcontentloaded", timeout=30000)
                    page.locator("ytd-comments#comments").scroll_into_view_if_needed(timeout=20000)
                except Exception as exc:
                    raise YoutubeNavigationFailed("YOUTUBE_NAVIGATION_FAILED") from exc
                self._emit("checking_login")
                if page.locator("a[href*='ServiceLogin']").count():
                    raise LoginRequired("LOGIN_REQUIRED")
                placeholder = page.locator("ytd-comment-simplebox-renderer #placeholder-area").first
                try:
                    placeholder.wait_for(state="visible", timeout=15000)
                except Exception as exc:
                    raise LoginRequired("LOGIN_REQUIRED") from exc
                author_href = self._author_href(page)
                self._emit("comment_window")
                placeholder.click()
                editor = page.locator("ytd-comment-simplebox-renderer #contenteditable-root").first
                try:
                    editor.wait_for(state="visible", timeout=5000)
                except Exception as exc:
                    raise CommentEditorMissing("COMMENT_EDITOR_MISSING") from exc
                editor.click()
                self._emit("typing")
                for character in body:
                    page.keyboard.type(character)
                if editor.inner_text().strip() != body.strip():
                    raise CommentInputMismatch("COMMENT_INPUT_MISMATCH")
                submit = page.locator("ytd-comment-simplebox-renderer #submit-button").first
                if not submit.is_visible() or not submit.is_enabled():
                    raise CommentEditorMissing("SUBMIT_BUTTON_UNAVAILABLE")
                self._emit("submitting")
                before_click()
                # From here even a thrown click may have reached YouTube.
                try:
                    submit.click()
                except Exception as exc:
                    raise CommentPostFailed("COMMENT_POST_FAILED") from exc
                self._emit("verifying")
                if not self._confirmed(page, body, author_href):
                    raise CommentNotConfirmed("COMMENT_NOT_CONFIRMED")
                self._emit("posted")
                if self.keep_window_open:
                    self._held = (manager, context, page)
                    held = True
                return True
            except Exception as exc:
                self._emit("failed", getattr(exc, "code", type(exc).__name__), self._capture(page, video_id))
                raise
            finally:
                if context is not None and not held:
                    try:
                        context.close()
                    except Exception:
                        pass
        finally:
            if not held:
                manager.__exit__(None, None, None)


def validate_cdp_url(url: str) -> str:
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("CDP_URL_BLOCKED") from exc
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}
            or not port or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment):
        raise ValueError("CDP_URL_BLOCKED")
    return url


class ChromeBrowser:
    """Uses the existing logged-in CDP context; never launches a profile."""

    def __init__(self, cdp_url: str):
        from playwright.sync_api import sync_playwright

        validate_cdp_url(cdp_url)
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.connect_over_cdp(cdp_url)
            if not self._browser.contexts:
                raise RuntimeError("NO_EXISTING_CHROME_CONTEXT")
            self._page = self._browser.contexts[0].new_page()
        except BaseException:
            self._playwright.stop()
            raise

    def open_video(self, video_id: str) -> None:
        self._page.goto(f"https://www.youtube.com/watch?v={video_id}", wait_until="domcontentloaded")
        self._page.locator("ytd-comments#comments").scroll_into_view_if_needed(timeout=15000)

    def author_channel_id(self) -> str:
        box = self._page.locator("ytd-comment-simplebox-renderer")
        box.wait_for(timeout=15000)
        if not box.locator("#placeholder-area").is_visible():
            raise RuntimeError("LOGIN_REQUIRED")
        href = box.locator("#avatar a").get_attribute("href")
        if not href or not href.startswith("/channel/"):
            raise RuntimeError("AUTHOR_CHANNEL_UNVERIFIED")
        return href.split("/")[2].split("?")[0]

    def fill_comment(self, body: str) -> None:
        self._page.locator("ytd-comment-simplebox-renderer #placeholder-area").click()
        editor = self._page.locator("ytd-comment-simplebox-renderer #contenteditable-root")
        editor.fill(body)
        if editor.inner_text().strip() != body.strip():
            raise RuntimeError("COMMENT_INPUT_MISMATCH")

    def click_submit(self) -> None:
        self._page.locator("ytd-comment-simplebox-renderer #submit-button").click()

    def find_comment(self, body: str, author_channel_id: str) -> bool:
        for comment in self._page.locator("ytd-comment-view-model").all():
            if comment.locator("#content-text").inner_text().strip() != body.strip():
                continue
            href = comment.locator("#author-text").get_attribute("href")
            if href and href.split("?")[0].rstrip("/") == f"/channel/{author_channel_id}":
                return True
        return False

    def screenshot(self, path: str) -> str:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._page.screenshot(path=path)
        return path

    def close(self) -> None:
        self._page.close()
        self._playwright.stop()


def _api_owner(video_id: str, lookup) -> str | None:
    """Accept a channel ID or a videos.list(part=snippet) response."""
    result = lookup(video_id)
    if isinstance(result, str):
        return result or None
    if isinstance(result, dict):
        items = result.get("items", [])
        if len(items) == 1 and items[0].get("id") == video_id:
            return items[0].get("snippet", {}).get("channelId")
    return None


def _capture(browser, screenshot_dir: str | Path, video_id: str, reason: str) -> str | None:
    if browser is None:
        return None
    path = str(Path(screenshot_dir) / f"{video_id}-{reason}.png")
    try:
        return browser.screenshot(path)
    except Exception:
        return None


def submit_comment(*, store, config, video: str, body: str, comment_id: str,
                   run_id: str, input_source: str, api_channel_lookup,
                   dry_run_path: str | Path, screenshot_dir: str | Path,
                   dry_run: bool = False, browser_factory=ChromeBrowser,
                   now: datetime | None = None) -> PostResult:
    """The only function allowed to fill or click; every exit is per-video."""
    when = now or datetime.now(timezone.utc)
    try:
        video_id = normalize_video_id(video)
    except ValueError:
        save_comment(dry_run_path, video_id=str(video), body=body, reason="INVALID_VIDEO_ID", run_id=run_id, input_source=input_source)
        return PostResult("BLOCKED", "INVALID_VIDEO_ID", str(video))

    existing = store.attempt(video_id)
    if existing:
        if existing["status"] in {"POST_PENDING", "POST_OUTCOME_UNKNOWN"}:
            return reconcile_pending(store=store, attempt=existing, config=config,
                                     browser_factory=browser_factory, screenshot_dir=screenshot_dir)
        return PostResult(existing["status"], "ALREADY_ATTEMPTED", video_id, existing["attempt_id"])

    decision = check_ownership(video_id, config.allowed_videos, store.ownership(video_id))
    if not decision.allowed or dry_run:
        reason = decision.reason if not decision.allowed else "DRY_RUN"
        save_comment(dry_run_path, video_id=video_id, body=body, reason=reason, run_id=run_id, input_source=input_source)
        return PostResult("BLOCKED" if not decision.allowed else "DRY_RUN_SAVED", reason, video_id)

    browser = None
    attempt_id = None
    clicked = False
    try:
        # Ownership must be established before Chrome can receive any input.
        api_owner = _api_owner(video_id, api_channel_lookup)
        decision = check_ownership(video_id, config.allowed_videos, store.ownership(video_id), api_owner)
        if not api_owner or not decision.allowed:
            raise RuntimeError(decision.reason if not decision.allowed else "OWNERSHIP_BLOCKED")
        validate_cdp_url(config.chrome_debug_url)
        browser = browser_factory(config.chrome_debug_url)
        browser.open_video(video_id)
        author = browser.author_channel_id()
        if not author:
            raise RuntimeError("LOGIN_REQUIRED")
        browser.fill_comment(body)
        attempt_id = store.reserve_post(
            video_id=video_id, comment_id=comment_id, run_id=run_id,
            input_source=input_source, body_hash=sha256(body.encode("utf-8")).hexdigest(),
            author_channel_id=author, target_channel_id=api_owner, when=when,
            daily_limit=config.limits.daily_max_comments,
            cooldown_hours=config.limits.channel_cooldown_hours)
        # The durable reservation exists before this final, click-adjacent check.
        api_owner = _api_owner(video_id, api_channel_lookup)
        decision = check_ownership(video_id, config.allowed_videos, store.ownership(video_id), api_owner)
        if not api_owner or not decision.allowed:
            raise RuntimeError(decision.reason if not decision.allowed else "OWNERSHIP_BLOCKED")
        # A thrown click may still have reached Chrome, so treat it as uncertain.
        clicked = True
        browser.click_submit()
        if not browser.find_comment(body, author):
            raise RuntimeError("COMMENT_NOT_CONFIRMED")
        store.set_post_status(attempt_id, "POSTED", verified_at=datetime.now(timezone.utc))
        return PostResult("POSTED", "CONFIRMED", video_id, attempt_id)
    except Exception as exc:
        reason = exc.reason if isinstance(exc, ReservationBlocked) else str(exc).splitlines()[0][:120]
        reason = reason or type(exc).__name__
        shot = _capture(browser, screenshot_dir, video_id, "failure")
        if attempt_id:
            status = "POST_OUTCOME_UNKNOWN" if clicked else "POST_FAILED"
            try:
                store.set_post_status(attempt_id, status, reason_code=reason, screenshot_path=shot)
            except Exception:
                # A durable POST_PENDING still forbids another click on restart.
                status = "POST_PENDING"
            if reason in {"ALLOWLIST_BLOCKED", "OWNERSHIP_BLOCKED"}:
                save_comment(dry_run_path, video_id=video_id, body=body, reason=reason, run_id=run_id, input_source=input_source)
        else:
            status = "POST_PRECHECK_FAILED"
            try:
                store.record_precheck_failure(video_id, run_id, reason, when, screenshot_path=shot)
            except Exception:
                pass
            save_comment(dry_run_path, video_id=video_id, body=body, reason=reason, run_id=run_id, input_source=input_source)
        return PostResult(status, reason, video_id, attempt_id, shot)
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass


def reconcile_pending(*, store, attempt, config, browser_factory=ChromeBrowser,
                      screenshot_dir: str | Path) -> PostResult:
    """On restart, inspect an uncertain attempt; never fill or click."""
    video_id, attempt_id = attempt["video_id"], attempt["attempt_id"]
    if attempt["status"] == "POST_PENDING":
        store.set_post_status(attempt_id, "POST_OUTCOME_UNKNOWN", reason_code="RESTART_PENDING")
    browser = None
    try:
        validate_cdp_url(config.chrome_debug_url)
        browser = browser_factory(config.chrome_debug_url)
        browser.open_video(video_id)
        comment = store.comment(video_id)
        if (comment and sha256(comment["body"].encode("utf-8")).hexdigest() == attempt["body_hash"]
                and browser.find_comment(comment["body"], attempt["author_channel_id"])):
            store.set_post_status(attempt_id, "POSTED", verified_at=datetime.now(timezone.utc))
            return PostResult("POSTED", "RECONCILED", video_id, attempt_id)
        return PostResult("POST_OUTCOME_UNKNOWN", "NOT_CONFIRMED", video_id, attempt_id)
    except Exception as exc:
        reason = str(exc).splitlines()[0][:120] or type(exc).__name__
        shot = _capture(browser, screenshot_dir, video_id, "reconcile")
        return PostResult("POST_OUTCOME_UNKNOWN", reason, video_id, attempt_id, shot)
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
