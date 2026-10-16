"""Topic classification with an explicit caption fallback and audit reason."""

from dataclasses import dataclass
import json

from .ai_client import AIClient
from .captions import CaptionProvider, CaptionResult


@dataclass(frozen=True)
class Video:
    video_id: str
    title: str
    description: str


@dataclass(frozen=True)
class Classification:
    on_topic: bool
    reason: str
    used_captions: bool
    caption_failure_reason: str | None = None
    source_text: str = ""


class Classifier:
    def __init__(self, ai: AIClient, captions: CaptionProvider, topic: str):
        self.ai, self.captions, self.topic = ai, captions, topic

    def classify(self, video: Video) -> Classification:
        try:
            result = self.captions.fetch(video.video_id)
            if not isinstance(result, CaptionResult):
                raise TypeError("caption provider must return CaptionResult")
        except Exception as exc:
            result = CaptionResult(failure_reason=f"{type(exc).__name__}: {exc}")
        used = result.available
        failure = None if used else (result.failure_reason or "EMPTY_CAPTIONS")
        source = "\n".join(part for part in (video.title, video.description, result.text if used else "") if part)
        prompt = json.dumps({"topic": self.topic, "title": video.title, "description": video.description,
                             "captions": result.text if used else None}, ensure_ascii=False)
        response = self.ai.complete_json(
            'Determine whether this video concerns the topic. Return JSON {"on_topic": boolean, "reason": string}. '
            "Use only supplied video text; do not infer missing content.", prompt)
        if type(response.get("on_topic")) is not bool:
            raise ValueError("classifier response needs boolean on_topic")
        reason = str(response.get("reason", "")).strip()
        if failure:
            reason = f"captions unavailable ({failure}); {reason}"
        return Classification(response["on_topic"], reason, used, failure, source)
