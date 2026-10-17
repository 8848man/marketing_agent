import json
import sqlite3
from urllib.error import HTTPError

import pytest

from marketing_agent.ai_client import (ClaudeClient, _parse_json_text, create_ai_client,
                                       test_ai_connection as probe_ai)
from marketing_agent.classifier import Classification, Video
from marketing_agent.fixtures import OFFLINE_BODY, OFFLINE_VIDEO, offline_comment
from marketing_agent.writer import Writer


SOURCE = "연락 고민\n상대가 답장을 하루에 한 번만 해서 서운함. 대화 시간을 정해 보세요."
VIDEO = Video("v", "연락 고민", "상대가 답장을 하루에 한 번만 해서 서운함. 대화 시간을 정해 보세요.")
ON_TOPIC = Classification(True, "yes", False, "no captions", SOURCE)
DRAFT = {"worry_summary": "답장 빈도 고민", "cited_detail": "답장을 하루에 한 번만 해서",
         "keyword": "대화 시간을 정해 보세요", "body":
         "답장을 하루에 한 번만 해서 서운하시겠어요. 대화 시간을 정해 보세요라는 제안처럼 서로 편한 연락 방식을 먼저 이야기해 보세요."}


class AI:
    def __init__(self, drafts, fits=True):
        self.drafts = iter(drafts)
        self.fits = fits
        self.draft_calls = self.fit_calls = 0

    def complete_json(self, system, prompt):
        if '"fits"' in system:
            self.fit_calls += 1
            return {"fits": self.fits, "reason": "bad fit"}
        self.draft_calls += 1
        return next(self.drafts)


def test_off_topic_never_calls_writer_ai():
    ai = AI([])
    result = Writer(ai).write(VIDEO, Classification(False, "other topic", False))
    assert result.state == "SKIPPED_OFF_TOPIC" and ai.draft_calls == 0


def test_offline_fixture_produces_one_publishable_comment():
    result = offline_comment()
    assert result.state == "COMMENT_WRITTEN" and result.body == OFFLINE_BODY
    assert 40 <= len(result.body) <= 120 and result.body == result.body.strip()


def test_rules_retry_duplicate_link_and_unsupported_evidence():
    bad_link = {**DRAFT, "body": DRAFT["body"] + " https://example.com"}
    bad_quote = {**DRAFT, "cited_detail": "영상에 없는 말"}
    ai = AI([DRAFT, bad_link, bad_quote, DRAFT])
    result = Writer(ai).write(VIDEO, ON_TOPIC, existing_comments=["  ".join(DRAFT["body"].split())])
    assert result.state == "WRITE_FAILED" and result.attempts == 4
    assert ai.draft_calls == 4 and ai.fit_calls == 0


def test_ai_fit_failure_rewrites_at_most_three_times():
    ai = AI([DRAFT] * 4, fits=False)
    result = Writer(ai).write(VIDEO, ON_TOPIC)
    assert result.state == "WRITE_FAILED" and result.attempts == 4
    assert ai.draft_calls == ai.fit_calls == 4


def test_rule_failure_then_success_and_unicode_length():
    ai = AI([{**DRAFT, "body": "짧음"}, DRAFT])
    result = Writer(ai).write(VIDEO, ON_TOPIC, recent_comments=["다른 댓글"])
    assert result.state == "COMMENT_WRITTEN" and result.attempts == 2
    assert result.cited_detail in SOURCE and result.keyword in SOURCE


def test_no_evidence_is_write_failed_without_ai():
    ai = AI([])
    result = Writer(ai).write(Video("v", "", ""), Classification(True, "yes", False))
    assert result.state == "WRITE_FAILED" and ai.draft_calls == 0


def test_stored_dry_run_comment_is_deduplicated():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE comments (body TEXT, state TEXT)")
    db.execute("INSERT INTO comments VALUES (?, 'DRY_RUN_SAVED')", ("  ".join(DRAFT["body"].split()),))
    store = type("StoreStub", (), {"db": db})()
    ai = AI([DRAFT] * 4)
    result = Writer(ai, store=store).write(VIDEO, ON_TOPIC)
    assert result.state == "WRITE_FAILED" and ai.fit_calls == 0
    db.close()


def test_claude_adapter_uses_injected_transport():
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            return json.dumps({"content": [{"type": "text", "text": '{"fits":true}'}]}).encode()

    def transport(request, timeout):
        requests.append(request)
        return Response()

    assert ClaudeClient("test-key", transport=transport).complete_json("system", "prompt") == {"fits": True}
    assert requests[0].get_header("X-api-key") == "test-key"


def test_ai_adapter_rejects_transport_without_bounded_read():
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            raise AssertionError("unbounded read must not run")

    with pytest.raises(ValueError, match="^AI_TRANSPORT_INVALID$") as error:
        ClaudeClient("test-secret", transport=lambda request, timeout: Response()).complete_json(
            "system", "prompt")
    assert "test-secret" not in str(error.value)


def test_json_parser_recovers_one_object_from_fence_or_explanatory_text():
    expected = {"worry_summary": "연애 고민", "cited_detail": "연애 고민", "comment": "운명원 사주가 궁금해요."}
    payload = json.dumps(expected, ensure_ascii=False)
    assert _parse_json_text(f"```json\n{payload}\n```") == expected
    assert _parse_json_text(f"요청한 결과입니다.\n{payload}\n검토해 주세요.") == expected


def test_json_parser_rejects_empty_broken_or_multiple_objects():
    for value, code in [("", "AI_EMPTY_RESPONSE"), ("설명뿐입니다", "AI_RESPONSE_INVALID"),
                        ('{"a": 1} {"b": 2}', "AI_RESPONSE_INVALID")]:
        try:
            _parse_json_text(value)
            assert False
        except ValueError as exc:
            assert str(exc) == code


def test_four_ai_providers_share_json_contract_and_fixed_hosts():
    requests = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size=None):
            return json.dumps(self.payload).encode()

    def transport(request, timeout):
        requests.append(request)
        assert timeout == 20
        if "anthropic.com" in request.full_url:
            return Response({"content": [{"type": "tool_use", "name": "return_structured_response",
                                           "input": {"worry_summary": "연애 고민", "cited_detail": "연애 고민",
                                                     "comment": "운명원 사주가 궁금해요."}}]})
        if "googleapis.com" in request.full_url:
            return Response({"candidates": [{"content": {"parts": [{"text": '{"worry_summary":"연애 고민","cited_detail":"연애 고민","comment":"운명원 사주가 궁금해요."}'}]}}]})
        return Response({"output": [{"type": "message", "content": [
            {"type": "output_text", "text": '{"worry_summary":"연애 고민","cited_detail":"연애 고민","comment":"운명원 사주가 궁금해요."}'}]}]})

    models = {"openai": "gpt-5.4-mini", "gemini": "gemini-3.5-flash",
              "claude": "claude-sonnet-4-6", "grok": "grok-4.7"}
    for provider, model in models.items():
        assert probe_ai(provider, model, "test-secret", transport=transport)
    assert [request.full_url.split("/")[2] for request in requests] == [
        "api.openai.com", "generativelanguage.googleapis.com",
        "api.anthropic.com", "api.x.ai"]
    assert json.loads(requests[0].data)["store"] is False
    assert json.loads(requests[0].data)["max_output_tokens"] == 512
    assert requests[1].get_header("X-goog-api-key") == "test-secret"
    assert json.loads(requests[1].data)["generationConfig"]["responseMimeType"] == "application/json"
    assert json.loads(requests[1].data)["generationConfig"]["maxOutputTokens"] == 4096
    assert json.loads(requests[1].data)["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "LOW"}
    assert json.loads(requests[0].data)["text"]["format"]["strict"] is True
    gemini_schema = json.loads(requests[1].data)["generationConfig"]["responseSchema"]
    assert gemini_schema["type"] == "OBJECT"
    assert "additionalProperties" not in gemini_schema
    claude_body = json.loads(requests[2].data)
    assert claude_body["tool_choice"] == {"type": "tool", "name": "return_structured_response"}
    assert claude_body["max_tokens"] == 512
    assert claude_body["tools"][0]["input_schema"]["required"] == ["worry_summary", "cited_detail", "comment"]
    assert json.loads(requests[3].data)["text"]["format"]["strict"] is True
    assert json.loads(requests[3].data)["max_output_tokens"] == 512
    assert requests[2].get_header("X-api-key") == "test-secret"
    assert requests[3].get_header("Authorization") == "Bearer test-secret"
    try:
        create_ai_client("gemini", "../invalid", "test-secret", transport=transport)
        assert False
    except ValueError as exc:
        assert str(exc) == "AI_MODEL_INVALID"


def test_ai_http_failure_never_returns_provider_body_or_key():
    def redirected(request, timeout):
        raise HTTPError(request.full_url, 302, "secret in provider error", {}, None)

    try:
        probe_ai("openai", "gpt-5.4-mini", "PRIVATE_KEY", transport=redirected)
        assert False
    except ValueError as exc:
        assert str(exc) == "AI_REDIRECT_BLOCKED"
        assert "PRIVATE_KEY" not in str(exc)


def test_claude_rejects_text_when_structured_output_was_required():
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size=None):
            return b'{"content":[{"type":"text","text":"{}"}]}'

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    try:
        ClaudeClient("test-key", transport=lambda *_args, **_kwargs: Response()).complete_json(
            "system", "prompt", response_schema=schema)
        assert False
    except ValueError as exc:
        assert str(exc) == "AI_RESPONSE_SCHEMA_INVALID"
