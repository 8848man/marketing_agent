"""Second-pass filter for AI drafts (IMP-15).

After the first generation the server checks the draft with deterministic rules
(the same quality rules used at approval, plus repetition and generic-praise
checks across the other drafts). Any problem is sent back to the same AI as
concrete Korean feedback for a rewrite, at most ``MAX_REVISIONS`` times. The
result is still saved UNAPPROVED; a person approves before anything is posted.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from .drafts import MAX_DRAFT_BYTES, quality_failure

MAX_REVISIONS = 2
SIMILARITY_LIMIT = 0.4
GENERIC_PRAISE = re.compile(r"영상\s*잘\s*봤|많은\s*것을\s*배우|많이\s*배웠|많이\s*배워|도움이\s*(?:됐|되|많이)|좋은\s*영상\s*감사|유익한\s*영상")
SENTENCE = re.compile(r"[^.!?。~]+[.!?。~]*")


def brand_sentence(comment: str, brand: str) -> str:
    """The sentence that carries the brand; repeated across videos it reads like an ad."""
    for sentence in SENTENCE.findall(comment):
        if brand in sentence:
            return sentence.strip()
    return ""


def _bigrams(text: str) -> set[str]:
    compact = re.sub(r"[\s\W_]+", "", text)
    return {compact[i:i + 2] for i in range(len(compact) - 1)}


def similarity(a: str, b: str) -> float:
    left, right = _bigrams(a), _bigrams(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def other_comments(drafts_dir: Path, video_id: str, limit: int = 60) -> list[str]:
    """Comments of the other saved drafts, newest files first."""
    comments: list[str] = []
    try:
        files = sorted((p for p in Path(drafts_dir).glob("*.json")
                        if p.stem != video_id and p.name != "latest.json" and not p.is_symlink()),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return comments
    for path in files[:limit]:
        try:
            if path.stat().st_size > MAX_DRAFT_BYTES:
                continue
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        comment = record.get("comment") if isinstance(record, dict) else None
        if isinstance(comment, str) and comment.strip():
            comments.append(comment)
    return comments


def review_problems(candidate: dict, others: list[str]) -> list[str]:
    """Concrete, fixable feedback in Korean; empty when the draft passes."""
    problems: list[str] = []
    comment = candidate.get("comment", "")
    lo, hi = candidate.get("min_chars", 40), candidate.get("max_chars", 120)
    target_hi = max(lo, hi - 15)
    brand = candidate.get("brand_name", "운명원")
    failure = quality_failure(candidate)
    if failure == "COMMENT_LENGTH":
        problems.append(f"LENGTH: 댓글이 {len(comment)}자입니다. 반드시 {lo}~{hi}자, 가능하면 {target_hi}자 이하로 줄이세요. "
                        "문장 하나를 빼거나 수식어를 줄이세요.")
    elif failure:
        problems.append(f"RULE {failure}: 금지 규칙에 걸렸습니다. 이 항목을 고치세요.")
    cited = candidate.get("cited_detail", "")
    if isinstance(cited, str) and len(cited) > 30:
        problems.append(f"QUOTE_TOO_LONG: 인용이 {len(cited)}자입니다. 근거에서 30자 이내의 짧은 표현만 그대로 인용하세요.")
    if isinstance(cited, str) and len(cited.strip()) >= 6:
        shared = next((other for other in others if cited.strip() in other), "")
        if shared:
            problems.append(f"SAME_QUOTE: 다른 영상 초안도 같은 표현('{cited.strip()}')을 인용했습니다. "
                            "이 영상에서만 나오는 다른 장면이나 말을 골라 인용하세요.")
    praise = GENERIC_PRAISE.search(comment)
    if praise:
        problems.append(f"GENERIC: '{praise.group(0)}'처럼 어느 영상에나 붙는 칭찬은 빼세요.")
    mine = brand_sentence(comment, brand)
    if mine:
        closest = max(((similarity(mine, brand_sentence(other, brand)), other) for other in others),
                      default=(0.0, ""))
        if closest[0] >= SIMILARITY_LIMIT:
            problems.append("REPEATED_CLOSING: 운명원 문장이 다른 영상 초안과 거의 같습니다"
                            f"(다른 초안: '{brand_sentence(closest[1], brand)}'). 이 영상의 고민에 맞춰 "
                            "재회운·궁합·결혼운·인연 시기·연애운 중 알맞은 말과 다른 문장 구조로 새로 쓰세요.")
    return problems
