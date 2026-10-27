"""Evidence grounded draft generation and bounded quality retries."""

from dataclasses import dataclass
import json
import re
from typing import Iterable

from .ai_client import AIClient
from .classifier import Classification, Video
from .drafts import LINK


def normalize_space(value: str) -> str:
    return " ".join(value.split())


@dataclass(frozen=True)
class WriteResult:
    state: str
    body: str = ""
    worry_summary: str = ""
    cited_detail: str = ""
    keyword: str = ""
    reason: str = ""
    attempts: int = 0


class Writer:
    def __init__(self, ai: AIClient, *, store=None, min_chars: int = 40, max_chars: int = 120, max_rewrites: int = 3):
        if min_chars < 1 or max_chars < min_chars or not 0 <= max_rewrites <= 3:
            raise ValueError("invalid comment limits")
        self.ai = ai
        self.store = store
        self.min_chars, self.max_chars, self.max_rewrites = min_chars, max_chars, max_rewrites

    def write(self, video: Video, classification: Classification, *, existing_comments: Iterable[str] = (),
              recent_comments: Iterable[str] = ()) -> WriteResult:
        if not classification.on_topic:
            return WriteResult("SKIPPED_OFF_TOPIC", reason=classification.reason)
        source = classification.source_text or "\n".join((video.title, video.description))
        if not normalize_space(source):
            return WriteResult("WRITE_FAILED", reason="NO_VIDEO_EVIDENCE")
        stored = ()
        if self.store is not None:
            stored = tuple(row[0] for row in self.store.db.execute(
                "SELECT body FROM comments WHERE state IN ('COMMENT_WRITTEN','DRY_RUN_SAVED')"))
        existing = (*tuple(existing_comments), *tuple(recent_comments), *stored)
        duplicates = {normalize_space(c) for c in existing}
        feedback = ""
        for attempt in range(1, self.max_rewrites + 2):
            prompt = json.dumps({"video_text": source, "existing_comments": list(existing),
                                 "feedback": feedback, "min_chars": self.min_chars, "max_chars": self.max_chars},
                                ensure_ascii=False)
            try:
                draft = self.ai.complete_json(
                    'Write a Korean relationship advice comment. Return JSON with "worry_summary", "cited_detail", '
                    '"keyword", "body". Quote a concrete detail and keyword exactly from video_text. '
                    "Use the concern, video evidence and existing comments. Do not invent details or add links.", prompt)
                body = str(draft.get("body", "")).strip()
                summary = str(draft.get("worry_summary", "")).strip()
                detail = str(draft.get("cited_detail", "")).strip()
                keyword = str(draft.get("keyword", "")).strip()
                feedback = self._rule_failure(body, summary, detail, keyword, source, duplicates)
                if feedback:
                    continue
                fit = self.ai.complete_json(
                    'Check whether the comment fits the video and its stated concern. Return JSON '
                    '{"fits": boolean, "reason": string}. Reject invented evidence, generic advice and irrelevant comments.',
                    json.dumps({"video_text": source, "worry_summary": summary, "cited_detail": detail,
                                "keyword": keyword, "body": body}, ensure_ascii=False))
                if fit.get("fits") is True:
                    return WriteResult("COMMENT_WRITTEN", body, summary, detail, keyword, attempts=attempt)
                feedback = f"AI_FIT_FAILED: {fit.get('reason', '')}"
            except (ValueError, TypeError, KeyError) as exc:
                feedback = f"INVALID_AI_RESPONSE: {exc}"
        return WriteResult("WRITE_FAILED", reason=feedback, attempts=self.max_rewrites + 1)

    def _rule_failure(self, body: str, summary: str, detail: str, keyword: str,
                      source: str, duplicates: set[str]) -> str:
        if not self.min_chars <= len(body) <= self.max_chars:
            return "LENGTH"
        if LINK.search(body):
            return "LINK"
        if normalize_space(body) in duplicates:
            return "DUPLICATE"
        if not summary or not detail or not keyword:
            return "MISSING_GROUNDING"
        if detail not in source or keyword not in source or detail not in body or keyword not in body:
            return "UNSUPPORTED_EVIDENCE"
        return ""
