"""Local human-approved draft lookup for RSS selections."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime, timezone

from .dashboard_contracts import DraftPreview, VideoCard
from .rss_feed import VIDEO_ID
from .writer import LINK


HASH = re.compile(r"^[0-9a-f]{64}$")
HASHTAG = re.compile(r"(?<!\w)#[\w가-힣]+")
APPROVED_FIELDS = ("video_id", "channel_id", "title", "worry_summary", "comment", "cited_detail", "source_text")
GENERATED_FIELDS = ("worry_summary", "cited_detail", "comment")
FAKE_TESTIMONIAL_END = re.compile(r"(?:써봤|이용해봤|상담받아봤|신청해봤|받아봤)")
# The brand is the proper name of a saju place (PDF p.2), not a common noun such as
# "destined partner". These templates catch the misuse seen in 2026-10-16 drafts.
BRAND_AS_COMMON_NOUN = (r"(?:제|저의|나의|내|우리의|너의|당신의|올|맞는)\s*{brand}",
                        r"{brand}(?:을|를|과|와)\s*(?:만나|만날|만난|찾|기다리|기다릴|놓치)",
                        r"{brand}(?:은|는|이|가)\s*(?:언제|어디|누구|나타)")
BRAND_EXPERIENCE = (r"{brand}(?:에서|에서는|에서도|도 보고)[^.!?。]{{0,15}}?"
                    r"(?:봤|받았|보니|보니까|봤더니|봤는데|다녀|갔었|상담했)",
                    r"{brand}(?:은|는)\s*물론", r"{brand}\s*궁합도",
                    # a past reading result ("운명원에서 제 연애운이 안 좋았던"), not an
                    # intent such as "운명원에서 제 연애운도 한번 봐보고 싶어요"
                    r"{brand}(?:이나 사주)?에서\s*(?:제|내)\s[^.!?。]{{0,20}}?(?:있었|였|았던|었던)")
# Comments that tell readers to rely on themselves *instead of* the brand work
# against the PDF mission ("운명원에서 연애 사주를 보고 싶어지는가").
BRAND_NEGATIVE = (r"{brand}[^.!?。]{{0,16}}(?:의지하기 전|가기 전|보기 전|받아도|맡겨야 하나|처럼 타고난)",)
MAX_DRAFT_BYTES = 1_000_000


def content_hash(draft: dict) -> str:
    """The exact fields a reviewer approves, with deterministic UTF-8 encoding."""
    payload = {key: draft.get(key, "") for key in APPROVED_FIELDS}
    for key in ("brand_name", "brand_description", "min_chars", "max_chars"):
        if key in draft:
            payload[key] = draft[key]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def quality_failure(draft: dict) -> str:
    body = draft.get("comment", "")
    min_chars, max_chars = draft.get("min_chars", 40), draft.get("max_chars", 120)
    if (type(min_chars) is not int or type(max_chars) is not int
            or not 1 <= min_chars <= max_chars <= 1000):
        return "COMMENT_LENGTH_SETTINGS_INVALID"
    if not isinstance(body, str) or not min_chars <= len(body) <= max_chars:
        return "COMMENT_LENGTH"
    if LINK.search(body):
        return "COMMENT_LINK"
    if HASHTAG.search(body):
        return "COMMENT_HASHTAG"
    brand_name = draft.get("brand_name", "운명원")
    if not isinstance(brand_name, str) or not brand_name or brand_name not in body:
        return "BRAND_CONTEXT_MISSING"
    if re.search(r"(?:" + re.escape(brand_name) + r".{0,12}|(?:제가|저는).{0,30}" +
                 re.escape(brand_name) + r".{0,20})" + FAKE_TESTIMONIAL_END.pattern, body):
        return "FABRICATED_TESTIMONIAL"
    escaped = re.escape(brand_name)
    if any(re.search(pattern.format(brand=escaped), body) for pattern in BRAND_EXPERIENCE):
        return "FABRICATED_TESTIMONIAL"
    if any(re.search(pattern.format(brand=escaped), body) for pattern in BRAND_AS_COMMON_NOUN):
        return "BRAND_MISUSED"
    if any(re.search(pattern.format(brand=escaped), body) for pattern in BRAND_NEGATIVE):
        return "BRAND_NEGATIVE_FRAMING"
    summary = draft.get("worry_summary", "")
    detail = draft.get("cited_detail", "")
    if not isinstance(summary, str) or not summary.strip() or not isinstance(detail, str) or not detail.strip():
        return "MISSING_GROUNDING"
    if detail not in body:
        return "UNSUPPORTED_DETAIL"
    source = draft.get("source_text", "")
    if source and (not isinstance(source, str) or detail not in source):
        return "UNSUPPORTED_DETAIL"
    return ""


def _load_record(drafts_dir: Path, video_id: str) -> dict | None:
    if not VIDEO_ID.fullmatch(video_id):
        return None
    if drafts_dir.is_symlink():
        raise ValueError("DRAFT_PATH_BLOCKED")
    path = drafts_dir / "latest.json"
    if path.is_symlink():
        raise ValueError("DRAFT_PATH_BLOCKED")
    if path.exists():
        if not path.is_file() or path.stat().st_size > MAX_DRAFT_BYTES:
            raise ValueError("DRAFT_UNREADABLE")
        data = json.loads(path.read_text(encoding="utf-8"))
        records = data.get("drafts", data) if isinstance(data, dict) else data
        if isinstance(records, dict):
            record = records.get(video_id)
            if isinstance(record, dict):
                return record
        elif isinstance(records, list):
            record = next((item for item in records if isinstance(item, dict) and item.get("video_id") == video_id), None)
            if record is not None:
                return record
        else:
            return None
    # Also accept the documented per-video format, without traversing paths.
    individual = drafts_dir / f"{video_id}.json"
    if individual.is_symlink():
        raise ValueError("DRAFT_PATH_BLOCKED")
    if not individual.is_file():
        return None
    if individual.stat().st_size > MAX_DRAFT_BYTES:
        raise ValueError("DRAFT_UNREADABLE")
    data = json.loads(individual.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _write_record(drafts_dir: Path, video_id: str, record: dict) -> None:
    """Atomically replace one draft without accepting path components from UI."""
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError("INVALID_VIDEO_ID")
    if drafts_dir.is_symlink():
        raise ValueError("DRAFT_PATH_BLOCKED")
    drafts_dir.mkdir(parents=True, exist_ok=True)
    path = drafts_dir / f"{video_id}.json"
    if path.is_symlink():
        raise ValueError("DRAFT_PATH_BLOCKED")
    encoded = json.dumps(record, ensure_ascii=False, indent=2)
    if len(encoded.encode("utf-8")) > MAX_DRAFT_BYTES:
        raise ValueError("DRAFT_TOO_LARGE")
    fd, temporary = tempfile.mkstemp(prefix=f".{video_id}-", suffix=".tmp", dir=drafts_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_generated(video: VideoCard, result: dict, drafts_dir: str | Path, *,
                   source_text: str | None = None, evidence_sources: tuple[str, ...] = (),
                   profile: str = "", brand_name: str = "운명원",
                   brand_description: str = "연애 고민을 사주 관점에서 살펴보는 서비스",
                   min_chars: int = 40, max_chars: int = 120,
                   review_rounds: list | None = None, prompt_version: str = "") -> dict:
    """Store an AI suggestion as unapproved; it can never enable posting itself."""
    if (not isinstance(result, dict) or set(result) != set(GENERATED_FIELDS)
            or any(not isinstance(result.get(key), str) or not result[key].strip() for key in GENERATED_FIELDS)):
        raise ValueError("AI_RESPONSE_SCHEMA_INVALID")
    record = {
        "video_id": video.video_id, "channel_id": video.channel_id, "title": video.title,
        "worry_summary": result["worry_summary"].strip(), "cited_detail": result["cited_detail"].strip(),
        "source_text": source_text if isinstance(source_text, str) and source_text.strip() else video.title,
        "evidence_sources": list(evidence_sources), "comment": result["comment"].strip(),
        "brand_name": brand_name,
        "brand_description": brand_description,
        "min_chars": min_chars, "max_chars": max_chars,
    }
    if profile:
        record["generated_profile"] = profile
        record["generated_at"] = datetime.now(timezone.utc).isoformat()
    if prompt_version:
        record["prompt_version"] = prompt_version
    if review_rounds:
        # Audit trail of the second-pass filter; not part of the approval hash.
        record["review_rounds"] = review_rounds
    _write_record(Path(drafts_dir), video.video_id, record)
    return record


def approve(video: VideoCard, values: dict, drafts_dir: str | Path) -> dict:
    """Validate a human-reviewed draft and bind the approval to this RSS card."""
    if not isinstance(values, dict) or set(values) != {"worry_summary", "cited_detail", "comment", "reviewer"}:
        raise ValueError("DRAFT_APPROVAL_INVALID")
    if any(not isinstance(values[key], str) or len(values[key]) > 1000 for key in values):
        raise ValueError("DRAFT_APPROVAL_INVALID")
    previous = _load_record(Path(drafts_dir), video.video_id) or {}
    source = previous.get("source_text") if (previous.get("video_id") == video.video_id
                                               and previous.get("channel_id") == video.channel_id
                                               and previous.get("title") == video.title) else video.title
    record = {
        "video_id": video.video_id, "channel_id": video.channel_id, "title": video.title,
        "worry_summary": values["worry_summary"].strip(), "cited_detail": values["cited_detail"].strip(),
        "source_text": source if isinstance(source, str) and source.strip() else video.title,
        "evidence_sources": previous.get("evidence_sources", []), "comment": values["comment"].strip(),
        "reviewer": values["reviewer"].strip(), "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    for key in ("brand_name", "brand_description", "min_chars", "max_chars"):
        if key in previous:
            record[key] = previous[key]
    for key in ("generated_profile", "generated_at"):
        if key in previous:
            record[key] = previous[key]
    if not record["reviewer"]:
        raise ValueError("HUMAN_REVIEW_MISSING")
    failure = quality_failure(record)
    if failure:
        raise ValueError(failure)
    record["content_hash"] = content_hash(record)
    record["approval_hash"] = record["content_hash"]
    _write_record(Path(drafts_dir), video.video_id, record)
    return record


def preview(video: VideoCard, drafts_dir: str | Path = "drafts") -> DraftPreview:
    try:
        draft = _load_record(Path(drafts_dir), video.video_id)
    except (OSError, ValueError, TypeError):
        return DraftPreview(video.video_id, reason_code="DRAFT_UNREADABLE")
    if draft is None:
        return DraftPreview(video.video_id, reason_code="DRAFT_MISSING")
    summary = draft.get("worry_summary", "")
    comment = draft.get("comment", draft.get("body", ""))
    summary = summary if isinstance(summary, str) else ""
    comment = comment if isinstance(comment, str) else ""
    cited_detail = draft.get("cited_detail", "")
    cited_detail = cited_detail if isinstance(cited_detail, str) else ""
    sources = draft.get("evidence_sources", ())
    sources = tuple(item for item in sources if isinstance(item, str)) if isinstance(sources, list) else ()
    source_text = draft.get("source_text", "")
    source_text = source_text if isinstance(source_text, str) else ""
    min_chars, max_chars = draft.get("min_chars", 40), draft.get("max_chars", 120)
    min_chars = min_chars if type(min_chars) is int else 40
    max_chars = max_chars if type(max_chars) is int else 120
    def blocked(reason: str) -> DraftPreview:
        return DraftPreview(video.video_id, summary, comment, False, reason, cited_detail, sources, source_text,
                            min_chars, max_chars)

    if draft.get("video_id") != video.video_id:
        return blocked("DRAFT_VIDEO_MISMATCH")
    if draft.get("channel_id") != video.channel_id:
        return blocked("DRAFT_CHANNEL_MISMATCH")
    if draft.get("title") != video.title:
        return blocked("DRAFT_TITLE_MISMATCH")
    if draft.get("comment") != comment:
        return blocked("DRAFT_CONTENT_MISMATCH")
    failure = quality_failure(draft)
    if failure:
        return blocked(failure)
    if "content_hash" not in draft and "approval_hash" not in draft:
        return blocked("APPROVAL_MISSING")
    digest = content_hash(draft)
    recorded = draft.get("content_hash")
    if recorded != digest:
        return blocked("DRAFT_CONTENT_HASH_MISMATCH")
    approval = draft.get("approval_hash")
    if not isinstance(approval, str) or not HASH.fullmatch(approval):
        return blocked("APPROVAL_MISSING")
    if approval != digest:
        return blocked("APPROVAL_HASH_MISMATCH")
    if not all(isinstance(draft.get(key), str) and draft[key].strip() for key in ("reviewer", "reviewed_at")):
        return blocked("HUMAN_REVIEW_MISSING")
    return DraftPreview(video.video_id, summary, comment, True, "", cited_detail, sources, source_text,
                        min_chars, max_chars)
