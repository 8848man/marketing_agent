from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from marketing_agent.poster import VisibleChromePoster, ProfileLocked, ProfilePathError, LoginRequired, CommentNotConfirmed, CommentPostFailed, YoutubeNavigationFailed
from marketing_agent.dashboard_contracts import VideoCard


VIDEO = "abcDEF123_-"
OWNER = "UC-owned"
BODY = "A useful comment on my own test video"


class _Locator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector
        self.first = self

    def scroll_into_view_if_needed(self, **_):
        if self.selector == "ytd-comments":
            raise RuntimeError("strict mode violation: two comments containers")

    def count(self):
        return 0

    def wait_for(self, **_):
        if self.page.login and "placeholder" in self.selector:
            raise TimeoutError("missing composer")

    def click(self):
        if "submit-button" in self.selector:
            self.page.calls.append("click")
            if self.page.click_fails:
                raise TimeoutError("click ambiguous")

    def inner_text(self):
        return "".join(self.page.characters)

    def get_attribute(self, name, **_):
        return "/channel/UC-author"

    def is_visible(self):
        return True

    def is_enabled(self):
        return True


class _Page:
    def __init__(self):
        self.url = "about:blank"
        self.calls = []
        self.characters = []
        self.login = False
        self.click_fails = False
        self.closed = False
        self.keyboard = self

    def goto(self, url, **_):
        self.calls.append(url)

    def evaluate(self, _):
        if self.closed:
            raise RuntimeError("closed")
        return 1

    def locator(self, selector):
        return _Locator(self, selector)

    def type(self, character):
        self.characters.append(character)

    def screenshot(self, path, **_):
        self.calls.append("capture")

    def wait_for_timeout(self, _):
        pass


class _Context:
    def __init__(self, page):
        self.page = page
        self.pages = [page]
        self.new_page_calls = 0
        self.close_calls = 0

    def new_page(self):
        self.new_page_calls += 1
        return self.page

    def close(self):
        self.close_calls += 1
        self.page.closed = True


class _Chromium:
    def __init__(self, page):
        self.page = page
        self.context = _Context(page)
        self.launches = []
        self.error = None

    def launch_persistent_context(self, **kwargs):
        self.launches.append(kwargs)
        if self.error:
            raise RuntimeError(self.error)
        return self.context


class _Playwright:
    def __init__(self, chromium):
        self.chromium = chromium

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


def _visible(tmp_path):
    profile = tmp_path / "Chrome User Data"
    profile.mkdir()
    (profile / "Profile 1").mkdir()
    page = _Page()
    chrome = _Chromium(page)
    poster = VisibleChromePoster(profile, "Profile 1", screenshot_dir=tmp_path / "shots",
                                 playwright_factory=lambda: _Playwright(chrome))
    card = VideoCard(VIDEO, OWNER, "test", "title", "now", "")
    return poster, card, page, chrome


def test_visible_poster_types_each_character_then_clicks_and_confirms(tmp_path, monkeypatch):
    poster, card, page, chrome = _visible(tmp_path)
    monkeypatch.setattr(VisibleChromePoster, "_confirmed", lambda *_: True)
    markers = []
    assert poster(card, BODY, lambda: markers.append(len(page.characters))) is True
    assert page.characters == list(BODY)
    assert markers == [len(BODY)]
    assert page.calls == [f"https://www.youtube.com/watch?v={VIDEO}", "click"]
    assert chrome.launches[0]["headless"] is False
    assert chrome.launches[0]["ignore_default_args"] == ["--no-sandbox"]
    assert chrome.launches[0]["args"] == ["--profile-directory=Profile 1"]
    assert chrome.context.new_page_calls == 0
    assert [item.stage for item in poster.events] == ["profile_check", "opening", "navigating", "checking_login", "comment_window", "typing", "submitting", "verifying", "posted"]
    assert chrome.context.close_calls == 1


def test_visible_poster_keeps_confirmed_window_until_user_closes(tmp_path, monkeypatch):
    poster, card, page, chrome = _visible(tmp_path)
    monkeypatch.setattr(VisibleChromePoster, "_confirmed", lambda *_: True)
    poster.keep_window_open = True
    assert poster(card, BODY, lambda: None) is True
    assert chrome.context.close_calls == 0
    assert poster.held_window_open() is True
    with pytest.raises(ProfileLocked):
        poster(card, BODY, lambda: None)
    assert len(chrome.launches) == 1
    page.closed = True
    assert poster.held_window_open() is False
    assert chrome.context.close_calls == 1


def test_visible_poster_closes_failed_window_even_with_keep_option(tmp_path):
    poster, card, page, chrome = _visible(tmp_path)
    poster.keep_window_open = True
    page.login = True
    with pytest.raises(LoginRequired):
        poster(card, BODY, lambda: None)
    assert chrome.context.close_calls == 1


def test_visible_poster_click_exception_is_uncertain_to_caller(tmp_path):
    poster, card, page, _ = _visible(tmp_path)
    page.click_fails = True
    marker = []
    with pytest.raises(CommentPostFailed):
        poster(card, BODY, lambda: marker.append(True))
    assert marker == [True]
    assert poster.events[-1].stage == "failed"
    assert poster.events[-1].reason_code == "COMMENT_POST_FAILED"
    assert poster.events[-1].screenshot_path
    assert "capture" in page.calls


def test_visible_poster_missing_own_comment_is_uncertain_after_marker(tmp_path, monkeypatch):
    poster, card, page, _ = _visible(tmp_path)
    monkeypatch.setattr(VisibleChromePoster, "_confirmed", lambda *_: False)
    marker = []
    with pytest.raises(CommentNotConfirmed):
        poster(card, BODY, lambda: marker.append(True))
    assert marker == [True]
    assert page.calls[-2:] == ["click", "capture"]


def test_visible_poster_profile_failures_never_click_or_switch(tmp_path):
    poster, card, page, chrome = _visible(tmp_path)
    poster.user_data_dir = tmp_path / "missing"
    with pytest.raises(ProfilePathError):
        poster(card, BODY, lambda: None)
    assert chrome.launches == []
    poster.user_data_dir = tmp_path / "Chrome User Data"
    chrome.error = "ProcessSingleton: profile in use"
    with pytest.raises(ProfileLocked):
        poster(card, BODY, lambda: None)
    assert len(chrome.launches) == 1 and "click" not in page.calls


def test_visible_poster_login_failure_before_marker(tmp_path):
    poster, card, page, _ = _visible(tmp_path)
    page.login = True
    marker = []
    with pytest.raises(LoginRequired):
        poster(card, BODY, lambda: marker.append(True))
    assert marker == [] and "click" not in page.calls


def test_visible_poster_navigation_failure_has_specific_code(tmp_path):
    poster, card, page, _ = _visible(tmp_path)
    def fail_goto(*args, **kwargs):
        raise RuntimeError("navigation failed")
    page.goto = fail_goto
    marker = []
    with pytest.raises(YoutubeNavigationFailed):
        poster(card, BODY, lambda: marker.append(True))
    assert marker == []
    assert poster.events[-1].reason_code == "YOUTUBE_NAVIGATION_FAILED"
    assert poster.events[-1].screenshot_path


def test_visible_poster_uses_account_menu_when_composer_has_no_author_link():
    page = MagicMock()
    composer_link = MagicMock()
    composer_link.first.get_attribute.return_value = None
    account_button = MagicMock()
    menu_link = MagicMock()
    menu_link.first.get_attribute.return_value = "/@signed-in-channel"
    def locate(selector):
        if selector == "ytd-comment-simplebox-renderer #avatar a":
            return composer_link
        if selector == "button#avatar-btn":
            return account_button
        if selector.startswith("ytd-multi-page-menu-renderer a["):
            return menu_link
        raise AssertionError(selector)
    page.locator.side_effect = locate
    assert VisibleChromePoster._author_href(page) == "/@signed-in-channel"
    account_button.first.click.assert_called_once()
    page.keyboard.press.assert_called_once_with("Escape")


PROBE = "akn-AvCeHBI"
PROBE_URL = "https://www.youtube.com/watch?v=akn-AvCeHBI&hl=ko"
LOGIN_SELECTOR = ("a[href*='accounts.google.com/ServiceLogin'], "
                  "a[href*='accounts.google.com/v3/signin'], a[href*='youtube.com/signin']")


def _inspection(tmp_path, *, avatar_visible, login_visible, redirect=None):
    profile = tmp_path / "chrome-profile-youtube1"
    (profile / "Default").mkdir(parents=True)
    page = MagicMock()
    page.url = "about:blank"
    page.goto.side_effect = lambda url, **_: setattr(page, "url", redirect or url)
    avatar = MagicMock()
    avatar.count.return_value = 1 if avatar_visible else 0
    avatar.first.is_visible.return_value = avatar_visible
    login = MagicMock()
    login.count.return_value = 1 if login_visible else 0
    login.nth.return_value.is_visible.return_value = login_visible
    page.locator.side_effect = lambda selector: {"button#avatar-btn": avatar,
                                                 LOGIN_SELECTOR: login}[selector]
    context = MagicMock()
    context.pages = [page]

    @contextmanager
    def opened_context(**_kwargs):
        yield context
    chromium = MagicMock()
    chromium.launch_persistent_context.side_effect = opened_context
    playwright = MagicMock()
    playwright.chromium = chromium

    @contextmanager
    def factory():
        yield playwright
    poster = VisibleChromePoster(profile, "Default", screenshot_dir=tmp_path / "shots",
                                 playwright_factory=factory)
    return poster, page, avatar


def test_account_check_uses_allowed_watch_page_and_never_clicks(tmp_path):
    poster, page, avatar = _inspection(tmp_path, avatar_visible=True, login_visible=False)
    assert poster.inspect_account_email(PROBE) == ""
    page.goto.assert_called_once_with(PROBE_URL, wait_until="domcontentloaded", timeout=30000)
    avatar.first.click.assert_not_called()
    assert not page.get_by_text.called and not page.screenshot.called


def test_account_check_distinguishes_visible_signed_out_page(tmp_path):
    poster, page, _ = _inspection(tmp_path, avatar_visible=False, login_visible=True)
    with pytest.raises(ValueError, match="PROFILE_SIGNED_OUT"):
        poster.inspect_account_email(PROBE)


def test_account_check_unknown_when_neither_control_visible(tmp_path):
    poster, page, _ = _inspection(tmp_path, avatar_visible=False, login_visible=False)
    with pytest.raises(ValueError, match="PROFILE_ACCOUNT_UNKNOWN"):
        poster.inspect_account_email(PROBE)


def test_account_check_rejects_redirect_and_bad_video_id(tmp_path):
    poster, page, _ = _inspection(tmp_path, avatar_visible=True, login_visible=False,
                                  redirect="https://www.youtube.com/")
    with pytest.raises(ValueError, match="PROFILE_ACCOUNT_UNKNOWN"):
        poster.inspect_account_email(PROBE)
    page.locator.assert_not_called()
    with pytest.raises(ValueError, match="INVALID_VIDEO_ID"):
        poster.inspect_account_email("https://myaccount.google.com/")
