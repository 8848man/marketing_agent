from marketing_agent.captions import CaptionResult
from marketing_agent.classifier import Classifier, Video


class AI:
    def __init__(self, on_topic):
        self.on_topic = on_topic
        self.prompts = []

    def complete_json(self, system, prompt):
        self.prompts.append(prompt)
        return {"on_topic": self.on_topic, "reason": "topic checked"}


class Captions:
    def __init__(self, result):
        self.result = result

    def fetch(self, video_id):
        return self.result


def test_caption_failure_falls_back_to_title_description():
    ai = AI(True)
    video = Video("v1", "연애 고민", "연락이 줄어서 걱정")
    result = Classifier(ai, Captions(CaptionResult(failure_reason="DISABLED")), "연애").classify(video)
    assert result.on_topic and not result.used_captions
    assert result.caption_failure_reason == "DISABLED"
    assert "DISABLED" in result.reason
    assert result.source_text == "연애 고민\n연락이 줄어서 걱정"
    assert "연락이 줄어서 걱정" in ai.prompts[0]


def test_caption_exception_and_off_topic():
    class Broken:
        def fetch(self, video_id):
            raise RuntimeError("blocked")

    result = Classifier(AI(False), Broken(), "연애").classify(Video("v", "자동차", "엔진 수리"))
    assert not result.on_topic and not result.used_captions
    assert "RuntimeError: blocked" in result.caption_failure_reason


def test_available_captions_are_in_source():
    result = Classifier(AI(True), Captions(CaptionResult("구체 자막")), "연애").classify(Video("v", "제목", "설명"))
    assert result.used_captions and result.caption_failure_reason is None
    assert "구체 자막" in result.source_text
