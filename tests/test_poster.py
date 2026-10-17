from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from unittest.mock import MagicMock

import pytest

from marketing_agent.config import AgentConfig
from marketing_agent.poster import submit_comment, validate_cdp_url
from marketing_agent.poster import VisibleChromePoster, ProfileLocked, ProfilePathError, LoginRequired, CommentNotConfirmed, CommentPostFailed, YoutubeNavigationFailed
from marketing_agent.dashboard_contracts import VideoCard
from marketing_agent.storage import Store


VIDEO = "abcDEF123_-"
OWNER = "UC-owned"
BODY = "A useful comment on my own test video"
NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)


class FakeBrowser:
    def __init__(self, url, *, confirm=True, fail=None):
        self.url = url
        self.confirm = confirm
        self.fail = fail
        self.inputs = self.clicks = self.reads = 0

    def open_video(self, video_id):
        self.reads += 1
        if self.fail == "open":
            raise RuntimeError("PAGE_MISSING")

    def author_channel_id(self):
        if self.fail == "login":
            raise RuntimeError("LOGIN_REQUIRED")
        return OWNER

    def fill_comment(self, body):
        self.inputs += 1

    def click_submit(self):
        self.clicks += 1
        if self.fail == "click":
            raise RuntimeError("CLICK_TIMEOUT")

    def find_comment(self, body, author):
        self.reads += 1
        return self.confirm and body == BODY and author == OWNER

    def screenshot(self, path):
        return path

    def close(self):
        pass


@dataclass
class Harness:
    store: Store
    browser: FakeBrowser
    folder: object
    allowed: tuple[str, ...] = (VIDEO,)
    lookup: object = None

    def post(self, *, dry_run=False, video=VIDEO, factory=None):
        config = AgentConfig(topic="test", keywords=("test",), allowed_videos=self.allowed)
        return submit_comment(store=self.store, config=config, video=video, body=BODY,
                              comment_id=self.store.comment(VIDEO)["comment_id"], run_id="r1",
                              input_source="fixture", api_channel_lookup=self.lookup or (lambda _: OWNER),
                              dry_run_path=self.folder / "dry.jsonl", screenshot_dir=self.folder / "shots",
                              dry_run=dry_run, browser_factory=factory or (lambda _: self.browser), now=NOW)


@pytest.fixture
def h(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    store.save_video(VIDEO, OWNER, NOW)
    store.save_comment(VIDEO, BODY, NOW)
    store.register_owned_video(VIDEO, OWNER, NOW, "studio/proof.png")
    yield Harness(store, FakeBrowser("local"), tmp_path)
    store.close()


@pytest.mark.parametrize("case", ["not_allowed", "missing_proof", "mismatch", "dry_run"])
def test_blocked_and_dry_run_never_type_or_click_and_save_jsonl(h, case):
    if case == "not_allowed":
        h.allowed = ()
    elif case == "missing_proof":
        h.store.db.execute("DELETE FROM owned_test_videos")
    elif case == "mismatch":
        h.store.register_owned_video(VIDEO, "wrong", NOW, "studio/proof.png")
        h.lookup = lambda _: OWNER
    result = h.post(dry_run=case == "dry_run")
    assert h.browser.inputs == h.browser.clicks == 0
    assert len((h.folder / "dry.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    if case == "mismatch":
        assert result.reason == "OWNERSHIP_BLOCKED"
    assert h.store.attempt(VIDEO) is None


def test_click_boundary_rechecks_api_and_allowlist(h):
    calls = 0

    def lookup(_):
        nonlocal calls
        calls += 1
        return OWNER if calls == 1 else "other"

    h.lookup = lookup
    result = h.post()
    assert calls == 2 and h.browser.inputs == 1 and h.browser.clicks == 0
    assert result.reason == "OWNERSHIP_BLOCKED"


@pytest.mark.parametrize("url", ["http://evil.test:9222", "https://localhost:9222",
                                   "http://localhost.evil.test:9222", "http://localhost:9222/path"])
def test_cdp_url_restricted(url):
    with pytest.raises(ValueError):
        validate_cdp_url(url)


def test_reservation_failure_never_clicks(h, monkeypatch):
    def fail(**kwargs):
        raise OSError("DISK_FULL")
    monkeypatch.setattr(h.store, "reserve_post", fail)
    result = h.post()
    assert result.status == "POST_PRECHECK_FAILED"
    assert h.browser.clicks == 0


def test_unknown_and_failed_are_never_reposted(h):
    h.browser.confirm = False
    first = h.post()
    assert first.status == "POST_OUTCOME_UNKNOWN"
    assert h.post().status == "POST_OUTCOME_UNKNOWN"
    assert h.browser.clicks == 1


def test_click_exception_is_unknown_and_never_reposted(h):
    h.browser.fail = "click"
    assert h.post().status == "POST_OUTCOME_UNKNOWN"
    h.browser.fail = None
    assert h.post().status == "POSTED"
    assert h.browser.clicks == 1


def test_post_failed_cannot_repost(h):
    from hashlib import sha256
    cid = h.store.comment(VIDEO)["comment_id"]
    aid = h.store.reserve_post(video_id=VIDEO, comment_id=cid, run_id="r1", input_source="fixture",
                               body_hash=sha256(BODY.encode()).hexdigest(), author_channel_id=OWNER,
                               target_channel_id=OWNER, when=NOW)
    h.store.set_post_status(aid, "POST_FAILED", reason_code="UI_ERROR")
    assert h.post().status == "POST_FAILED"
    assert h.browser.inputs == h.browser.clicks == 0


def test_restart_pending_only_reads_and_matches_body_and_author(h):
    from hashlib import sha256
    cid = h.store.comment(VIDEO)["comment_id"]
    h.store.reserve_post(video_id=VIDEO, comment_id=cid, run_id="r1", input_source="fixture",
                         body_hash=sha256(BODY.encode()).hexdigest(), author_channel_id=OWNER,
                         target_channel_id=OWNER, when=NOW)
    result = h.post()
    assert result.status == "POSTED"
    assert h.browser.inputs == h.browser.clicks == 0
    assert h.store.attempt(VIDEO)["status"] == "POSTED"


def test_restart_pending_without_matching_comment_stays_unknown(h):
    from hashlib import sha256
    cid = h.store.comment(VIDEO)["comment_id"]
    h.store.reserve_post(video_id=VIDEO, comment_id=cid, run_id="r1", input_source="fixture",
                         body_hash=sha256(BODY.encode()).hexdigest(), author_channel_id=OWNER,
                         target_channel_id=OWNER, when=NOW)
    h.browser.confirm = False
    assert h.post().status == "POST_OUTCOME_UNKNOWN"
    assert h.store.attempt(VIDEO)["status"] == "POST_OUTCOME_UNKNOWN"
    assert h.browser.inputs == h.browser.clicks == 0


def test_precheck_browser_failure_records_reason_and_next_video_can_continue(h):
    h.browser.fail = "login"
    result = h.post()
    assert result.status == "POST_PRECHECK_FAILED"
    assert result.screenshot_path
    assert h.store.db.execute("SELECT reason_code FROM post_precheck_failures").fetchone()[0] == "LOGIN_REQUIRED"
    h.browser.fail = None
    assert h.post().status == "POSTED"


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


def test_account_email_inspection_reads_only_active_header_on_youtube_home(tmp_path):
    from contextlib import contextmanager
    profile = tmp_path / "chrome-profile-youtube1"
    (profile / "Default").mkdir(parents=True)
    page = MagicMock()
    page.url = "about:blank"
    page.goto.side_effect = lambda url, **_: setattr(page, "url", url)
    header = MagicMock()
    header.count.return_value = 1
    header.first.is_visible.return_value = True
    header.first.inner_text.return_value = "signed@example.com"
    active = MagicMock()
    active.count.return_value = 0
    active_header = MagicMock(); active_header.count.return_value = 0
    account_name = MagicMock(); account_name.count.return_value = 0
    channel_handle = MagicMock(); channel_handle.count.return_value = 0
    avatar = MagicMock()
    avatar.count.return_value = 1
    avatar.first.is_visible.return_value = True
    # Account controls arrive after the initial document response.
    avatar.count.side_effect = lambda: 1 if page.wait_for_function.called else 0
    login = MagicMock()
    login.count.return_value = 0
    switch = MagicMock()
    switch.count.return_value = 1
    page.get_by_text.return_value = switch
    page.locator.side_effect = lambda selector: {
        "button#avatar-btn": avatar,
        "ytd-active-account-header-renderer #email": active,
        "ytd-active-account-header-renderer": active_header,
        "ytd-active-account-header-renderer #account-name": account_name,
        "ytd-active-account-header-renderer #channel-handle": channel_handle,
        "ytd-google-account-header-renderer #email": header,
        "a[href*='accounts.google.com/ServiceLogin'], a[href*='accounts.google.com/v3/signin'], a[href*='youtube.com/signin']": login,
    }[selector]
    context = MagicMock()
    context.pages = [page]
    @contextmanager
    def opened_context(**kwargs):
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
    assert poster.inspect_account_email() == "signed@example.com"
    page.wait_for_function.assert_called_once()
    switch.click.assert_called_once()
    page.goto.assert_called_once_with("https://www.youtube.com/",
                                      wait_until="domcontentloaded", timeout=30000)
    assert not page.screenshot.called
    active_header.count.return_value = 1
    active_header.first.is_visible.return_value = True
    account_name.count.return_value = 1
    account_name.first.is_visible.return_value = True
    account_name.first.inner_text.return_value = "channel name"
    channel_handle.count.return_value = 1
    channel_handle.first.is_visible.return_value = True
    channel_handle.first.inner_text.return_value = "@channel"
    switch.count.return_value = 0
    page.url = "about:blank"
    assert poster.inspect_account_email() == ""
    active_header.count.return_value = 0
    switch.count.return_value = 1
    header.first.inner_text.return_value = "not an email"
    page.url = "about:blank"
    with pytest.raises(ValueError, match="PROFILE_ACCOUNT_UNKNOWN"):
        poster.inspect_account_email()


def test_account_email_inspection_distinguishes_visible_signed_out_page(tmp_path):
    from contextlib import contextmanager
    profile = tmp_path / "chrome-profile-youtube1"
    (profile / "Default").mkdir(parents=True)
    page = MagicMock()
    page.url = "about:blank"
    page.goto.side_effect = lambda url, **_: setattr(page, "url", url)
    avatar = MagicMock(); avatar.count.return_value = 0
    login = MagicMock(); login.count.return_value = 1; login.nth.return_value.is_visible.return_value = True
    page.locator.side_effect = lambda selector: avatar if selector == "button#avatar-btn" else login
    context = MagicMock(); context.pages = [page]
    @contextmanager
    def opened_context(**_kwargs): yield context
    chromium = MagicMock(); chromium.launch_persistent_context.side_effect = opened_context
    playwright = MagicMock(); playwright.chromium = chromium
    @contextmanager
    def factory(): yield playwright
    poster = VisibleChromePoster(profile, "Default", screenshot_dir=tmp_path / "shots",
                                 playwright_factory=factory)
    with pytest.raises(ValueError, match="PROFILE_SIGNED_OUT"):
        poster.inspect_account_email()


def test_account_inspection_rejects_redirect_before_reading_account_ui(tmp_path):
    profile = tmp_path / "chrome-profile-youtube1"
    (profile / "Default").mkdir(parents=True)
    page = MagicMock()
    page.url = "about:blank"
    page.goto.side_effect = lambda *_args, **_kwargs: setattr(page, "url", "https://outside.example/")
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
    with pytest.raises(ValueError, match="PROFILE_ACCOUNT_UNKNOWN"):
        poster.inspect_account_email()
    page.goto.assert_called_once_with("https://www.youtube.com/",
                                      wait_until="domcontentloaded", timeout=30000)
    page.locator.assert_not_called()
