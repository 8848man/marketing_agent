"""Visible app-profile Chrome automation for the dashboard comment flow.

The legacy poster that attached to a user-launched Chrome over CDP was removed on
2026-10-18 (IMP-2026-10-18 / SEC-02, ARCH-02); the dashboard button is the only
posting entry point."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import time
from urllib.parse import urlparse

from .post_events import PostEvent, event
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
