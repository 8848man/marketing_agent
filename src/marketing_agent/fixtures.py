"""Deterministic offline input and AI responses; no credentials or network needed."""

from .captions import CaptionResult
from .classifier import Classifier, Video
from .writer import Writer, WriteResult


OFFLINE_VIDEO = Video("offline-relationship-1", "연락 빈도 때문에 서운한 연애 고민",
                      "상대가 답장을 하루에 한 번만 해서 서운하다는 고민과 대화 시간을 정해 보라는 조언")
OFFLINE_BODY = "답장을 하루에 한 번만 해서 서운하셨겠어요. 대화 시간을 정해 보라는 조언처럼 서로 편한 연락 빈도를 차분히 이야기해 보세요."


class OfflineCaptions:
    def fetch(self, video_id: str) -> CaptionResult:
        return CaptionResult(failure_reason="OFFLINE_NO_CAPTIONS")


class OfflineAI:
    def complete_json(self, system: str, prompt: str) -> dict:
        if '"on_topic"' in system:
            return {"on_topic": True, "reason": "연애 연락 고민"}
        if '"fits"' in system:
            return {"fits": True, "reason": "영상 고민과 근거에 맞음"}
        return {"worry_summary": "연락 빈도 때문에 서운함", "cited_detail": "답장을 하루에 한 번만 해서",
                "keyword": "대화 시간을 정해 보라는 조언", "body": OFFLINE_BODY}


def offline_comment() -> WriteResult:
    ai = OfflineAI()
    result = Classifier(ai, OfflineCaptions(), "연애 상담").classify(OFFLINE_VIDEO)
    return Writer(ai).write(OFFLINE_VIDEO, result)
