from datetime import datetime, timezone

import pytest

from marketing_agent.guard import check_ownership, normalize_video_id


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
