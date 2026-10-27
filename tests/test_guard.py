from datetime import datetime, timezone

import pytest

from marketing_agent.dashboard_contracts import VideoCard
from marketing_agent.guard import check_ownership, check_rss_membership, normalize_video_id
from marketing_agent.rss_feed import CHANNELS


VIDEO = "abcDEF123_-"
OWNER = "UC-owned"
PROOF = {"video_id": VIDEO, "owner_channel_id": OWNER,
         "verified_at": datetime.now(timezone.utc).isoformat(),
         "evidence_path": "studio/proof.png"}


@pytest.mark.parametrize("value", [VIDEO, f"https://www.youtube.com/watch?v={VIDEO}",
                                   f"https://youtu.be/{VIDEO}",
                                   f"https://www.youtube.com/shorts/{VIDEO}"])
def test_normalizes_supported_video_forms(value):
    assert normalize_video_id(value) == VIDEO


@pytest.mark.parametrize("value", ["https://evil.test/watch?v=abcDEF123_-",
                                   "http://youtu.be/abcDEF123_-", "too-short",
                                   "https://youtube.com/watch?v=abcDEF123_-&v=another-id"])
def test_rejects_invalid_video_forms(value):
    with pytest.raises(ValueError):
        normalize_video_id(value)


def test_guard_requires_allowlist_studio_proof_and_matching_api_owner():
    assert check_ownership(VIDEO, [], PROOF).reason == "ALLOWLIST_BLOCKED"
    assert check_ownership(VIDEO, [VIDEO], None).reason == "OWNERSHIP_BLOCKED"
    assert check_ownership(VIDEO, [VIDEO], {**PROOF, "evidence_path": ""}).reason == "OWNERSHIP_BLOCKED"
    assert check_ownership(VIDEO, [VIDEO], PROOF, "other").reason == "OWNERSHIP_BLOCKED"
    assert check_ownership(VIDEO, [f"https://youtu.be/{VIDEO}"], PROOF, OWNER).allowed


def _card(channel):
    return VideoCard(VIDEO, channel, "채널", "제목", "2026-10-15", "")


def test_rss_membership_allows_injected_channel():
    custom = "UCzzzzzzzzzzzzzzzzzzzzzz"
    assert custom not in CHANNELS
    decision = check_rss_membership(VIDEO, custom, recheck=lambda *_: _card(custom),
                                    allowed_channels={custom: "설정"})
    assert (decision.allowed, decision.reason) == (True, "POST_ALLOWED")


def test_rss_membership_rejects_channel_outside_injected():
    fixed = next(iter(CHANNELS))
    decision = check_rss_membership(VIDEO, fixed, recheck=lambda *_: _card(fixed),
                                    allowed_channels={"UCzzzzzzzzzzzzzzzzzzzzzz": "설정"})
    assert (decision.allowed, decision.reason) == (False, "CHANNEL_NOT_ALLOWED")


def test_rss_membership_defaults_to_fixed_channels():
    fixed = next(iter(CHANNELS))
    assert check_rss_membership(VIDEO, fixed, recheck=lambda *_: _card(fixed)).allowed
    assert check_rss_membership(VIDEO, "UCzzzzzzzzzzzzzzzzzzzzzz").reason == "CHANNEL_NOT_ALLOWED"
